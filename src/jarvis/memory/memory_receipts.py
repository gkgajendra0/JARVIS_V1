"""What memory actually did for each owner turn: the only source of truth for
any statement that something was saved, changed or forgotten.

Two writers, both after the operation itself returned:

- explicit memory tools (remember / correct / forget), on ``ok`` results;
- automatic learning, when a turn's learning finishes (committed mutations,
  or nothing changed, or dropped).

Readers: the ``memory_status`` tool (Jarvis confirms only what is recorded
here) and the reply claim check (jarvis.voice.memory_claims), which corrects a
reply that claimed a change this record does not show.

Content-light and bounded: operation kinds and the labels of the facts the
owner just stated; per conversation, the most recent turns only.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_TURNS = 64

# Operation kinds, as the claim check groups them.
SAVE_OPERATIONS = frozenset(
    {"remember", "already_saved", "create", "refine", "change", "correct"}
)
FORGET_OPERATIONS = frozenset({"forget", "retract", "suppress"})


@dataclass(frozen=True)
class MemoryOperation:
    source: str  # "explicit" | "learning"
    operation: str
    label: str | None = None


@dataclass
class _Turn:
    operations: list = field(default_factory=list)
    learning: str = "none"  # none | pending | finished
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
        else:
            self._turns.move_to_end(key)
        return turn

    # writers -------------------------------------------------------------

    def learning_started(self, session_id, turn_id) -> None:
        turn = self._turn(session_id, turn_id)
        turn.learning = "pending"
        turn.done = asyncio.Event()

    def learning_finished(self, session_id, turn_id, status, operations=()) -> None:
        turn = self._turn(session_id, turn_id)
        turn.operations.extend(
            MemoryOperation("learning", action, label) for action, label in operations
        )
        turn.learning, turn.learning_status = "finished", status
        if turn.done is not None:
            turn.done.set()

    def explicit(self, session_id, turn_id, operation, labels=()) -> None:
        """An explicit memory tool returned ok for this owner turn."""
        turn = self._turn(session_id, turn_id)
        for label in labels or (None,):
            turn.operations.append(MemoryOperation("explicit", operation, label))

    # readers -------------------------------------------------------------

    async def wait_learning(self, session_id, turn_id, timeout: float) -> bool:
        """Wait (bounded) for this turn's learning. True when finished or when
        learning never started for it (nothing will arrive)."""
        turn = self._turns.get((session_id, turn_id))
        if turn is None or turn.learning != "pending" or turn.done is None:
            return True
        try:
            await asyncio.wait_for(turn.done.wait(), timeout)
        except TimeoutError:
            return False
        return True

    def operations(self, session_id, turn_id) -> tuple[MemoryOperation, ...]:
        turn = self._turns.get((session_id, turn_id))
        return tuple(turn.operations) if turn else ()

    def pending(self, session_id, turn_id) -> bool:
        turn = self._turns.get((session_id, turn_id))
        return bool(turn and turn.learning == "pending")

    def view(self, session_id, turn_id) -> dict:
        """What the memory_status tool returns: what was verifiably done for
        this owner turn, never more."""
        ops = self.operations(session_id, turn_id)
        if self.pending(session_id, turn_id):
            status = "still_processing"
        elif any(o.operation in FORGET_OPERATIONS for o in ops):
            status = (
                "forgotten"
                if all(o.operation in FORGET_OPERATIONS for o in ops)
                else "changed"
            )
        elif ops:
            status = "saved"
        else:
            status = "nothing_saved"
        return {
            "status": status,
            "operations": [
                {"operation": o.operation, "item": o.label}
                for o in ops
                if o.label or o.operation
            ],
            "rule": (
                "Confirm only what is listed here. still_processing: say you are "
                "still taking it in, not that it is saved. nothing_saved: say it was "
                "not saved (ask the owner to rephrase, or use the explicit memory "
                "tools when they asked you to remember, correct or forget)."
            ),
        }

    def clear(self, session_id=None) -> None:
        for key in list(self._turns):
            if session_id is None or key[0] == session_id:
                turn = self._turns.pop(key)
                if turn.done is not None:
                    turn.done.set()
