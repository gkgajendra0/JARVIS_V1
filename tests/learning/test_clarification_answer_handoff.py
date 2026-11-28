"""Clarification-to-memory handoff: the owner's answer to an open question.

The trusted open question (bound by code to its canonical plan, holding the
owner's original words) supplies the plan's identity and its original
evidence. The extractor supplies only the semantic reading: which question was
answered and, for a choice, the chosen value. Code checks that value against
the owner's current turn and the question, then the ordinary policy,
reconciliation (bound to the question's plan) and storage run.

Recorded D28 outputs (lab ef0c9340 and lab 7b580710) are replayed through the
real learning runtime and a fictional database, unmodified apart from evidence
turn ids; structurally different readings of the same answer are replayed too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_slice1_d9_clarification import (  # noqa: F401 - pytest fixture
    CHOICE,
    LAB6,
    TWO_CHOICES,
    _choice,
    _recorded,
    _rows,
    _said,
    _two_choices,
    lab,
)

from jarvis.memory.learning_contracts import LearningCandidate

FIXTURES = Path(__file__).parent / "fixtures"
EF0C = json.loads((FIXTURES / "codex_ef0c9340_d28.json").read_text(encoding="utf-8"))
B580 = json.loads((FIXTURES / "codex_7b580710_d28.json").read_text(encoding="utf-8"))
TAKE = "We'll take the Jimny."
JIMNY = {"value": "Jimny", "options": [], "certainty": "confirmed"}


def _replay(recorded, step, mutate=None):
    """The recorded proposals of ``step``; each cited span is rebound to the
    replayed turn whose text it was recorded against."""
    steps = recorded["steps"]
    first_id = steps["alt-01"]["extraction"]["candidates"][0]["evidence"][0]["turn_id"]

    def build(source):
        raws = json.loads(json.dumps(steps[step]["extraction"]["candidates"]))
        out = []
        for raw in raws:
            for span in raw["evidence"]:
                said = steps["alt-01" if span["turn_id"] == first_id else step][
                    "utterance"
                ]
                span["turn_id"] = next(
                    t.turn_id for t in source.turns if t.text == said
                )
            if mutate is not None:
                raw = mutate(raw, source)
                if raw is None:
                    continue
            out.append(LearningCandidate.model_validate(raw))
        return out

    return build


async def _first_turn(lab, recorded=EF0C):  # noqa: F811
    first = recorded["steps"]["alt-01"]["utterance"]
    lab.script.by_text[first] = _replay(recorded, "alt-01")
    await lab.say(first)
    (before,) = await lab.plans()
    assert "vehicle" not in before["slots"]
    (question,) = lab.seen
    return before, question


async def _answer(lab, text, build, answers=(("chosen", "vehicle"),), target=None):  # noqa: F811
    if build is not None:
        lab.script.by_text[text] = build
    lab.script.answers[text] = list(answers)
    if target is not None:
        lab.resolver.targets[text] = target
    await lab.say(text)


def _assert_decided(before, after):
    assert after["slots"]["vehicle"] == JIMNY
    assert (after["label"], after["value"]) == (before["label"], before["value"])
    assert after["slots"]["when"] == before["slots"]["when"]
    assert after["slots"]["destination"] == before["slots"]["destination"]


# the latest D28 failure, replayed unmodified --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("resolver", ["new", "match"])
async def test_recorded_ef0c9340_d28_answer_decides_the_same_plan(lab, resolver):  # noqa: F811
    before, question = await _first_turn(lab)
    answer = EF0C["steps"]["alt-02"]["utterance"]
    await _answer(
        lab,
        answer,
        _replay(EF0C, "alt-02"),
        target=before["label"] if resolver == "match" else None,
    )
    (after,) = await lab.plans()
    _assert_decided(before, after)
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_recorded_7b580710_d28_answer_citing_both_turns_still_decides(lab):  # noqa: F811
    before, question = await _first_turn(lab, B580)
    await _answer(lab, B580["steps"]["alt-02"]["utterance"], _replay(B580, "alt-02"))
    (after,) = await lab.plans()
    _assert_decided(before, after)
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_the_decision_supersedes_the_plan_row_and_keeps_history(lab, learning):  # noqa: F811
    before, _ = await _first_turn(lab)
    await _answer(lab, TAKE, _replay(EF0C, "alt-02"))
    rows = await _rows(learning.reader)
    assert [state for state, _ in rows] == ["superseded", "active"]
    assert rows[0][1] == before
    ((entry, _),) = await learning.service.canonical_reader.learning_current_scoped()
    assert entry.value["slots"]["vehicle"] == JIMNY
    assert entry.value["plan_status"] == before["plan_status"]


# structurally different readings of the same answer --------------------------


def _reading(mutate=None):
    """The recorded alt-02 reading of an answer, citing whatever the current
    turn is (for answers worded differently), then ``mutate``."""

    def build(source):
        turn = source.turns[-1]
        out = []
        for raw in json.loads(
            json.dumps(EF0C["steps"]["alt-02"]["extraction"]["candidates"])
        ):
            raw["evidence"] = [
                {"turn_id": turn.turn_id, "start": 0, "end": len(turn.text)}
            ]
            if mutate is not None:
                raw = mutate(raw, source)
            if raw is not None:
                out.append(LearningCandidate.model_validate(raw))
        return out

    return build


def _set(**fields):
    def mutate(raw, source):
        return {**raw, **fields}

    return mutate


def _vehicle(value=None, **slot):
    def mutate(raw, source):
        vehicle = dict(raw["slots"]["vehicle"], **slot)
        if value is not None:
            vehicle["value"] = value
        raw["slots"] = {**raw["slots"], "vehicle": vehicle}
        return raw

    return mutate


def _only_vehicle(raw, source):
    raw["slots"] = {"vehicle": raw["slots"]["vehicle"]}
    return raw


def _cite_question_turn(raw, source):
    first = source.turns[0]
    raw["evidence"] = [{"turn_id": first.turn_id, "start": 0, "end": len(first.text)}]
    return raw


def _cite_both(raw, source):
    first, last = source.turns[0], source.turns[-1]
    raw["evidence"] = [
        {"turn_id": first.turn_id, "start": 0, "end": len(first.text)},
        {"turn_id": last.turn_id, "start": 0, "end": len(last.text)},
    ]
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mutate"),
    [
        (TAKE, None),
        (TAKE, _only_vehicle),
        (TAKE, _set(label="Spiti trip", value="Spiti trip", kind="other")),
        (TAKE, _set(label="Spiti", value="Spiti", kind="other")),
        (TAKE, _cite_question_turn),
        (TAKE, _cite_both),
        (TAKE, _vehicle("jimny")),
        ("Jimny.", None),
        ("Let's go with the Jimny for that.", None),
        ("Jimny, final answer.", _set(intent="change")),
    ],
    ids=[
        "recorded-shape",
        "only-the-answered-detail",
        "paraphrased-name",
        "grounded-other-name",
        "cites-only-the-question-turn",
        "cites-both-turns",
        "different-case",
        "one-word",
        "other-wording",
        "change-intent",
    ],
)
async def test_any_reading_of_the_choice_decides_the_questions_plan(lab, text, mutate):  # noqa: F811
    before, question = await _first_turn(lab)
    await _answer(lab, text, _reading(mutate))
    plans = await lab.plans()
    assert len(plans) == 1  # never a second plan
    _assert_decided(before, plans[0])
    assert lab.runtime.clarifications.pending(question.session_id) == []


# answers code cannot check store nothing and leave the question open ---------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mutate"),
    [
        ("We'll take the second one.", None),  # the value is not said now
        (TAKE, _vehicle("Thar")),  # a value the owner did not say
        (TAKE, lambda raw, source: None),  # an answer with no value
        ("Should we take the Jimny?", None),  # a question back
        ("We'll probably take the Jimny.", _vehicle(certainty="tentative")),
        ("Jimny, or maybe the Thar.", "both"),  # contradictory
        (TAKE, _vehicle(options=["Thar", "Jimny"], value="")),  # options again
        # Names the plan with other words of this turn: read as another plan
        # (admitted limitation; the ordinary path then judges it on its own).
        (TAKE, _set(label=TAKE, value=TAKE)),
    ],
    ids=[
        "not-said",
        "other-option",
        "no-value",
        "question",
        "tentative",
        "contradictory",
        "options-again",
        "answer-words-as-name",
    ],
)
async def test_an_unchecked_choice_stores_nothing(lab, learning, text, mutate):  # noqa: F811
    before, question = await _first_turn(lab)
    if mutate == "both":

        def build(source):
            jimny = _reading()(source)[0]
            thar = _reading(_vehicle("Thar"))(source)[0]
            return [jimny, thar]

    else:
        build = _reading(mutate)
    await _answer(lab, text, build)
    (after,) = await lab.plans()
    assert after == before
    assert [state for state, _ in await _rows(learning.reader)] == ["active"]
    assert lab.runtime.clarifications.pending(question.session_id) == [question]


@pytest.mark.asyncio
async def test_a_choice_outside_the_options_is_still_the_owners_decision(lab):  # noqa: F811
    before, _ = await _first_turn(lab)
    text = "Neither, we'll take the Scorpio."
    await _answer(lab, text, _reading(_vehicle("Scorpio")))
    (after,) = await lab.plans()
    assert after["slots"]["vehicle"] == {
        "value": "Scorpio",
        "options": [],
        "certainty": "confirmed",
    }
    assert after["slots"]["when"] == before["slots"]["when"]


@pytest.mark.asyncio
async def test_only_the_answered_detail_is_taken_from_the_answer(lab):  # noqa: F811
    """Admitted limitation: another detail said inside the answer ("stay in
    Kaza") is not learned from that turn, so it can never sink the decision
    or slip a restated earlier detail in with it."""
    before, _ = await _first_turn(lab)
    text = "We'll take the Jimny and stay in Kaza."

    def mutate(raw, source):
        raw["slots"]["stay"] = {
            "value": "Kaza",
            "options": [],
            "certainty": "confirmed",
        }
        raw["slots"]["when"] = {
            "value": "February",
            "options": [],
            "certainty": "confirmed",
        }
        return raw

    await _answer(lab, text, _reading(mutate))
    (after,) = await lab.plans()
    assert after["slots"]["vehicle"] == JIMNY
    assert "stay" not in after["slots"]
    assert after["slots"]["when"] == before["slots"]["when"]


@pytest.mark.asyncio
async def test_a_known_detail_said_differently_does_not_ride_along(lab):  # noqa: F811
    before, _ = await _first_turn(lab)
    text = "We'll take the Jimny in February."

    def mutate(raw, source):
        raw["slots"]["when"] = {
            "value": "February",
            "options": [],
            "certainty": "confirmed",
        }
        return raw

    await _answer(lab, text, _reading(mutate))
    (after,) = await lab.plans()
    # The decision is stored; a changed schedule is not slipped in with it.
    assert after["slots"]["vehicle"] == JIMNY
    assert after["slots"]["when"] == before["slots"]["when"]


@pytest.mark.asyncio
async def test_a_later_change_of_time_is_not_reverted_by_the_answer(lab):  # noqa: F811
    before, _ = await _first_turn(lab)
    moved = "We moved Spiti to February."

    def build(source):
        turn = source.turns[-1]
        at = turn.text.index("February")
        first = source.turns[0]
        return [
            LearningCandidate(
                category="plan",
                kind="other",
                intent="change",
                label=before["label"],
                value=before["value"],
                state="planned",
                plan_status="planned",
                slots={"when": {"value": "February", "certainty": "confirmed"}},
                evidence=[
                    {"turn_id": first.turn_id, "start": 0, "end": len(first.text)},
                    {"turn_id": turn.turn_id, "start": at, "end": at + 8},
                ],
            )
        ]

    lab.script.by_text[moved] = build
    lab.resolver.targets[moved] = before["label"]
    await lab.say(moved)
    (middle,) = await lab.plans()
    assert middle["slots"]["when"]["value"] == "February"
    await _answer(lab, TAKE, _reading())
    (after,) = await lab.plans()
    assert after["slots"]["vehicle"] == JIMNY
    assert after["slots"]["when"]["value"] == "February"


# the other answers, replayed from the same recorded first turn ---------------


@pytest.mark.asyncio
async def test_confirmed_alternatives_are_saved_undecided_from_the_recording(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    yes = "Yes, still deciding between those."
    await _answer(lab, yes, None, answers=[("confirmed", "vehicle")])
    (after,) = await lab.plans()
    assert after["slots"]["vehicle"] == {
        "value": None,
        "options": ["Thar", "Jimny"],
        "certainty": "tentative",
    }
    assert after["slots"]["when"] == before["slots"]["when"]
    assert lab.runtime.clarifications.pending(question.session_id) == []
    # With no question open, a later decision is an ordinary proposal (D10):
    # it must name the plan in the owner's words. The recorded paraphrase
    # alone is not enough (admitted limitation, outside the handoff) ...
    await _answer(lab, TAKE, _reading(), answers=())
    assert (await lab.plans())[0]["slots"]["vehicle"] == after["slots"]["vehicle"]
    # ... a reading that cites the owner's name for it decides the same plan.
    await _answer(
        lab,
        "We'll take the Jimny for Spiti.",
        _reading(
            lambda raw, source: _only_vehicle(
                {**raw, "label": "Spiti", "value": "Spiti", "kind": "other"}, source
            )
        ),
        answers=(),
        target=before["label"],
    )
    (decided,) = await lab.plans()
    assert decided["slots"]["vehicle"] == JIMNY
    assert decided["label"] == before["label"]


@pytest.mark.asyncio
async def test_a_question_back_does_not_confirm(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    ask = "Are we still deciding?"
    await _answer(lab, ask, None, answers=[("confirmed", "vehicle")])
    (after,) = await lab.plans()
    assert after == before
    assert lab.runtime.clarifications.pending(question.session_id) == [question]


@pytest.mark.asyncio
async def test_doesnt_matter_and_unrelated_replies_from_the_recording(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    await lab.say("What's the weather like there in January?")
    assert await lab.plans() == [before]
    assert lab.runtime.clarifications.pending(question.session_id) == [question]
    whatever = "Doesn't matter, either is fine."
    await _answer(lab, whatever, None, answers=[("doesnt_matter", "vehicle")])
    assert await lab.plans() == [before]
    assert lab.runtime.clarifications.pending(question.session_id) == []
    # Nothing left to answer: the recorded choice reading has no question.
    await _answer(lab, TAKE, _reading(), answers=())
    assert lab.script.questions_seen[-1] == []
    assert await lab.plans() == [before]


# missing, expired or invalidated context -------------------------------------


@pytest.mark.asyncio
async def test_an_expired_question_is_not_offered_and_its_answer_stores_nothing(lab):  # noqa: F811
    before, _ = await _first_turn(lab)
    for text in ("Okay.", "Nice weather today.", "Hmm."):
        await lab.say(text)
    # The question's turn has left the learning window (four owner turns).
    await _answer(lab, TAKE, _reading())
    assert lab.script.questions_seen[-1] == []
    assert await lab.plans() == [before]


def test_answer_candidate_needs_the_original_words_in_the_source():
    from types import SimpleNamespace

    from jarvis.memory.learning_clarification import (
        LearningClarification,
        answer_candidate,
    )

    original = LearningCandidate.model_validate(
        {
            **EF0C["steps"]["alt-01"]["extraction"]["candidates"][0],
            "label": EF0C["steps"]["alt-01"]["utterance"],
        }
    )
    note = LearningClarification(
        "s1",
        original.evidence[0].turn_id,
        "plan",
        original.label,
        ("vehicle",),
        ("Thar", "Jimny"),
        kind="confirm_alternatives",
        choices=(("vehicle", ("Thar", "Jimny")),),
        candidate=original,
        plan_predicate="plan_x",
    )
    latest = SimpleNamespace(turn_id="t2", text=TAKE)
    gone = SimpleNamespace(session_id="s1", turn_id="t2", turns=[latest])
    assert answer_candidate(gone, [], [(note, {"vehicle": "Jimny"})]) == (
        None,
        "original_evidence_expired",
    )
    first = SimpleNamespace(
        turn_id=original.evidence[0].turn_id,
        text=EF0C["steps"]["alt-01"]["utterance"],
    )
    held = SimpleNamespace(session_id="s1", turn_id="t2", turns=[first, latest])
    candidate, reason = answer_candidate(held, [], [(note, {"vehicle": "Jimny"})])
    assert reason is None
    assert (candidate.label, candidate.value) == (original.label, original.value)
    assert [s.turn_id for s in candidate.evidence] == [first.turn_id, "t2"]
    assert candidate.time_expression is None and candidate.plan_status is None
    assert candidate.slots.vehicle.value == "Jimny"
    assert candidate.slots.when is None  # nothing restated


@pytest.mark.asyncio
async def test_explicit_memory_changes_clear_open_questions(lab, learning):  # noqa: F811
    _, question = await _first_turn(lab)
    # Explicit remember/correct/forget call the runtime's bound invalidator.
    assert learning.service._learning_invalidator == lab.runtime.invalidate_sources
    learning.service._invalidate_learning()
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_a_cancelled_plan_closes_its_question_and_takes_no_answer(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    cancel = "We cancelled the Spiti trip."

    def build(source):
        first, turn = source.turns[0], source.turns[-1]
        return [
            LearningCandidate(
                category="plan",
                kind="other",
                intent="change",
                label=before["label"],
                value=before["value"],
                state="cancelled",
                plan_status="cancelled",
                evidence=[
                    {"turn_id": first.turn_id, "start": 0, "end": len(first.text)},
                    {"turn_id": turn.turn_id, "start": 0, "end": len(turn.text)},
                ],
            )
        ]

    lab.script.by_text[cancel] = build
    lab.resolver.targets[cancel] = before["label"]
    await lab.say(cancel)
    (cancelled,) = await lab.plans()
    assert cancelled["plan_status"] == "cancelled"
    assert lab.runtime.clarifications.pending(question.session_id) == []
    await _answer(lab, TAKE, _reading())
    (after,) = await lab.plans()
    assert "vehicle" not in after["slots"]


# several details, several plans ----------------------------------------------


@pytest.mark.asyncio
async def test_two_details_of_one_plan_are_answered_as_one_change(lab, learning):  # noqa: F811
    lab.script.by_text[TWO_CHOICES] = _two_choices()
    await lab.say(TWO_CHOICES)
    assert [n.details for n in lab.seen] == [("vehicle",), ("stay",)]
    text = "The Jimny, and still deciding between the hotel and homestay."

    def build(source):
        turn = source.turns[-1]
        return [
            LearningCandidate(
                category="plan",
                kind="other",
                intent="new",
                label="our trip",
                value="our trip",
                slots={"vehicle": {"value": "Jimny", "certainty": "confirmed"}},
                evidence=[{"turn_id": turn.turn_id, "start": 0, "end": 9}],
            )
        ]

    await _answer(
        lab, text, build, answers=[("chosen", "vehicle"), ("confirmed", "stay")]
    )
    (plan,) = await lab.plans()
    assert plan["slots"]["vehicle"] == JIMNY
    assert plan["slots"]["stay"]["options"] == ["hotel", "homestay"]
    assert [s for s, _ in await _rows(learning.reader)] == ["superseded", "active"]
    assert lab.runtime.clarifications.pending(lab.conversation.session_id) == []


GOA = "We're going to Goa in April, scooter or bike."


def _goa():
    return _said(
        GOA,
        "Goa",
        slots={
            "when": {"value": "April", "certainty": "confirmed"},
            "vehicle": {"options": ["scooter", "bike"], "certainty": "tentative"},
        },
    )


@pytest.mark.asyncio
async def test_answers_for_two_plans_go_to_their_own_plans(lab):  # noqa: F811
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    lab.script.by_text[GOA] = _goa()
    await lab.say(GOA)
    assert len(lab.seen) == 2
    text = "Jimny for Spiti and the scooter for Goa."

    def build(source):
        turn = source.turns[-1]
        out = []
        for label, value in (("Spiti", "Jimny"), ("Goa", "scooter")):
            at = turn.text.index(value)
            out.append(
                LearningCandidate(
                    category="plan",
                    kind="vehicle",
                    intent="new",
                    label=f"{label} holiday",
                    value=f"{label} holiday",
                    slots={"vehicle": {"value": value, "certainty": "confirmed"}},
                    evidence=[
                        {"turn_id": turn.turn_id, "start": at, "end": at + len(value)}
                    ],
                )
            )
        return out

    lab.script.by_text[text] = build
    lab.script.answers[text] = [("chosen", "vehicle")]  # both questions
    await lab.say(text)
    plans = {p["label"]: p for p in await lab.plans()}
    assert set(plans) == {"Spiti", "Goa"}
    assert plans["Spiti"]["slots"]["vehicle"]["value"] == "Jimny"
    assert plans["Goa"]["slots"]["vehicle"]["value"] == "scooter"
    assert lab.runtime.clarifications.pending(lab.conversation.session_id) == []


@pytest.mark.asyncio
async def test_one_value_claimed_for_two_plans_decides_neither(lab):  # noqa: F811
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    other = "We're going to Ladakh in May, Thar or Jimny."
    lab.script.by_text[other] = _said(
        other,
        "Ladakh",
        slots={
            "when": {"value": "May", "certainty": "confirmed"},
            "vehicle": {"options": ["Thar", "Jimny"], "certainty": "tentative"},
        },
    )
    await lab.say(other)
    assert len(lab.seen) == 2
    lab.script.answers[TAKE] = [("chosen", "vehicle")]  # both, ambiguously
    await _answer(lab, TAKE, _reading())
    plans = await lab.plans()
    assert all("vehicle" not in p["slots"] for p in plans)
    assert len(lab.runtime.clarifications.pending(lab.conversation.session_id)) == 2


# an unclear-detail question (D9 shape) takes the same handoff ----------------


@pytest.mark.asyncio
async def test_unclear_detail_answer_decides_the_same_plan(lab):  # noqa: F811
    first = LAB6["steps"]["idiom-01"]["utterance"]
    lab.script.by_text[first] = _recorded(LAB6, "idiom-01")
    await lab.say(first)
    (before,) = await lab.plans()
    (question,) = lab.seen
    assert question.kind == "unclear"
    text = "We'll take the Thar."
    await _answer(lab, text, _reading(_vehicle("Thar")))
    (after,) = await lab.plans()
    assert after["slots"]["vehicle"]["value"] == "Thar"
    assert after["label"] == before["label"]
    assert lab.runtime.clarifications.pending(question.session_id) == []


def test_chosen_values_unit_rules():
    from dataclasses import replace
    from types import SimpleNamespace

    from jarvis.memory.learning_clarification import (
        LearningClarification,
        chosen_values,
    )

    original = LearningCandidate.model_validate(
        EF0C["steps"]["alt-01"]["extraction"]["candidates"][0]
    )
    note = LearningClarification(
        "s1",
        "t1",
        "plan",
        "Spiti",
        ("vehicle",),
        ("Thar", "Jimny"),
        kind="confirm_alternatives",
        choices=(("vehicle", ("Thar", "Jimny")),),
        candidate=original,
        plan_predicate="plan_x",
    )
    turn = SimpleNamespace(turn_id="t2", text="We'll take the jimny. Or the Thar?")
    source = SimpleNamespace(session_id="s1", turn_id="t2", turns=[turn])
    reading = LearningCandidate.model_validate(
        {
            **EF0C["steps"]["alt-02"]["extraction"]["candidates"][0],
            "evidence": [{"turn_id": "t2", "start": 0, "end": 5}],
        }
    )
    # The owner's spelling from a statement; "Thar" only in a question.
    assert chosen_values(source, [note], [reading]) == (
        {note.question_id: {"vehicle": "jimny"}},
        [],
    )
    # A question not bound to a stored plan decides nothing.
    unbound = replace(note, plan_predicate=None)
    assert chosen_values(source, [unbound], [reading]) == (
        {},
        [(unbound, "unbound_question")],
    )
    # A word inside another word is not the owner's choice.
    turn.text = "We'll take the Jimnyx."
    assert chosen_values(source, [note], [reading])[1] == [(note, "choice_not_stated")]


# a second plan in the answer turn is learned on its own ----------------------


def _named(turn, label, slots, intent="new"):
    return LearningCandidate(
        category="plan",
        kind="other",
        intent=intent,
        label=label,
        value=label,
        state="planned",
        plan_status="planned",
        slots=slots,
        evidence=[{"turn_id": turn.turn_id, "start": 0, "end": len(turn.text)}],
    )


def _car(value):
    return {"value": value, "options": [], "certainty": "confirmed"}


@pytest.mark.asyncio
async def test_another_plans_details_never_ride_onto_the_questioned_plan(lab):  # noqa: F811
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    goa = "We're going to Goa in April."
    lab.script.by_text[goa] = _said(goa, "Goa")
    await lab.say(goa)
    text = "Jimny for Spiti. For Goa we'll take the Jimny too and stay in Baga."

    def build(source):
        t = source.turns[-1]
        return [
            _named(t, "Spiti", {"vehicle": _car("Jimny")}),
            _named(t, "Goa", {"vehicle": _car("Jimny"), "stay": _car("Baga")}),
        ]

    lab.resolver.targets[text] = "Goa"
    await _answer(lab, text, build)
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans["Spiti"]["slots"]["vehicle"] == JIMNY
    assert "stay" not in plans["Spiti"]["slots"]
    assert plans["Goa"]["slots"]["stay"]["value"] == "Baga"
    assert plans["Goa"]["slots"]["vehicle"]["value"] == "Jimny"


@pytest.mark.asyncio
async def test_a_value_said_about_another_plan_does_not_answer(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    text = "Not sure yet. For Goa we're taking the Creta."

    def build(source):
        return [_named(source.turns[-1], "Goa", {"vehicle": _car("Creta")})]

    await _answer(lab, text, build)
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans[before["label"]] == before
    assert plans["Goa"]["slots"]["vehicle"]["value"] == "Creta"  # learned itself
    assert lab.runtime.clarifications.pending(question.session_id) == [question]


@pytest.mark.asyncio
async def test_a_new_plan_with_another_option_neither_blocks_nor_is_lost(lab):  # noqa: F811
    before, question = await _first_turn(lab)
    text = "We'll take the Jimny. Ladakh in May is with the Thar."

    def build(source):
        t = source.turns[-1]
        return [
            LearningCandidate.model_validate(
                {
                    **EF0C["steps"]["alt-02"]["extraction"]["candidates"][0],
                    "evidence": [{"turn_id": t.turn_id, "start": 0, "end": 21}],
                }
            ),
            _named(t, "Ladakh", {"vehicle": _car("Thar")}),
        ]

    await _answer(lab, text, build)
    plans = {p["label"]: p for p in await lab.plans()}
    _assert_decided(before, plans[before["label"]])
    assert plans["Ladakh"]["slots"]["vehicle"]["value"] == "Thar"
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_an_answer_too_large_to_cite_stores_nothing_and_breaks_nothing(lab):  # noqa: F811
    from dataclasses import replace

    before, question = await _first_turn(lab)
    # A question whose proposal cites eight spans: with the answer turn the
    # answer would need nine, more than a proposal may carry.
    first = lab.conversation.turns[0]
    spans = [{"turn_id": first.turn_id, "start": i, "end": i + 5} for i in range(8)]
    wide = question.candidate.model_copy(
        update={
            "evidence": [type(question.candidate.evidence[0])(**span) for span in spans]
        }
    )
    board = lab.runtime.clarifications
    board.close(question)
    board.offer(replace(question, candidate=wide))
    other = "We're going to Goa in April."
    text = TAKE + " " + other

    def build(source):
        return _reading()(source) + _said(text, "Goa", quote=other)(source)

    await _answer(lab, text, build)
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans[before["label"]] == before
    assert "Goa" in plans  # the rest of the turn is still learned


@pytest.mark.asyncio
@pytest.mark.parametrize("resolver", ["new", "match"])
async def test_an_alias_of_the_plan_still_answers_and_never_makes_a_second_plan(
    lab,  # noqa: F811
    resolver,
):
    before, question = await _first_turn(lab)
    text = "We'll take the Jimny for the Spiti trip."

    def build(source):
        return [_named(source.turns[-1], "Spiti trip", {"vehicle": _car("Jimny")})]

    await _answer(
        lab, text, build, target=before["label"] if resolver == "match" else None
    )
    (after,) = await lab.plans()
    _assert_decided(before, after)
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Not sure yet. We're going to Goa in the Creta."])
@pytest.mark.parametrize("label", ["Goa trip", "goa"])
async def test_a_paraphrase_with_another_destination_does_not_answer(
    lab,  # noqa: F811
    text,
    label,
):
    before, question = await _first_turn(lab)

    def build(source):
        return [
            _named(
                source.turns[-1],
                label,
                {"vehicle": _car("Creta"), "destination": _car("Goa")},
            )
        ]

    await _answer(lab, text, build)
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans[before["label"]] == before
    assert lab.runtime.clarifications.pending(question.session_id) == [question]


OFFICE = "The office trip is next month, train or flight."


def _office():
    return _said(
        OFFICE,
        "office trip",
        slots={"other": {"options": ["train", "flight"], "certainty": "tentative"}},
    )


@pytest.mark.asyncio
async def test_a_shared_head_noun_does_not_make_another_trip_the_answer(lab):  # noqa: F811
    lab.script.by_text[OFFICE] = _office()
    await lab.say(OFFICE)
    (question,) = lab.seen
    text = "Not sure yet. The family trip will take the train."

    def build(source):
        return [_named(source.turns[-1], "family trip", {"other": _car("train")})]

    await _answer(lab, text, build, answers=[("chosen", "other")])
    plans = {p["label"]: p for p in await lab.plans()}
    assert "other" not in plans["office trip"].get("slots", {})
    assert plans["family trip"]["slots"]["other"]["value"] == "train"
    assert lab.runtime.clarifications.pending(question.session_id) == [question]


@pytest.mark.asyncio
async def test_each_trip_keeps_its_own_choice(lab):  # noqa: F811
    lab.script.by_text[OFFICE] = _office()
    await lab.say(OFFICE)
    text = "We'll take the flight for the office trip, and the family trip will take the train."

    def build(source):
        t = source.turns[-1]
        return [
            _named(t, "office trip", {"other": _car("flight")}),
            _named(t, "family trip", {"other": _car("train")}),
        ]

    await _answer(lab, text, build, answers=[("chosen", "other")])
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans["office trip"]["slots"]["other"]["value"] == "flight"
    assert plans["family trip"]["slots"]["other"]["value"] == "train"
    assert lab.runtime.clarifications.pending(lab.conversation.session_id) == []
