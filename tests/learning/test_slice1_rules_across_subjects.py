"""The same memory rules across categories, subjects and wording (offline).

Each case is a fixed proposal of the kind the extraction model returns; the
code under test is the deterministic part: policy (evidence, qualification,
uncertainty, questions) and reconciliation (create, change, correct, history).
These tests say nothing about whether the model interprets a sentence
correctly - that is model behaviour and needs a live evaluation.

Rules that hold for every category pass here. Two rules that the code applies
only to some categories are pinned as strict xfails (known gaps, not fixed):
a possibility is stored as a fact outside the history categories, and a
question is gated only for plans.
"""

from __future__ import annotations

import json

import pytest
from test_slice1_d12_d16 import _source

from jarvis.memory.learning_contracts import (
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler

# One ordinary statement per category, none of them used by any other test.
FACTS = {
    "personal_fact": (
        "I work as a nurse at City Hospital.",
        "nurse at City Hospital",
        {},
    ),
    "routine": (
        "I go swimming every morning at 6.",
        "swimming",
        {"value": "every morning at 6"},
    ),
    "goal": ("My goal is to run a half marathon.", "run a half marathon", {}),
    "food_preference": (
        "I'm vegetarian.",
        "vegetarian",
        {"scalar_facet": "diet_preference"},
    ),
    "activity": ("I'm learning the guitar these days.", "learning the guitar", {}),
    "event": (
        "Last weekend I went to Pondicherry.",
        "Pondicherry",
        {"state": "completed", "time_expression": "Last weekend"},
    ),
    "owned_item": (
        "I have a Kindle Paperwhite.",
        "Kindle Paperwhite",
        {"kind": "device", "state": "owned"},
    ),
    "plan": (
        "We're visiting Jaipur in March.",
        "Jaipur",
        {"state": "planned", "plan_status": "planned"},
    ),
}
HISTORY = {"personal_fact", "activity", "event", "plan"}


def _proposal(text, category, label, **fields):
    source = _source(text, "2026-11-20")
    values = {
        "category": category,
        "intent": "new",
        "label": label,
        "value": fields.pop("value", label),
        "evidence": [{"turn_id": source.turn_id, "start": 0, "end": len(text)}],
        **fields,
    }
    return source, LearningCandidate(**values)


def _outcome(source, candidate, entries=(), decision="new", target=None):
    verdict = LearningPolicy().evaluate(source, candidate)
    if verdict.status != "eligible":
        return verdict.reason, None
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0, decision=decision, target_id=target
                )
            ]
        ),
    )
    if not plan.mutations:
        return [o.reason for o in plan.outcomes], None
    (mutation,) = plan.mutations
    return mutation.action, mutation.draft.value


def _stored(category, aid):
    text, label, fields = FACTS[category]
    action, value = _outcome(*_proposal(text, category, label, **dict(fields)))
    assert action == "create", (category, action)
    return LearningCatalogEntry(
        assertion_id=aid,
        predicate=f"{category}_{aid}",
        category=category,
        text=f"{category}: {label}",
        value=json.dumps(value),
        kind=fields.get("kind", "other"),
    )


@pytest.mark.parametrize("category", sorted(FACTS))
def test_a_direct_statement_is_stored_in_every_category(category):
    text, label, fields = FACTS[category]
    action, _value = _outcome(*_proposal(text, category, label, **dict(fields)))
    assert action == "create"


@pytest.mark.parametrize("category", sorted(FACTS))
def test_unsaid_words_are_refused_in_every_category(category):
    text, _label, fields = FACTS[category]
    fields = dict(fields)
    fields.pop("value", None)
    reason, _ = _outcome(*_proposal(text, category, "Zanzibar", **fields))
    assert reason in {"unsupported_value", "unsupported_label"}


@pytest.mark.parametrize("category", sorted(FACTS))
def test_meaning_marked_uncertain_is_never_stored_in_any_category(category):
    text, label, fields = FACTS[category]
    reason, _ = _outcome(
        *_proposal(text, category, label, certainty="uncertain", **dict(fields))
    )
    assert reason == "meaning_unclear"


