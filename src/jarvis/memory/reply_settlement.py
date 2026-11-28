"""When the reply to an owner turn is over.

Automatic learning holds its write for an owner turn until Jarvis's reply to
that turn has finished, so an explicit memory request made in that reply
(remember / correct / forget, with its consent prompt) is known first and
claims the turn. Without this, learning could commit before the explicit
tool was even called, and a refused explicit change would already be stored
(live voice 27 Nov, turn d6e0274b, ordering reversed).

A reply can be several generations: personal-context corrections first read
the catalog, may speak ("let me check"), and call correct_memory in the next
generation. A spoken segment is accepted as an assistant turn when its
playout ends, before the tool reply. So a turn is settled only when an
assistant turn was accepted after it AND the agent is back to listening (not
thinking or speaking: no tool call or generation is still running); or when
a newer owner turn is accepted, or the conversation ends. Without an agent
state feed (text harnesses), an accepted assistant turn settles it. A turn
this tracker never saw is never settled (learning drops rather than guesses).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from jarvis.conversation import ConversationRole

MAX_TURNS = 256
_BUSY_STATES = frozenset({"thinking", "speaking"})


class ReplySettlement:
    def __init__(self, limit: int = MAX_TURNS, *, agent_states: bool = False):
        self._limit = limit
        self._events: OrderedDict[str, asyncio.Event] = OrderedDict()
        self._replied: set[str] = set()
        self._closed = False
        # With an agent state feed, a reply is over only once the agent is
        # not thinking or speaking.
        self._agent_states = agent_states
        self._agent_busy = agent_states
        self._latest_user: str | None = None
        self._bound_request: str | None = None

    def observe(self, turn) -> None:
        if turn.role is ConversationRole.USER:
            self._latest_user = turn.turn_id
            # A newer owner turn supersedes earlier ones, but while a reply
            # (a tool chain) is still running for one of them it is not over:
            # it settles when the agent is back to listening.
            pending = [t for t, e in self._events.items() if not e.is_set()]
            if self._agent_busy:
                self._replied.update(pending)
            else:
                self._settle(pending)
            event = asyncio.Event()
            if self._closed:
                event.set()
            self._events[turn.turn_id] = event
            while len(self._events) > self._limit:
                turn_id, old = self._events.popitem(last=False)
                old.set()
                self._replied.discard(turn_id)
        elif turn.role is ConversationRole.ASSISTANT:
            self._replied.update(
                turn_id for turn_id, event in self._events.items() if not event.is_set()
            )
            if not self._agent_busy:
                self._settle(tuple(self._replied))

    def agent_state(self, state: str) -> None:
        if not self._agent_states:
            return
        self._agent_busy = state in _BUSY_STATES
        if not self._agent_busy:
            self._bound_request = None
            self._settle(tuple(self._replied))

    def bind_request(self) -> str | None:
        """The owner turn a memory or personal-context tool call acts for.

        The first tool call of a reply binds the latest accepted owner turn;
        later tool calls of the same reply (until the agent is back to
        listening) keep that binding even if another utterance was accepted
        meanwhile, so a correction resolved for one request is never applied
        to, or excluded from learning for, whichever turn is latest."""
        if (
            self._agent_states
            and self._agent_busy
            and self._bound_request in self._events
        ):
            return self._bound_request
        self._bound_request = self._latest_user
        return self._bound_request

    def _settle(self, turn_ids) -> None:
        for turn_id in turn_ids:
            event = self._events.get(turn_id)
            if event is not None:
                event.set()
            self._replied.discard(turn_id)

    def close(self) -> None:
        self._closed = True
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
