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


# -- Run 5 D10: the recorded outputs, unmodified ---------------------------------
#
# Run 5 (lab 7a0a29e2) stored story-07 with label "trip" (the model's name; it
# is in the owner's words) and value "Ladakh or winter Spiti trip". story-10
# was proposed as label "winter Spiti" and matched by the resolver to that
# plan. The run-4 fix lived inside the refine route, which first requires the
# new label to name the stored plan ("winter Spiti" is not contained in
# "trip"), so it was never reached and the turn fell through to
# new_fact_cannot_mutate_target.

from pathlib import Path

from jarvis.memory.learning_catalog_page import unique_reference
from jarvis.memory.learning_contracts import (
    LearningResolutionBatch as _RB,
)

RUN5 = json.loads(
    (Path(__file__).parent / "fixtures" / "run5_d10_recorded.json").read_text(
        encoding="utf-8"
    )
)
RUN5_TARGET = RUN5["steps"]["story-10"]["resolution"]["resolutions"][0]["target_id"]


def _replayed(step, text=None, **changes):
    """The recorded proposal for ``step``. Only the evidence turn id is rebound
    to the replay conversation's turn (an identifier of the lab conversation,
    not model content); ``changes`` exist only for negative cases."""
    source = _source(text or RUN5["owner_said"][step])
    (raw,) = RUN5["steps"][step]["extraction"]["candidates"]
    raw = {**json.loads(json.dumps(raw)), **changes}
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    return source, LearningCandidate.model_validate(raw)


def _run5_entry(assertion_id=RUN5_TARGET, step="story-07", **changes):
    source, candidate = _replayed(step, **changes)
    reconciler = LearningReconciler(None, None)
    plan = reconciler.plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        _RB.model_validate(RUN5["steps"]["story-07"]["resolution"]),
    )
    (mutation,) = plan.mutations
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=mutation.predicate,
        category="plan",
        text=mutation.draft.normalized_text,
        value=json.dumps(mutation.draft.value, ensure_ascii=False),
        kind="other",
    )


def _run5_story_10(entries, resolution=None, text=None, **changes):
    source, candidate = _replayed("story-10", text, **changes)
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        _RB.model_validate(resolution or RUN5["steps"]["story-10"]["resolution"]),
    )


def test_run5_recorded_proposals_are_eligible_as_recorded():
    for step in ("story-07", "story-10"):
        source, candidate = _replayed(step)
        assert ground_plan_label(source, candidate) is candidate  # labels said
        assert LearningPolicy().evaluate(source, candidate).status == "eligible"


def test_run5_why_the_run4_fix_was_not_reached():
    entry = _run5_entry()
    assert json.loads(entry.value)["label"] == "trip"
    # The refine route needs the new label to name the stored plan.
    assert not unique_reference(entry, "winter Spiti", [entry])


def test_run5_d10_recorded_decision_changes_the_matched_plan():
    entry = _run5_entry()
    old = json.loads(entry.value)
    plan = _run5_story_10([entry])
    assert plan.outcomes == ()  # run 5: new_fact_cannot_mutate_target
    (mutation,) = plan.mutations
    assert mutation.action == "change"
    assert (mutation.predicate, mutation.expected_assertion_id) == (
        entry.predicate,
        RUN5_TARGET,
    )
    assert mutation.effective_at is None
    value = mutation.draft.value
    assert value["slots"]["destination"] == {
        "value": "winter Spiti",
        "options": [],
        "certainty": "confirmed",
    }
    assert value["slots"]["vehicle"]["value"] == "Jimny"
    assert value["slots"]["when"] == old["slots"]["when"]  # January kept
    assert old["slots"]["destination"]["options"] == ["Ladakh", "winter Spiti"]


def test_run5_route_refuses_when_another_plan_offers_the_same_option():
    entry = _run5_entry()
    other = _run5_entry(assertion_id="another-plan")
    plan = _run5_story_10([entry, other])
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]


def _slots_with(**destination):
    (raw,) = RUN5["steps"]["story-10"]["extraction"]["candidates"]
    slots = json.loads(json.dumps(raw["slots"]))
    slots["destination"].update(destination)
    return slots


def test_run5_route_refuses_a_tentative_choice_or_a_plan_only_considered():
    entry = _run5_entry()
    tentative = _run5_story_10([entry], slots=_slots_with(certainty="tentative"))
    considered = _run5_story_10([entry], plan_status="considering")
    for plan in (tentative, considered):
        assert plan.mutations == ()
        assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]


def test_run5_route_refuses_a_value_that_was_never_an_option():
    entry = _run5_entry()
    text = "We're going with Kerala, and we'll take the Jimny."
    plan = _run5_story_10(
        [entry],
        text=text,
        label="Kerala",
        value=text,
        slots=_slots_with(value="Kerala"),
        evidence=[{"turn_id": "replaced", "start": 0, "end": len(text)}],
    )
    assert plan.mutations == ()


def test_run5_route_refuses_a_matched_plan_without_that_option():
    # The resolver points at a stored plan that never offered "winter Spiti".
    entry = _run5_entry()
    value = json.loads(entry.value)
    value["slots"]["destination"] = {
        "value": "Goa",
        "options": [],
        "certainty": "confirmed",
    }
    goa = entry.model_copy(update={"value": json.dumps(value)})
    plan = _run5_story_10([goa])
    assert plan.mutations == ()


def test_run5_route_never_applies_to_an_unknown_target_or_a_new_decision():
    entry = _run5_entry()
    unknown = _run5_story_10(
        [entry],
        resolution={
            "resolutions": [
                {"candidate_index": 0, "decision": "match", "target_id": "missing"}
            ]
        },
    )
    assert unknown.mutations == ()
    assert [o.reason for o in unknown.outcomes] == [
        "target_missing_or_category_mismatch"
    ]
    new = _run5_story_10(
        [entry],
        resolution={"resolutions": [{"candidate_index": 0, "decision": "new"}]},
    )
    assert all(m.action == "create" for m in new.mutations)


def test_run5_invented_or_questioned_decisions_never_reach_reconciliation():
    # A decision the owner did not say is refused by the grounding gate.
    source, invented = _replayed("story-10", slots=_slots_with(value="Ladakh"))
    assert LearningPolicy().evaluate(source, invented).reason == "unsupported_detail"
    # A question is not a decision.
    question = "Should we go with winter Spiti, and take the Jimny?"
    source, asked = _replayed(
        "story-10",
        question,
        value=question,
        evidence=[{"turn_id": "replaced", "start": 0, "end": len(question)}],
    )
    assert LearningPolicy().evaluate(source, asked).status == "drop"