@pytest.mark.parametrize("qualification", ["hypothetical", "quoted"])
@pytest.mark.parametrize("category", sorted(FACTS))
def test_hypothetical_or_quoted_is_never_stored_in_any_category(
    category, qualification
):
    text, label, fields = FACTS[category]
    reason, _ = _outcome(
        *_proposal(text, category, label, qualification=qualification, **dict(fields))
    )
    assert reason == "not_direct_standard"


@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        ("routine", "My swimming is now at 7.", "swimming", {"value": "at 7"}),
        ("personal_fact", "I now work as a nurse at Apollo.", "nurse at Apollo", {}),
        (
            "owned_item",
            "I sold my Kindle Paperwhite.",
            "Kindle Paperwhite",
            {"kind": "device", "state": "sold"},
        ),
        ("activity", "I'm learning the violin these days.", "learning the violin", {}),
    ],
)
def test_a_real_world_change_updates_the_same_record_in_any_category(
    category, text, label, fields
):
    entry = _stored(category, "x1")
    action, _value = _outcome(
        *_proposal(text, category, label, intent="change", **fields),
        [entry],
        "match",
        "x1",
    )
    assert action == "change", (category, action)


@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        ("routine", "Sorry, swimming is at 7, not 6.", "swimming", {"value": "at 7"}),
        ("goal", "I meant a full marathon.", "a full marathon", {}),
        (
            "event",
            "Actually it was Puducherry last month, not last weekend.",
            "Puducherry",
            {"state": "completed", "time_expression": "last month"},
        ),
        ("personal_fact", "Correction: I'm a nurse at Apollo.", "nurse at Apollo", {}),
    ],
)
def test_a_correction_replaces_the_same_record_in_any_category(
    category, text, label, fields
):
    entry = _stored(category, "x1")
    action, _ = _outcome(
        *_proposal(text, category, label, intent="correction", **fields),
        [entry],
        "match",
        "x1",
    )
    assert action == "correct", (category, action)


@pytest.mark.parametrize("category", sorted(FACTS))
def test_a_change_never_creates_a_second_record_when_unmatched(category):
    text, label, fields = FACTS[category]
    reason, value = _outcome(
        *_proposal(text, category, label, intent="change", **dict(fields))
    )
    assert value is None and reason  # recorded, nothing written


@pytest.mark.parametrize("category", sorted(HISTORY))
def test_a_possibility_is_stored_as_tentative_in_history_categories(category):
    text, label, fields = FACTS[category]
    fields = dict(fields)
    if category == "plan":
        fields["plan_status"] = "considering"
    action, value = _outcome(
        *_proposal(text, category, label, certainty="tentative", **fields)
    )
    assert action == "create" and value["certainty"] == "tentative"


# Known gaps: rules applied only to some categories --------------------------


@pytest.mark.xfail(
    strict=True,
    reason="gap: certainty is stored only for history categories; a possibility"
    " in another category is stored as a plain fact",
)
@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        ("routine", "I might start swimming at 6.", "swimming", {"value": "at 6"}),
        ("goal", "My goal might be a half marathon.", "a half marathon", {}),
        (
            "owned_item",
            "Maybe I'll get a Kindle.",
            "Kindle",
            {"kind": "device", "state": "owned"},
        ),
    ],
)
def test_gap_a_possibility_outside_history_categories_stays_a_possibility(
    category, text, label, fields
):
    _action, value = _outcome(
        *_proposal(text, category, label, certainty="tentative", **fields)
    )
    assert value is None or value.get("certainty") == "tentative"


@pytest.mark.xfail(
    strict=True,
    reason="gap: the question gate applies to plans only; a question proposed"
    " as another category's fact is stored",
)
@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        (
            "owned_item",
            "Should I buy a Kindle?",
            "Kindle",
            {"kind": "device", "state": "owned"},
        ),
        ("routine", "Should I start swimming at 6?", "swimming", {"value": "at 6"}),
        ("goal", "Should my goal be a half marathon?", "a half marathon", {}),
    ],
)
def test_gap_a_question_is_never_stored_as_a_fact_in_any_category(
    category, text, label, fields
):
    _reason, value = _outcome(*_proposal(text, category, label, **fields))
    assert value is None


def test_the_question_gate_holds_for_plans():
    reason, value = _outcome(
        *_proposal(
            "Should we visit Jaipur in March?",
            "plan",
            "Jaipur",
            state="planned",
            plan_status="planned",
        )
    )
    assert reason == "question_not_disclosure" and value is None
