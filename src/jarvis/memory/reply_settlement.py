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
        self, limit: int = MAX_TURNS, *, speech_feed: bool = False, clock=monotonic
    ):
        self._limit = limit
        self._events: OrderedDict[str, asyncio.Event] = OrderedDict()
        self._waiting: set[str] = set()  # replied or superseded, chain running
        self._closed = False
        self._speech_feed = speech_feed
        self._clock = clock
        self._latest_user: str | None = None
        self._chain_request: str | None = None
        self._chain_tool = False
        self._open = 0
        self._last_activity = 0.0

    # --- conversation ------------------------------------------------------

    def observe(self, turn) -> None:
        self._expire()
        if turn.role is ConversationRole.USER:
            self._latest_user = turn.turn_id
            pending = [t for t, e in self._events.items() if not e.is_set()]
            if self._chain_request is not None:
                self._waiting.update(pending)
                if not self._chain_tool:
                    self._chain_request = turn.turn_id
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
            self._chain_request = self._latest_user
            self._chain_tool = False
        self._open += 1
        self._last_activity = self._clock()

    def speech_finished(self, *, tool_call: bool, interrupted: bool) -> None:
        if not self._speech_feed:
            return
        self._open = max(0, self._open - 1)
        self._last_activity = self._clock()
        if (interrupted or not tool_call) and self._open == 0:
            self._end_chain()

    def tool_started(self) -> None:
        if not self._speech_feed:
            return
        self._expire()
        if self._chain_request is None:
            self._chain_request = self._latest_user
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

    def _end_chain(self) -> None:
        self._chain_request = None
        self._chain_tool = False
        self._settle(tuple(self._waiting))

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
