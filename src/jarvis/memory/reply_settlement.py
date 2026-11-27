"""When the reply to an owner turn is over.

Automatic learning holds its write for an owner turn until Jarvis's reply to
that turn has finished, so an explicit memory request made in that reply
(remember / correct / forget, with its consent prompt) is known first and
claims the turn. Without this, learning could commit before the explicit
tool was even called, and a refused explicit change would already be stored
(live voice 27 Nov, turn d6e0274b, ordering reversed).

A turn is settled when an assistant turn is accepted after it, a newer owner
turn is accepted, or the conversation ends. A turn this tracker never saw is
never settled (learning drops rather than guesses).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from jarvis.conversation import ConversationRole

MAX_TURNS = 256


class ReplySettlement:
    def __init__(self, limit: int = MAX_TURNS):
        self._limit = limit
        self._events: OrderedDict[str, asyncio.Event] = OrderedDict()
        self._closed = False

    def observe(self, turn) -> None:
        if turn.role is ConversationRole.USER:
            self._settle_all()
            event = asyncio.Event()
            if self._closed:
                event.set()
            self._events[turn.turn_id] = event
            while len(self._events) > self._limit:
                self._events.popitem(last=False)[1].set()
        elif turn.role is ConversationRole.ASSISTANT:
            self._settle_all()

    def _settle_all(self) -> None:
        for event in self._events.values():
            event.set()

    def close(self) -> None:
        self._closed = True
        self._settle_all()

    async def wait(self, turn_id: str, timeout: float) -> bool:
        event = self._events.get(turn_id)
        if event is None or timeout <= 0:
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return False
        return True
