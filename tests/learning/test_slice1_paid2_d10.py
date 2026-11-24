"""Paid lab (05f059d1, slice1-acceptance-paid-2) D10, replayed from the
recorded outputs (fixtures/paid2_d10_recorded.json, unmodified).

story-10 "We're going with winter Spiti, and we'll take the Jimny." was
proposed as intent new, plan kind "vehicle"; the resolver matched the stored
"Ladakh or winter Spiti trip" plan (kind "other"). The run-5 option-decision
route required the proposal's kind to equal the stored plan's, so the
decision fell through to new_fact_cannot_mutate_target. A plan's kind does
not identify it; the decision route now ignores it and the change keeps the
stored plan's kind. Nothing else about the route is relaxed.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_slice1_d12_d16 import _source

from jarvis.memory.learning_contracts import (
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy, ground_plan_label
from jarvis.memory.learning_reconciliation import LearningReconciler

PAID2 = json.loads(
    (Path(__file__).parent / "fixtures" / "paid2_d10_recorded.json").read_text(
        encoding="utf-8"
    )
)
S = PAID2["steps"]
SPITI = S["story-10"]["resolution"]["resolutions"][0]["target_id"]
STORED = (("story-01", "plan-rishikesh"), ("story-07", SPITI), ("story-08", "plan-goa"))


def _replay(step, text=None, **changes):
    """The recorded proposal; only the evidence turn id is rebound to the
    replay turn. ``changes`` exist only for negative cases."""
    st = S[step]
    source = _source(text or st["utterance"], st["told_at"][:10])
    (raw,) = st["extraction"]["candidates"]
    raw = {**json.loads(json.dumps(raw)), **changes}
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    return source, ground_plan_label(source, LearningCandidate.model_validate(raw))


def _plan(source, candidate, entries, resolution):
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch.model_validate(resolution),
    )


def _stored_plans(extra=()):
    """The plans in the catalog at story-10, built from their recorded turns."""
    entries = []
    for step, assertion_id in STORED + tuple(extra):
        source, candidate = _replay(step)
        (mutation,) = _plan(source, candidate, entries, S[step]["resolution"]).mutations
        value = mutation.draft.value
        entries.append(
            LearningCatalogEntry(
                assertion_id=assertion_id,
                predicate=f"plan_{assertion_id}",
                category="plan",
                text=mutation.draft.normalized_text,
                value=json.dumps(value, ensure_ascii=False),
                kind=value["kind"],
            )
        )
    return entries


def _story_10(entries, target=SPITI, text=None, **changes):
    source, candidate = _replay("story-10", text, **changes)
    resolution = {
        "resolutions": [
            {"candidate_index": 0, "decision": "match", "target_id": target}
        ]
    }
    return _plan(source, candidate, entries, resolution)


def test_recorded_story_10_is_eligible_and_its_kind_differs_from_the_stored_plan():
    source, candidate = _replay("story-10")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    assert (candidate.intent, candidate.kind) == ("new", "vehicle")
    entries = {e.assertion_id: e for e in _stored_plans()}
    assert entries[SPITI].kind == "other"
    stored = json.loads(entries[SPITI].value)
    assert stored["slots"]["destination"]["options"] == ["Ladakh", "winter Spiti"]
    assert S["story-10"]["status"]["skipped"] == [
        {"category": "plan", "reason": "new_fact_cannot_mutate_target"}
    ]


def test_recorded_decision_now_changes_the_matched_plan_and_keeps_its_kind():
    entries = _stored_plans()
    old = json.loads(next(e for e in entries if e.assertion_id == SPITI).value)
    plan = _story_10(entries)
    assert plan.outcomes == ()
    (mutation,) = plan.mutations
    assert (mutation.action, mutation.expected_assertion_id) == ("change", SPITI)
    assert mutation.effective_at is None
    value = mutation.draft.value
    assert value["kind"] == "other"
    assert mutation.draft.normalized_text.startswith("plan.other: ")
    assert value["slots"]["destination"] == {
        "value": "winter Spiti",
        "options": [],
        "certainty": "confirmed",
    }
    assert value["slots"]["vehicle"]["value"] == "Jimny"
    assert value["slots"]["when"] == old["slots"]["when"]  # January kept
    assert value["plan_status"] == "planned"


def test_another_plan_offering_the_same_option_is_ambiguous_and_refused():
    entries = _stored_plans()
    twin = json.loads(next(e for e in entries if e.assertion_id == SPITI).value)
    for kind in ("other", "vehicle"):  # of any kind
        other = LearningCatalogEntry(
            assertion_id="plan-twin",
            predicate="plan_plan-twin",
            category="plan",
            text="plan.other: mountain trip",
            value=json.dumps({**twin, "label": "mountain trip", "kind": kind}),
            kind=kind,
        )
        plan = _story_10([*entries, other])
        assert plan.mutations == (), kind
        assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]


def test_an_unrelated_plan_the_resolver_points_at_is_never_changed():
    entries = _stored_plans()
    for target in ("plan-goa", "plan-rishikesh"):
        plan = _story_10(entries, target=target)
        assert plan.mutations == (), target
        assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]


def test_a_value_that_was_never_an_option_is_refused_whatever_the_kind():
    text = "We're going with Kerala, and we'll take the Jimny."
    (raw,) = S["story-10"]["extraction"]["candidates"]
    slots = json.loads(json.dumps(raw["slots"]))
    slots["destination"]["value"] = "Kerala"
    plan = _story_10(
        _stored_plans(),
        text=text,
        label="Kerala",
        value="Kerala",
        slots=slots,
        evidence=[{"turn_id": "replaced", "start": 0, "end": len(text)}],
    )
    assert plan.mutations == ()


def test_a_tentative_choice_or_a_plan_only_considered_is_refused():
    (raw,) = S["story-10"]["extraction"]["candidates"]
    slots = json.loads(json.dumps(raw["slots"]))
    slots["destination"]["certainty"] = "tentative"
    for changes in ({"slots": slots}, {"plan_status": "considering"}):
        plan = _story_10(_stored_plans(), **changes)
        assert plan.mutations == (), changes


def test_a_mis_kinded_detail_that_decides_nothing_still_cannot_mutate_the_plan():
    # Only the option-decision change ignores the proposal's kind. Adding a
    # detail under a different kind is not a refine of the stored plan.
    text = "We'll stay in a homestay on the winter Spiti trip."
    plan = _story_10(
        _stored_plans(),
        text=text,
        label="winter Spiti trip",
        value="winter Spiti",
        slots={
            "destination": None,
            "when": None,
            "vehicle": None,
            "stay": {"value": "homestay", "options": [], "certainty": "confirmed"},
            "companions": None,
            "other": None,
        },
        evidence=[{"turn_id": "replaced", "start": 0, "end": len(text)}],
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]


def test_an_owned_item_matched_to_the_plan_is_never_a_decision():
    text = "We're going with winter Spiti, and we'll take the Jimny."
    plan = _story_10(
        _stored_plans(),
        category="owned_item",
        label="Jimny",
        value="Jimny",
        state="owned",
        plan_status=None,
        slots=None,
        evidence=[{"turn_id": "replaced", "start": 0, "end": len(text)}],
    )
    assert plan.mutations == ()
