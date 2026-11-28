"""When the reply to an owner turn is over, and which owner turn it acts for.

Automatic learning holds its write for an owner turn until Jarvis's reply to
that turn is over, so an explicit memory request made in that reply
(remember / correct / forget, with its consent prompt) is known first and
claims the turn (live voice 27 Nov, turn d6e0274b).

A reply is a chain: one or more generations (speech handles), with tool calls
between them. Personal-context corrections read the catalog first and call
correct_memory in the next generation; with realtime models LiveKit reports
the agent as "listening" between those generations, so the agent state is no
signal. The chain is tracked from speech handles instead:

- the first speech handle starts the chain and binds the latest accepted
  owner turn as its request;
- a handle that finished with a tool call continues the chain (its follow-up
  generation comes next); a handle that finished without one, or was
  interrupted, ends it once no handle is open;
- an owner turn accepted while the chain has not run a tool yet becomes its
  request (a late transcript of the triggering utterance); one accepted after
  a tool ran is an interloper: the chain keeps its request, and memory tools
  refuse to act for either turn;
- a chain idle for longer than CHAIN_IDLE_SECONDS (a tool with no follow-up)
  expires.

A turn is settled when the chain that answered it ended, or, outside any
chain, when a newer owner turn or an assistant turn is accepted, or the
conversation ends. Without a speech feed (text harnesses) every tool acts for
the latest owner turn and an accepted assistant turn settles it. A turn this
tracker never saw is never settled (learning drops rather than guesses).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic

from jarvis.conversation import ConversationRole

MAX_TURNS = 256
CHAIN_IDLE_SECONDS = 30.0


class ReplySettlement:
    def __init__(
        self,
        limit: int = MAX_TURNS,
        *,
        speech_feed: bool = False,
        clock=monotonic,
        activity_epoch=None,
    ):
        self._limit = limit
        self._events: OrderedDict[str, asyncio.Event] = OrderedDict()
        self._waiting: set[str] = set()  # replied or superseded, chain running
        self._closed = False
        self._speech_feed = speech_feed
        self._clock = clock
        self._latest_user: str | None = None
        self._latest_epoch: int | None = None
        self._turn_epochs: dict[str, int] = {}
        self._epoch_turns: dict[int, str] = {}
        self._speech_epoch = None
        self._chain_request: str | None = None
        self._chain_tool = False
        self._open = 0
        self._last_activity = 0.0
        # The user activity the chain answers (conversation epoch when its
        # first generation started): an accepted turn of that same activity is
        # the chain's request even if a tool already ran (tools can run before
        # the transcript is accepted).
        self._activity_epoch = activity_epoch or (lambda: None)
        self._chain_epoch = None
        self._chain_pre_turn = False
        self._expiry = None

    # --- conversation ------------------------------------------------------

    def observe(self, turn) -> None:
        self._expire()
        if turn.role is ConversationRole.USER:
            self._latest_user = turn.turn_id
            self._latest_epoch = getattr(turn, "user_activity_epoch", None)
            if self._latest_epoch is not None:
                self._turn_epochs[turn.turn_id] = self._latest_epoch
                self._epoch_turns[self._latest_epoch] = turn.turn_id
                while len(self._turn_epochs) > self._limit:
                    old_turn = next(iter(self._turn_epochs))
                    self._epoch_turns.pop(self._turn_epochs.pop(old_turn), None)
            pending = [t for t, e in self._events.items() if not e.is_set()]
            if self._chain_request is not None:
                self._waiting.update(pending)
                epoch = getattr(turn, "user_activity_epoch", None)
                if not self._chain_tool or (
                    # Once: only while the request is still the turn from
                    # before the chain started (a second final transcript of
                    # the same speech never takes the binding over).
                    self._chain_pre_turn
                    and epoch is not None
                    and epoch == self._chain_epoch
                ):
                    self._chain_request = turn.turn_id
                    self._chain_pre_turn = False
            else:
                self._settle(pending)
            event = asyncio.Event()
            if self._closed:
                event.set()
            self._events[turn.turn_id] = event
            while len(self._events) > self._limit:
                turn_id, old = self._events.popitem(last=False)
                old.set()
                self._waiting.discard(turn_id)
        elif turn.role is ConversationRole.ASSISTANT:
            pending = [t for t, e in self._events.items() if not e.is_set()]
            if self._chain_request is not None:
                self._waiting.update(pending)
            else:
                self._settle(pending)

    # --- reply chain (speech handles and tools) ---------------------------

    def speech_started(self) -> None:
        if not self._speech_feed:
            return
        self._expire()
        if self._chain_request is None:
            self._start_chain()
            self._chain_tool = False
        try:
            self._speech_epoch = self._activity_epoch()
        except Exception:  # noqa: BLE001 - no epoch: per-generation binding off
            self._speech_epoch = None
        self._open += 1
        self._last_activity = self._clock()

    def speech_finished(self, *, tool_call: bool, interrupted: bool) -> None:
        if not self._speech_feed:
            return
        self._open = max(0, self._open - 1)
        self._last_activity = self._clock()
        if (interrupted or not tool_call) and self._open == 0:
            self._end_chain()
        elif self._open == 0:
            self._arm_expiry()

    def tool_started(self) -> None:
        if not self._speech_feed:
            return
        self._expire()
        if self._chain_request is None:
            self._start_chain()
        self._chain_tool = True
        self._last_activity = self._clock()

    def bind_request(self) -> str | None:
        """The owner turn a memory, personal-context or project tool call acts
        for: the request of the reply chain it runs in (see the module
        docstring), never simply whichever turn is latest now."""
        if not self._speech_feed:
            return self._latest_user
        self.tool_started()
        return self._chain_request

    def latest_user(self) -> str | None:
        return self._latest_user

    def activity_epoch(self):
        """The conversation's user activity epoch now."""
        try:
            return self._activity_epoch()
        except Exception:  # noqa: BLE001
            return None

    def speech_epoch(self):
        """The user activity epoch when the latest generation started."""
        return self._speech_epoch

    def current_request(self, speech_epoch=None) -> str | None:
        """The owner turn the generation that started at ``speech_epoch`` (user
        activity epoch at its start) answers, or None while that activity's
        transcript has not been accepted yet.

        A generation that starts after newer user activity than its chain's
        request (someone spoke after the request: a barge-in, an interloper
        before a tool follow-up) answers that newer activity, never the
        earlier, possibly verified, request."""
        if not self._speech_feed:
            return self._latest_user
        epoch = speech_epoch if speech_epoch is not None else self._speech_epoch
        request = self._chain_request or self._latest_user
        if epoch is None:
            return request
        if self._turn_epochs.get(request) == epoch:
            return request
        newer = self._epoch_turns.get(epoch)
        if newer is not None:
            return newer
        request_epoch = self._turn_epochs.get(request)
        if request_epoch is not None and request_epoch > epoch:
            return request  # a generation older than its accepted request
        return None

    def _start_chain(self) -> None:
        self._chain_request = self._latest_user
        self._chain_pre_turn = True
        try:
            self._chain_epoch = self._activity_epoch()
        except Exception:  # noqa: BLE001 - no epoch: rebinding by epoch off
            self._chain_epoch = None

    def _end_chain(self) -> None:
        self._chain_request = None
        self._chain_tool = False
        self._chain_epoch = None
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self._settle(tuple(self._waiting))

    def _arm_expiry(self) -> None:
        """A tool step with no follow-up generation (a stopped response, a
        follow-up that never came) ends the chain after CHAIN_IDLE_SECONDS
        even if nothing else happens."""
        if self._expiry is not None:
            self._expiry.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._expiry = loop.call_later(CHAIN_IDLE_SECONDS + 0.1, self._expire)

    def _expire(self) -> None:
        if (
            self._chain_request is not None
            and self._open == 0
            and self._clock() - self._last_activity > CHAIN_IDLE_SECONDS
        ):
            self._end_chain()

    # --- settlement ----------------------------------------------------------

    def _settle(self, turn_ids) -> None:
        for turn_id in tuple(turn_ids):
            event = self._events.get(turn_id)
            if event is not None:
                event.set()
            self._waiting.discard(turn_id)

    def close(self) -> None:
        self._closed = True
        self._chain_request = None
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self._settle(tuple(self._events))

    async def wait(self, turn_id: str, timeout: float) -> bool:
        event = self._events.get(turn_id)
        if event is None or timeout <= 0:
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return False
        return True
