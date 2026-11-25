"""The same memory rules across categories, subjects and wording (offline).

Each case is a fixed proposal of the kind the extraction model returns; the
code under test is the deterministic part: policy (evidence, qualification,
uncertainty, questions) and reconciliation (create, change, correct, history).
These tests say nothing about whether the model interprets a sentence
correctly - that is model behaviour and needs a live evaluation.

Every rule here holds for every category. The six cases that were found
applied only to some categories (a possibility stored as a plain fact
outside the history categories; a question gated only for plans) are now
regressions below.
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


# Formerly known gaps, now the same rule in every category -------------------


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


# possibilities ----------------------------------------------------------------


@pytest.mark.parametrize(
    "category,text,label,fields,stored",
    [
        (
            "routine",
            "I might start swimming at 6.",
            "swimming",
            {"value": "at 6"},
            True,
        ),
        ("goal", "Maybe my goal is a half marathon.", "a half marathon", {}, True),
        (
            "event",
            "I might have been to Pondicherry.",
            "Pondicherry",
            {"state": "completed"},
            True,
        ),
        (
            "owned_item",
            "Maybe I'll get a Kindle.",
            "Kindle",
            {"kind": "device", "state": "owned"},
            False,
        ),
        (
            "owned_item",
            "I might sell my Kindle.",
            "Kindle",
            {"kind": "device", "state": "sold", "intent": "change"},
            False,
        ),
        (
            "food_preference",
            "I'm thinking of going vegetarian.",
            "vegetarian",
            {"scalar_facet": "diet_preference"},
            False,
        ),
    ],
)
def test_a_possibility_is_kept_as_one_or_not_saved_never_a_fact(
    category, text, label, fields, stored
):
    reason, value = _outcome(
        *_proposal(text, category, label, certainty="tentative", **fields)
    )
    if stored:
        assert value["certainty"] == "tentative", (category, value)
    else:
        assert value is None and reason == "possibility_not_fact", (category, reason)


@pytest.mark.parametrize(
    "category,text,label,fields,stored_as",
    [
        (
            "routine",
            "I might move my swimming to 7.",
            "swimming",
            {"value": "to 7"},
            "routine",
        ),
        (
            "personal_fact",
            "I might work as a nurse at Apollo.",
            "nurse at Apollo",
            {},
            "personal_fact",
        ),
        (
            "plan",
            "Maybe we'll cancel the Jaipur trip.",
            "Jaipur",
            {"state": "cancelled", "plan_status": "cancelled"},
            "plan",
        ),
    ],
)
def test_a_possibility_never_changes_or_corrects_a_stored_fact(
    category, text, label, fields, stored_as
):
    entry = _stored(stored_as, "x1")
    for intent in ("change", "correction"):
        reason, value = _outcome(
            *_proposal(
                text, category, label, certainty="tentative", intent=intent, **fields
            ),
            [entry],
            "match",
            "x1",
        )
        assert value is None and reason == ["possibility_cannot_change_fact"], (
            category,
            intent,
            reason,
        )


def test_a_possibility_may_update_a_stored_possibility_and_a_fact_settles_it():
    source, maybe = _proposal(
        "I might start swimming at 6.",
        "routine",
        "swimming",
        value="at 6",
        certainty="tentative",
    )
    _action, value = _outcome(source, maybe)
    entry = LearningCatalogEntry(
        assertion_id="r1",
        predicate="routine_r1",
        category="routine",
        text="routine: swimming",
        value=json.dumps(value),
        kind="other",
    )
    action, still = _outcome(
        *_proposal(
            "Maybe swimming at 7 instead.",
            "routine",
            "swimming",
            value="at 7",
            certainty="tentative",
            intent="change",
        ),
        [entry],
        "match",
        "r1",
    )
    assert action == "change" and still["certainty"] == "tentative"
    action, fact = _outcome(
        *_proposal(
            "My swimming is at 7 now.",
            "routine",
            "swimming",
            value="at 7",
            intent="change",
        ),
        [entry],
        "match",
        "r1",
    )
    assert action == "change" and "certainty" not in fact  # confirmed


def test_a_confirmed_routine_keeps_the_stored_shape_of_earlier_rows():
    # Rows stored before this rule have no certainty key: a confirmed
    # routine or goal still stores none, so nothing churns.
    for category in ("routine", "goal"):
        text, label, fields = FACTS[category]
        _action, value = _outcome(*_proposal(text, category, label, **dict(fields)))
        assert "certainty" not in value


# mixed turns and sensitive data -------------------------------------------------


def _mixed(text, *proposals):
    source = _source(text, "2026-11-20")
    out = []
    for category, quote, label, fields in proposals:
        start = text.index(quote)
        fields = dict(fields)
        out.append(
            LearningCandidate(
                category=category,
                intent=fields.pop("intent", "new"),
                label=label,
                value=fields.pop("value", label),
                evidence=[
                    {
                        "turn_id": source.turn_id,
                        "start": start,
                        "end": start + len(quote),
                    }
                ],
                **fields,
            )
        )
    return source, out


@pytest.mark.parametrize(
    "text,assertion,question",
    [
        (
            "I sold my Pulsar last week. Should I buy a Kindle?",
            (
                "owned_item",
                "I sold my Pulsar last week",
                "Pulsar",
                {
                    "kind": "vehicle",
                    "state": "sold",
                    "disposed_expression": "last week",
                },
            ),
            (
                "owned_item",
                "Should I buy a Kindle",
                "Kindle",
                {"kind": "device", "state": "owned"},
            ),
        ),
        (
            "We're going to Jaipur in March. Which hotel should we book?",
            (
                "plan",
                "We're going to Jaipur in March",
                "Jaipur",
                {"state": "planned", "plan_status": "planned"},
            ),
            (
                "plan",
                "Which hotel should we book",
                "hotel",
                {"state": "planned", "plan_status": "planned"},
            ),
        ),
        (
            "Should I start swimming at 6? I already run every evening.",
            (
                "routine",
                "I already run every evening",
                "run",
                {"value": "every evening"},
            ),
            ("routine", "Should I start swimming at 6", "swimming", {"value": "at 6"}),
        ),
    ],
)
def test_a_mixed_turn_keeps_the_assertion_and_drops_the_question(
    text, assertion, question
):
    source, (kept, asked) = _mixed(text, assertion, question)
    assert LearningPolicy().evaluate(source, kept).status == "eligible"
    verdict = LearningPolicy().evaluate(source, asked)
    assert (verdict.status, verdict.reason) == ("drop", "question_not_disclosure")


@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        ("personal_fact", "My medication is taken every night.", "medication", {}),
        ("personal_fact", "I was diagnosed with asthma.", "diagnosed with asthma", {}),
        ("personal_fact", "My salary is fifty thousand.", "salary", {}),
        (
            "routine",
            "I check my bank balance every Monday.",
            "bank balance",
            {"value": "every Monday"},
        ),
    ],
)
def test_data_classes_outside_automatic_admission_are_never_stored(
    category, text, label, fields
):
    reason, value = _outcome(*_proposal(text, category, label, **fields))
    assert value is None and reason == "sensitive_content"


def test_sensitive_words_elsewhere_in_the_turn_do_not_block_a_standard_fact():
    text = "I have a Kindle Paperwhite. My medication is in the drawer."
    source, (kindle,) = _mixed(
        text,
        (
            "owned_item",
            "I have a Kindle Paperwhite",
            "Kindle Paperwhite",
            {"kind": "device", "state": "owned"},
        ),
    )
    assert LearningPolicy().evaluate(source, kindle).status == "eligible"


def test_a_model_labelled_private_fact_is_never_stored():
    reason, value = _outcome(
        *_proposal(
            "I'm allergic to peanuts.",
            "personal_fact",
            "allergic to peanuts",
            sensitivity="private",
        )
    )
    assert value is None and reason == "not_direct_standard"


def test_known_limit_an_allergy_labelled_standard_is_judged_by_the_model():
    # The existing policy excludes medical data. Its deterministic backstop is
    # the shared list of data classes ("medical", "health", "medication",
    # "diagnosis", ...). An allergy stated without those words, and labelled
    # standard by the model, is still admitted: no new word list was added.
    _action, value = _outcome(
        *_proposal("I'm allergic to peanuts.", "personal_fact", "allergic to peanuts")
    )
    assert value is not None
