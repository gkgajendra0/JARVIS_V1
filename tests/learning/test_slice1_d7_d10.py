"""Run 4 (lab 67967242) D7 and D10, reproduced from the recorded model outputs.

D7: "Maybe we'll do Goa this winter." was proposed as plan label "Goa trip",
value "Goa". "Goa trip" is not in the owner's words, so the label gate dropped
the whole plan (no eligible fact). Fix: a plan whose value is grounded uses the
value as its label.

D10: "We're going with winter Spiti, and we'll take the Jimny." was proposed
as intent new and matched to the stored "Ladakh or winter Spiti trip". Refine
saw the destination slot disagree (stored options, new value) and skipped it as
refine_conflicts_existing_detail. Fix: choosing one of the owner's stated
alternatives is a change of the same plan; the earlier row keeps the options.
"""

import json

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy, ground_plan_label
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_values import decides_stated_options

STORY_07 = "I'm planning a Ladakh or winter Spiti trip in January."
STORY_08 = "Maybe we'll do Goa this winter."
STORY_10 = "We're going with winter Spiti, and we'll take the Jimny."


def _source(text):
    c = ConversationSession()
    c.start()
    turn = c.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", c, turn, now=100)


def _slot(value=None, options=()):
    return {"value": value, "options": list(options), "certainty": "confirmed"}


def _recorded(source, **fields):
    """A plan proposal shaped exactly as run 4 recorded it."""
    base = {
        "category": "plan",
        "kind": "other",
        "intent": "new",
        "qualification": "direct",
        "importance": "transient",
        "sensitivity": "standard",
        "state": "planned",
        "certainty": "confirmed",
        "time_expression": None,
        "location": None,
        "reason": None,
        "scalar_facet": None,
        "confidence": 1.0,
        "aliases": [],
        "details": None,
        "acquired_expression": None,
        "disposed_expression": None,
        "plan_status": "planned",
    }
    slots = {
        "destination": None,
        "when": None,
        "vehicle": None,
        "stay": None,
        "companions": None,
        "other": None,
        **fields.pop("slots", {}),
    }
    return LearningCandidate(
        **{**base, **fields},
        slots=slots,
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(source.text))],
    )


def story_07(source):
    return _recorded(
        source,
        label="Ladakh or winter Spiti trip",
        value="Ladakh or winter Spiti trip",
        time_expression="January",
        slots={
            "destination": _slot(options=("Ladakh", "winter Spiti")),
            "when": _slot("January"),
        },
    )


def story_08(source):
    return _recorded(
        source,
        label="Goa trip",
        value="Goa",
        certainty="tentative",
        confidence=0.95,
        time_expression="this winter",
        location="Goa",
        plan_status="considering",
        slots={"destination": _slot("Goa"), "when": _slot("this winter")},
    )


def story_10(source, destination="winter Spiti"):
    return _recorded(
        source,
        label=destination,
        value=destination,
        slots={"destination": _slot(destination), "vehicle": _slot("Jimny")},
    )


# -- D7 ------------------------------------------------------------------------


def test_d7_reproduction_recorded_goa_label_was_dropped():
    source = _source(STORY_08)
    candidate = story_08(source)
    decision = LearningPolicy().evaluate(source, candidate)
    assert (decision.status, decision.reason) == ("drop", "unsupported_label")


def test_d7_grounded_plan_value_becomes_the_label_and_is_eligible():
    source = _source(STORY_08)
    grounded = ground_plan_label(source, story_08(source))
    assert grounded.label == "Goa" and grounded.value == "Goa"
    assert grounded.plan_status == "considering"
    assert grounded.certainty == "tentative"
    assert LearningPolicy().evaluate(source, grounded).status == "eligible"


def test_label_grounding_never_applies_outside_plans_or_to_unsaid_values():
    source = _source("I bought a Hero Xoom scooter.")
    item = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="new",
        label="Hero Xoom 110",
        value="Hero Xoom",
        state="owned",
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=29)],
    )
    assert ground_plan_label(source, item) is item
    assert LearningPolicy().evaluate(source, item).reason == "unsupported_label"

    plan_source = _source(STORY_08)
    unsaid = story_08(plan_source).model_copy(
        update={"label": "Goa trip", "value": "Goa beach holiday"}
    )
    assert ground_plan_label(plan_source, unsaid) is unsaid
    assert LearningPolicy().evaluate(plan_source, unsaid).status == "drop"


