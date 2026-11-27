"""What memory actually did for each owner turn: the only source of truth for
any statement that something was saved, changed or forgotten.

Two writers, both after the operation itself returned:

- explicit memory tools (remember / correct / forget), on ``ok`` results;
- automatic learning, when a turn's learning finishes (committed mutations,
  or nothing changed, or dropped).

Readers: the ``memory_status`` tool (Jarvis confirms only what is recorded
here) and the reply claim check (jarvis.voice.memory_claims), which stops or
corrects a reply that claims a change this record does not show.

Readers look at the owner's most recent turns, not only the latest one: "Did
you save that?" asks about the turn before it, and a reply can start before
the owner turn it answers is accepted.

Content-light and bounded: operation kinds and the labels of the facts
written; per conversation, the most recent turns only.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_TURNS = 64
RECENT_TURNS = 3

# Operation kinds, as claims are checked against them.
SAVE_OPERATIONS = frozenset(
    {"remember", "already_saved", "create", "refine", "change", "correct"}
)
FORGET_OPERATIONS = frozenset({"forget", "retract", "suppress"})


@dataclass(frozen=True)
class MemoryOperation:
    source: str  # "explicit" | "learning"
    operation: str
    label: str | None = None
    turn_id: str | None = None


@dataclass
class _Turn:
    operations: list = field(default_factory=list)
    in_flight: int = 0
    learning_status: str | None = None
    done: asyncio.Event | None = None


class MemoryReceipts:
    def __init__(self, limit: int = MAX_TURNS):
        self._limit = limit
        self._turns: OrderedDict[tuple[str, str], _Turn] = OrderedDict()

    def _turn(self, session_id, turn_id) -> _Turn:
        key = (session_id, turn_id)
        turn = self._turns.get(key)
        if turn is None:
            turn = self._turns[key] = _Turn()
            while len(self._turns) > self._limit:
                old = self._turns.popitem(last=False)[1]
                if old.done is not None:
                    old.done.set()
        return turn

    # writers -------------------------------------------------------------

    def learning_started(self, session_id, turn_id) -> None:
        turn = self._turn(session_id, turn_id)
        turn.in_flight += 1
        if turn.done is None or turn.done.is_set():
            turn.done = asyncio.Event()

    def learning_finished(self, session_id, turn_id, status, operations=()) -> None:
        turn = self._turn(session_id, turn_id)
        turn.operations.extend(
            MemoryOperation("learning", action, label, turn_id)
            for action, label in operations
        )
        turn.learning_status = status
        turn.in_flight = max(0, turn.in_flight - 1)
        if turn.in_flight == 0 and turn.done is not None:
            turn.done.set()

    def explicit(self, session_id, turn_id, operation, labels=()) -> None:
        """An explicit memory tool returned ok for this owner turn."""
        turn = self._turn(session_id, turn_id)
        for label in labels or (None,):
            turn.operations.append(
                MemoryOperation("explicit", operation, label, turn_id)
            )

    # readers -------------------------------------------------------------

    def pending(self, session_id, turn_id) -> bool:
        turn = self._turns.get((session_id, turn_id))
        return bool(turn and turn.in_flight)

    async def wait_learning(self, session_id, turn_ids, timeout: float) -> bool:
        """Wait (bounded) for learning of these turns. True when all finished
        (or never started: nothing will arrive)."""
        if isinstance(turn_ids, str):
            turn_ids = (turn_ids,)
        events = [
            turn.done
            for turn_id in turn_ids
            if (turn := self._turns.get((session_id, turn_id))) is not None
            and turn.in_flight
            and turn.done is not None
        ]
        if not events:
            return True
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in events)), timeout
            )
        except TimeoutError:
            return False
        return True

    def operations(self, session_id, turn_ids) -> tuple[MemoryOperation, ...]:
        if isinstance(turn_ids, str):
            turn_ids = (turn_ids,)
        out = []
        for turn_id in turn_ids:
            turn = self._turns.get((session_id, turn_id))
            if turn is not None:
                out.extend(turn.operations)
        return tuple(out)

    def view(self, session_id, turns) -> dict:
        """What the memory_status tool returns: what was verifiably done for
        the owner's recent turns (newest first), never more.

        ``turns``: (turn_id, owner words) pairs, newest first."""
        entries = []
        for turn_id, words in turns:
            ops = self.operations(session_id, turn_id)
            if self.pending(session_id, turn_id):
                status = "still_processing"
            elif ops and all(o.operation in FORGET_OPERATIONS for o in ops):
                status = "forgotten"
            elif ops:
                status = "saved"
            else:
                status = "nothing_saved"
            entries.append(
                {
                    "owner_words": words,
                    "status": status,
                    "operations": [
                        {"operation": o.operation, "item": o.label} for o in ops
                    ],
                }
            )
        return {
            "turns": entries,
            "rule": (
                "Newest owner turn first. Confirm only what is listed, for the "
                "turn the owner means. still_processing is not saved yet. "
                "nothing_saved means nothing was saved for that turn: say so, and "
                "offer to try again or use the explicit memory tools when the "
                "owner asked to remember, correct or forget."
            ),
        }

    def clear(self, session_id=None) -> None:
        for key in list(self._turns):
            if session_id is None or key[0] == session_id:
                turn = self._turns.pop(key)
                if turn.done is not None:
                    turn.done.set()
