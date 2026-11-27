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

- ``confirmed`` alternatives are stored as an undecided choice;
- ``chosen``: the decided value, said in a statement of the owner's current
  turn, is stored on the same plan (:func:`chosen_values`);
- ``doesnt_matter`` discards the pending detail;
- no answer leaves it unsaved; it ends with the conversation.

An answer never depends on the extractor repeating the plan's name or its
earlier evidence: the question supplies both (:func:`answer_candidate`), and
reconciliation is bound to the question's canonical plan. The extractor's own
version of the same answer is replaced, not stored beside it. An answer that
cannot be checked (not said in the current turn, contradictory, ambiguous
between plans, or whose original words have left the source) stores nothing
and leaves the question open.
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
    # A plan's predicate survives changes to its assertion and display name.
    plan_predicate: str | None = field(default=None, repr=False)

    @property
    def identity(self):
        return self.plan_predicate, (
            self.subject.casefold() if self.plan_predicate is None else None
        )

    @property
    def key(self):
        return (
            self.session_id,
            self.category,
            self.identity,
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
        # A detail question keeps its proposal: the plan's identity and the
        # owner's original words for a later answer. A whole-fact question
        # has no detail to answer.
        candidate=None if dropped_unclear else candidate,
    )


def alternatives_questions(source, candidate):
    """One independently answerable question per unconfirmed plan detail."""
    pending = pending_alternatives(candidate)
    subject = _subject(candidate)
    if not pending or not subject:
        return []
    skip = set(pending) | set(unclear_slot_names(candidate.slots))
    known = tuple(_known(candidate, skip).items())
    return [
        LearningClarification(
            source.session_id,
            source.turn_id,
            candidate.category,
            subject,
            (detail,),
            options,
            known,
            kind=ALTERNATIVES,
            choices=((detail, options),),
            candidate=candidate,
        )
        for detail, options in pending.items()
    ]


def _statement_sentences(text):
    """Spans of the sentences of ``text`` that are statements, not questions."""
    out, start = [], 0
    for index, char in enumerate(text):
        if char in ".!?\n":
            if char != "?" and text[start:index].strip():
                out.append((start, index + 1))
            start = index + 1
    if text[start:].strip() and not text[start:].rstrip().endswith("?"):
        out.append((start, len(text)))
    return out


def has_statement(text) -> bool:
    """Whether a turn says anything other than questions."""
    return bool(_statement_sentences(text))


def said_now(text, value):
    """The owner's own spelling of ``value`` in a statement (not a question)
    of the current turn, or None. Case is the only difference allowed."""
    if not value:
        return None
    sentences = _statement_sentences(text)
    folded, wanted = text.lower(), value.lower()
    if len(folded) != len(text):
        folded, wanted = text, value
    at = folded.find(wanted)
    while at >= 0:
        end = at + len(wanted)
        whole = (at == 0 or not text[at - 1].isalnum()) and (
            end == len(text) or not text[end].isalnum()
        )
        if whole and any(s <= at and end <= e for s, e in sentences):
            return text[at:end]
        at = folded.find(wanted, at + 1)
    return None


def _options(note, detail):
    return dict(note.choices).get(detail) or (
        note.owner_words if note.kind == UNCLEAR else ()
    )


def _decided(slot):
    return (
        slot is not None
        and slot.value
        and not _slot_parts(slot)
        and slot.certainty == "confirmed"
    )


def chosen_values(source, notes, candidates):
    """The value the owner chose for each answered question, or why not.

    The extractor reads the meaning (which question, which value: its proposed
    slot for the detail). Code accepts a value only when it can check it: a
    decided value (confirmed, no options), said in a statement of the owner's
    current turn, and attributable to exactly one question (one of that
    question's own options, or the only question about that detail). Several
    values for one question, or one value claimed by questions on different
    plans, decide nothing.

    Returns ``({question_id: {detail: value}}, [(note, reason)])``.
    """
    text = next((t.text for t in source.turns if t.turn_id == source.turn_id), "")
    said: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.category != "plan" or candidate.slots is None:
            continue
        for name in SLOT_NAMES:
            slot = getattr(candidate.slots, name)
            if _decided(slot) and (owner := said_now(text, slot.value)):
                said.setdefault(name, []).append(owner)
    asking: dict[str, int] = {}
    for note in notes:
        for detail in note.details:
            asking[detail] = asking.get(detail, 0) + 1
    values, refused = {}, []
    for note in notes:
        if note.plan_predicate is None or note.candidate is None:
            refused.append((note, "unbound_question"))
            continue
        chosen, reason = {}, None
        for detail in note.details:
            heard = list(dict.fromkeys(v.casefold() for v in said.get(detail, ())))
            options = {o.casefold() for o in _options(note, detail)}
            among = [v for v in heard if v in options]
            pick = among or (heard if asking[detail] == 1 else [])
            if not pick:
                reason = "choice_not_stated"
                break
            if len(pick) > 1:
                reason = "contradictory_choice"
                break
            chosen[detail] = next(v for v in said[detail] if v.casefold() == pick[0])
        if reason:
            refused.append((note, reason))
        else:
            values[note.question_id] = chosen
    claims: dict[tuple, set] = {}
    for note in notes:
        for detail, value in values.get(note.question_id, {}).items():
            claims.setdefault((detail, value.casefold()), set()).add(
                note.plan_predicate
            )
    for note in notes:
        chosen = values.get(note.question_id)
        if chosen and any(
            len(claims[(d, v.casefold())]) > 1 for d, v in chosen.items()
        ):
            del values[note.question_id]
            refused.append((note, "ambiguous_choice"))
    return values, refused