def test_a_grounded_label_is_left_unchanged():
    source = _source(STORY_07)
    candidate = story_07(source)
    assert ground_plan_label(source, candidate) is candidate


def test_label_grounding_does_not_weaken_the_question_gate():
    source = _source("Should we do Goa this winter?")
    candidate = story_08(source).model_copy(
        update={
            "evidence": [
                EvidenceSpan(turn_id=source.turn_id, start=0, end=len(source.text))
            ]
        }
    )
    grounded = ground_plan_label(source, candidate)
    assert LearningPolicy().evaluate(source, grounded).status == "drop"


# -- D10 -----------------------------------------------------------------------


def test_decision_among_stated_options_is_recognized_narrowly():
    old = {"slots": {"destination": _slot(options=("Ladakh", "winter Spiti"))}}
    assert decides_stated_options(
        old, {"slots": {"destination": _slot("Winter  Spiti")}}
    )
    assert decides_stated_options(
        old,
        {"slots": {"destination": _slot("winter Spiti"), "vehicle": _slot("Jimny")}},
    )
    # A value that was never one of the options is not a decision.
    assert not decides_stated_options(old, {"slots": {"destination": _slot("Kerala")}})
    # A slot that already had a value is not reopened here.
    decided = {"slots": {"destination": _slot("Ladakh")}}
    assert not decides_stated_options(
        decided, {"slots": {"destination": _slot("winter Spiti")}}
    )
    # Nothing decided: not a change.
    assert not decides_stated_options(old, {"slots": {"vehicle": _slot("Jimny")}})
    assert not decides_stated_options(old, {})
    # Another disagreement alongside the decision keeps its own handling.
    with_details = {**old, "details": "with friends"}
    assert not decides_stated_options(
        with_details,
        {"details": "solo", "slots": {"destination": _slot("winter Spiti")}},
    )


def _stored_story_07():
    reconciler = LearningReconciler(None, None)
    source = _source(STORY_07)
    batch = LearningBatch(candidates=[story_07(source)])
    plan = reconciler.plan(
        source,
        batch,
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        ),
    )
    (mutation,) = plan.mutations
    value = mutation.draft.value
    entry = LearningCatalogEntry(
        assertion_id="plan-ladakh-spiti",
        predicate=mutation.predicate,
        category="plan",
        text=mutation.draft.normalized_text,
        value=json.dumps(value, ensure_ascii=False),
        kind="other",
    )
    return reconciler, entry, value


def _plan_story_10(destination="winter Spiti"):
    reconciler, entry, old = _stored_story_07()
    source = _source(
        STORY_10
        if destination == "winter Spiti"
        else f"We're going with {destination}, and we'll take the Jimny."
    )
    candidate = story_10(source, destination)
    plan = reconciler.plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=[entry]),
        LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0, decision="match", target_id=entry.assertion_id
                )
            ]
        ),
    )
    return plan, entry, old


def test_d10_reproduction_decision_changes_the_same_plan():
    plan, entry, old = _plan_story_10()
    assert plan.outcomes == ()  # previously: refine_conflicts_existing_detail
    (mutation,) = plan.mutations
    assert mutation.action == "change"
    assert (mutation.predicate, mutation.expected_assertion_id) == (
        entry.predicate,
        entry.assertion_id,
    )
    assert mutation.effective_at is None  # when it was decided is not stated
    value = mutation.draft.value
    assert value["slots"]["destination"]["value"] == "winter Spiti"
    assert value["slots"]["destination"]["options"] == []
    assert value["slots"]["vehicle"]["value"] == "Jimny"
    assert value["slots"]["when"] == old["slots"]["when"]  # kept from the plan
    assert value["plan_status"] == "planned"
    # The superseded row (history) still holds the stated options.
    assert old["slots"]["destination"]["options"] == ["Ladakh", "winter Spiti"]


def test_a_destination_that_was_never_an_option_is_not_changed():
    # Existing handling is unchanged: nothing written, a reason recorded.
    plan, _, _ = _plan_story_10("Kerala")
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]
