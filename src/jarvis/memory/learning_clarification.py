"""Open questions from learning: unclear meaning and unconfirmed alternatives.

Learning stores nothing it cannot tell the meaning of, and it does not store
alternatives on the model's reading alone (learning_values.normalized_slots,
LearningPolicy ``meaning_unclear``). This module turns those same structural
conditions into an open question for the conversation:

- ``unclear``: a proposal the extractor marked uncertain (whole fact), a plan
  detail marked uncertain, or a lone option (a mention, not a choice);
- ``confirm_alternatives``: a plan detail proposed as two or more options,
  whatever certainty the model gave them. They stay pending here, never in
  storage, until the owner confirms them.

Nothing here interprets wording: the conditions are the proposal's own
structure. Every other skip (duplicates, suppression, unsupported or unsaid
text, ambiguous targets, questions) stays silent.

A question carries the owner's own words, the details already known (never
asked again) and nothing about storage, so the reply has no receipt to claim.
It is asked once and stays open in its conversation until the owner answers
it (the extractor reads the answer; code decides what it allows):

- ``confirmed`` alternatives are stored as an undecided choice, from the
  owner's original words plus the confirming turn (:func:`confirmation_candidate`);
- ``chosen``: the owner's stated value is an ordinary clear proposal;
- ``doesnt_matter`` discards the pending detail;
- no answer leaves it unsaved; it ends with the conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .learning_values import SLOT_NAMES

MAX_OPEN = 4
UNCLEAR, ALTERNATIVES = "unclear", "confirm_alternatives"


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


def pending_alternatives(candidate) -> dict[str, tuple[str, ...]]:
    """Plan details proposed as alternatives (two or more options) that the
    owner has not confirmed: they are not stored, only asked about."""
    slots = candidate.slots
    if candidate.category != "plan" or slots is None:
        return {}
    out = {}
    for name in SLOT_NAMES:
        slot = getattr(slots, name)
        if slot is None or name in candidate.owner_confirmed:
            continue
        options = _slot_parts(slot)
        if len(options) >= 2 and slot.certainty != "uncertain":
            out[name] = tuple(options)
    return out


def _known(candidate, skip) -> dict[str, str]:
    known = {}
    slots = candidate.slots
    if slots is not None:
        for name in SLOT_NAMES:
            slot = getattr(slots, name)
            if slot is None or name in skip or slot.certainty == "uncertain":
                continue
            if slot.value and len(_slot_parts(slot)) < 2:
                known[name] = slot.value
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
    kind: str = UNCLEAR
    choices: tuple[tuple[str, tuple[str, ...]], ...] = field(default=())
    question_id: str = field(default_factory=lambda: uuid4().hex[:12])
    # The proposal the question came from (for a confirmation); never shown.
    candidate: object = field(default=None, compare=False, hash=False, repr=False)

    @property
    def key(self):
        return (
            self.session_id,
            self.category,
            self.subject.casefold(),
            self.details,
            self.kind,
        )

    def model_view(self) -> dict:
        """What the reply and the extractor see: inert data in the owner's own
        words, no storage status."""
        view = {
            "question_id": self.question_id,
            "question": self.kind,
            "about": self.category,
            "subject": self.subject,
        }
        if self.kind == ALTERNATIVES:
            view["choices"] = {name: list(options) for name, options in self.choices}
        else:
            view["unclear"] = list(self.details) or ["what was meant"]
            view["owner_words"] = list(self.owner_words)
        view["already_known"] = dict(self.known)
        return view


def _subject(candidate):
    return candidate.label or candidate.value or ""


def clarification_for(source, candidate, *, dropped_unclear=False):
    """The ``unclear`` question for one proposal, or None. ``dropped_unclear``:
    the policy dropped the whole proposal as meaning_unclear."""
    subject = _subject(candidate)
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
        known = _known(candidate, set(details) | set(pending_alternatives(candidate)))
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


def alternatives_question(source, candidate):
    """The ``confirm_alternatives`` question for a plan proposal whose
    alternatives are not confirmed, or None."""
    pending = pending_alternatives(candidate)
    subject = _subject(candidate)
    if not pending or not subject:
        return None
    skip = set(pending) | set(unclear_slot_names(candidate.slots))
    words = tuple(dict.fromkeys(o for options in pending.values() for o in options))
    return LearningClarification(
        source.session_id,
        source.turn_id,
        candidate.category,
        subject,
        tuple(pending),
        words,
        tuple(_known(candidate, skip).items()),
        kind=ALTERNATIVES,
        choices=tuple(pending.items()),
        candidate=candidate,
    )


def confirmation_candidate(source, note):
    """The owner confirmed the pending alternatives: the same proposal, with
    only those details, citing the owner's original words (still within this
    learning source) and the confirming turn. It then passes the ordinary
    policy, resolution and reconciliation. None when the original words are
    no longer in the source (nothing is stored)."""
    from .learning_contracts import EvidenceSpan, LearningCandidate

    original = note.candidate
    if note.kind != ALTERNATIVES or original is None:
        return None
    window = {t.turn_id for t in source.turns}
    spans = [s for s in original.evidence if s.turn_id in window]
    if not spans or note.turn_id not in window:
        return None
    latest = source.turns[-1]
    if all(s.turn_id != latest.turn_id for s in spans):
        spans.append(
            EvidenceSpan(turn_id=latest.turn_id, start=0, end=len(latest.text))
        )
    slots = {
        name: {"value": None, "options": list(options), "certainty": "tentative"}
        for name, options in note.choices
    }
    data = original.model_dump(mode="json", exclude={"evidence", "slots"})
    return LearningCandidate.model_validate(
        {
            **data,
            "intent": "new",
            "slots": slots,
            "evidence": [s.model_dump() for s in spans],
            "owner_confirmed": tuple(name for name, _ in note.choices),
        }
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
        and len(_slot_parts(slot)) < 2
    }


class ClarificationBoard:
    """Open questions of each conversation. A question is asked once and
    stays open until answered, settled by a later clear statement, or its
    conversation ends; the same question is not raised again while open.
    Bounded; cleared on close or invalidation."""

    def __init__(self, limit: int = MAX_OPEN):
        self._limit = limit
        self._open: dict[tuple, LearningClarification] = {}
        self._asked: set[tuple] = set()

    def offer(self, note: LearningClarification) -> bool:
        """Open a question unless the same detail of the same fact already has
        one open in this conversation (one question per detail)."""
        if note.key in self._open or any(
            n.session_id == note.session_id
            and n.category == note.category
            and n.subject.casefold() == note.subject.casefold()
            and (set(n.details) & set(note.details) or not (n.details or note.details))
            for n in self._open.values()
        ):
            return False
        self._open[note.key] = note
        while len(self._open) > self._limit:
            self.close(next(iter(self._open.values())))
        return True

    def close(self, note) -> None:
        self._open.pop(note.key, None)
        self._asked.discard(note.key)

    def by_id(self, session_id, question_id):
        return next(
            (
                n
                for n in self._open.values()
                if n.session_id == session_id and n.question_id == question_id
            ),
            None,
        )

    def resolve(self, session_id, category, subject, details) -> list:
        """A later clear statement of these details settles the questions
        about them; the subject must name the same fact."""
        subject = (subject or "").casefold()
        settled = []
        for note in list(self._open.values()):
            if (
                note.session_id == session_id
                and note.category == category
                and note.subject.casefold() == subject
                and note.details
                and set(note.details) <= set(details)
            ):
                self.close(note)
                settled.append(note)
        return settled

    def pending(self, session_id, turn_id=None) -> list[LearningClarification]:
        """Open questions of this conversation (optionally of one turn)."""
        return [
            n
            for n in self._open.values()
            if n.session_id == session_id and (turn_id is None or n.turn_id == turn_id)
        ]

    def take(self, session_id, turn_id=None) -> list[LearningClarification]:
        """The questions to ask now; each is asked once and stays open."""
        notes = [
            n for n in self.pending(session_id, turn_id) if n.key not in self._asked
        ]
        self._asked.update(n.key for n in notes)
        return notes

    def clear(self, session_id=None) -> None:
        for note in list(self._open.values()):
            if session_id is None or note.session_id == session_id:
                self.close(note)