def answers_the_question(candidate, notes, values) -> bool:
    """Whether a proposal is the extractor's own version of these answers (a
    plan stating an answered detail as one of that question's options, as its
    chosen value, or as those options again). It is replaced by the answer the
    question supports, never stored beside it."""
    if candidate.category != "plan" or candidate.slots is None:
        return False
    for note in notes:
        for detail in note.details:
            slot = getattr(candidate.slots, detail, None)
            if slot is None:
                continue
            known = {o.casefold() for o in _options(note, detail)}
            chosen = values.get(note.question_id, {}).get(detail)
            if chosen:
                known.add(chosen.casefold())
            stated = {o.casefold() for o in _slot_parts(slot)}
            if slot.value:
                stated.add(slot.value.casefold())
            if stated & known:
                return True
    return False


def answer_candidate(source, confirmed, chosen, extra_slots=None):
    """One proposal for the owner's answers to questions on one plan.

    Identity (label, value, kind) and the original evidence come from the
    trusted question: the owner's original words, which must still be in this
    learning source; the current turn is cited in full. Only the answered
    details are proposed: confirmed alternatives stay undecided
    (``owner_confirmed``); a choice is the decided value code checked
    (:func:`chosen_values`). ``extra_slots``: other decided details said in the
    current turn. It then passes the ordinary policy, resolution and
    reconciliation bound to the question's plan. ``(None, reason)`` when the
    original words are no longer available (nothing is stored)."""
    from .learning_contracts import EvidenceSpan, LearningCandidate

    notes = [*confirmed, *(note for note, _ in chosen)]
    original = notes[0].candidate
    if original is None:
        return None, "unbound_question"
    window = {t.turn_id for t in source.turns}
    spans = []
    for note in notes:
        if note.candidate is None or note.turn_id not in window:
            return None, "original_evidence_expired"
        kept = [s for s in note.candidate.evidence if s.turn_id in window]
        if not kept:
            return None, "original_evidence_expired"
        spans += [s for s in kept if s not in spans]
    latest = next(t for t in source.turns if t.turn_id == source.turn_id)
    if all(s.turn_id != latest.turn_id for s in spans):
        spans.append(
            EvidenceSpan(turn_id=latest.turn_id, start=0, end=len(latest.text))
        )
    slots = dict(extra_slots or {})
    for note in confirmed:
        for name, options in note.choices:
            slots[name] = {
                "value": None,
                "options": list(options),
                "certainty": "tentative",
            }
    for _, values in chosen:
        for name, value in values.items():
            slots[name] = {"value": value, "options": [], "certainty": "confirmed"}
    # Identity only: the question's earlier restated facts (time, place,
    # status, aliases) are not part of the answer and could be stale.
    data = original.model_dump(mode="json", exclude={"evidence", "slots"})
    data.update(
        {
            "time_expression": None,
            "location": None,
            "reason": None,
            "details": None,
            "aliases": [],
            "acquired_expression": None,
            "disposed_expression": None,
            "plan_status": None,
        }
    )
    return LearningCandidate.model_validate(
        {
            **data,
            "intent": "new",
            "slots": slots,
            "evidence": [s.model_dump() for s in spans],
            "owner_confirmed": tuple(
                name for note in confirmed for name, _ in note.choices
            ),
        }
    ), None


def current_turn_details(source, candidate, skip) -> dict:
    """Decided details of an answering proposal that the owner said in a
    statement of the current turn (never a restated earlier detail)."""
    text = next((t.text for t in source.turns if t.turn_id == source.turn_id), "")
    out = {}
    if candidate.category != "plan" or candidate.slots is None:
        return out
    for name in SLOT_NAMES:
        slot = getattr(candidate.slots, name)
        if name in skip or not _decided(slot):
            continue
        if owner := said_now(text, slot.value):
            out[name] = {"value": owner, "options": [], "certainty": "confirmed"}
    return out


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
        """Open a question unless this fact and detail already have one."""
        if note.key in self._open or any(
            n.session_id == note.session_id
            and n.category == note.category
            and n.identity == note.identity
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

    def resolve(
        self, session_id, category, subject, details, *, plan_predicate=None
    ) -> list:
        """A later clear statement of these details settles the questions
        about them on the same fact."""
        identity = (
            plan_predicate,
            (subject or "").casefold() if plan_predicate is None else None,
        )
        settled = []
        for note in list(self._open.values()):
            if (
                note.session_id == session_id
                and note.category == category
                and note.identity == identity
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
