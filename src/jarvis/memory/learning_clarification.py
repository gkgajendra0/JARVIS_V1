"""Structured "meaning unclear" learning outcomes for the reply path.

Learning stores nothing it cannot tell the meaning of (learning_values.
normalized_slots, LearningPolicy ``meaning_unclear``). This module turns those
same structural conditions into a note the reply can ask about:

- a proposal the extractor itself marked uncertain (whole fact);
- a plan detail marked uncertain, or a lone option (a mention, not a choice).

Nothing here interprets wording: the conditions are the proposal's own
structure, the same ones that keep the detail out of storage. Only these
conditions make a note. Every other skip (duplicates, suppression, unsupported
or unsaid text, ambiguous targets, questions) stays silent.

A note carries the owner's own words for the unclear detail, which details are
already known (so the reply never asks for them again), and nothing about
storage, so the reply has no receipt to claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .learning_values import SLOT_NAMES

MAX_PENDING = 4


def _slot_parts(slot):
    return [o for o in dict.fromkeys(slot.options or []) if o]


def unclear_slot_names(slots) -> tuple[str, ...]:
    """Details the proposal mentions without a meaning learning can store:
    marked uncertain, or a single option with no stated value."""
    if slots is None:
        return ()
    names = []
    for name in SLOT_NAMES:
        slot = getattr(slots, name)
        if slot is None:
            continue
        options = _slot_parts(slot)
        uncertain = slot.certainty == "uncertain" and (slot.value or options)
        lone_mention = len(options) == 1 and not slot.value
        if uncertain or lone_mention:
            names.append(name)
    return tuple(names)


def _known(candidate, unclear) -> dict[str, str]:
    known = {}
    slots = candidate.slots
    if slots is not None:
        for name in SLOT_NAMES:
            slot = getattr(slots, name)
            if slot is None or name in unclear or slot.certainty == "uncertain":
                continue
            options = _slot_parts(slot)
            if slot.value:
                known[name] = slot.value
            elif len(options) >= 2:
                known[name] = " or ".join(options) + " (undecided)"
    return known


@dataclass(frozen=True)
class LearningClarification:
    session_id: str
    turn_id: str
    category: str
    subject: str
    details: tuple[str, ...]
    owner_words: tuple[str, ...]
    known: tuple[tuple[str, str], ...] = field(default=())

    @property
    def key(self):
        return (self.session_id, self.category, self.subject.casefold(), self.details)

    def model_view(self) -> dict:
        """What the reply sees: inert data from the owner's own words."""
        return {
            "about": self.category,
            "subject": self.subject,
            "unclear": list(self.details) or ["what was meant"],
            "owner_words": list(self.owner_words),
            "already_known": dict(self.known),
        }


def clarification_for(source, candidate, *, dropped_unclear=False):
    """The note for one proposal, or None when nothing about its meaning is
    unclear. ``dropped_unclear``: the policy dropped the whole proposal as
    meaning_unclear (nothing of it was stored)."""
    subject = candidate.label or candidate.value or ""
    if not subject:
        return None
    if dropped_unclear:
        details, words = (), [candidate.label, candidate.value]
        known = {}
    else:
        details = unclear_slot_names(candidate.slots)
        if not details:
            return None
        words = []
        for name in details:
            slot = getattr(candidate.slots, name)
            words += [slot.value, *_slot_parts(slot)]
        known = _known(candidate, details)
    words = tuple(w for w in dict.fromkeys(words) if w)
    return LearningClarification(
        source.session_id,
        source.turn_id,
        candidate.category,
        subject,
        details,
        words,
        tuple(known.items()),
    )


def stated_details(candidate) -> set[str]:
    """Details this proposal states clearly (a value that is not uncertain)."""
    slots = candidate.slots
    if slots is None:
        return set()
    return {
        name
        for name in SLOT_NAMES
        if (slot := getattr(slots, name)) is not None
        and slot.value
        and slot.certainty != "uncertain"
    }


class ClarificationBoard:
    """Session-bound pending notes. A detail is offered once per session: it
    is never asked about again unless a later turn resolved it and the owner
    made it unclear afresh. Bounded; cleared on close or invalidation."""

    def __init__(self, limit: int = MAX_PENDING):
        self._limit = limit
        self._pending: dict[tuple, LearningClarification] = {}
        self._offered: set[tuple] = set()

    def offer(self, note: LearningClarification) -> bool:
        if note.key in self._offered:
            return False
        self._offered.add(note.key)
        self._pending[note.key] = note
        while len(self._pending) > self._limit:
            self._pending.pop(next(iter(self._pending)))
        return True

    def resolve(self, session_id, category, subject, details) -> None:
        """A later clear statement of these details settles the notes about
        them; the subject must name the same fact."""
        subject = (subject or "").casefold()
        for key in list(self._offered):
            s, c, subj, d = key
            if s == session_id and c == category and subj == subject:
                remaining = tuple(x for x in d if x not in details)
                if d and not remaining:
                    self._offered.discard(key)
                    self._pending.pop(key, None)

    def pending(self, session_id, turn_id=None) -> list[LearningClarification]:
        return [
            n
            for n in self._pending.values()
            if n.session_id == session_id and (turn_id is None or n.turn_id == turn_id)
        ]

    def take(self, session_id, turn_id=None) -> list[LearningClarification]:
        """The notes to deliver now; once taken, they are not delivered again."""
        notes = self.pending(session_id, turn_id)
        for note in notes:
            self._pending.pop(note.key, None)
        return notes

    def clear(self, session_id=None) -> None:
        if session_id is None:
            self._pending.clear()
            self._offered.clear()
            return
        for key in [k for k in self._offered if k[0] == session_id]:
            self._offered.discard(key)
            self._pending.pop(key, None)
