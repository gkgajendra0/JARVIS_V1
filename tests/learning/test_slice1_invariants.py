"""General slice-1 invariants (outside the frozen case files).

1. Changing one attribute of an owned item, by correction or by real-world
   change, keeps the item's identity and every unrelated attribute.
2. A plan decision among stated options reaches the same plan across
   legitimate label variations on either side, and never another plan.
3. Missing told-time evidence never produces a told date.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_slice1_d7_d10 import _slot
from test_slice1_d12_d16 import JIMNY_ID, _correct, _entry, _recorded, _source

from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_context_projection import _learned, _told_date

# -- 1. one attribute changes, identity and the rest are kept ---------------------

STORED = {
    "schema": None,  # replaced with the current policy version below
    "category": "owned_item",
    "kind": "vehicle",
    "label": "Jimny",
    "value": "Maruti Jimny",
    "state": "owned",
    "aliases": ["the 4x4"],
    "details": "the white one",
    "acquired": {
        "expression": "last month",
        "precision": "month",
        "earliest": "2026-10-01",
        "latest": "2026-10-31",
        "basis": "stated",
    },
}


def _stored_jimny():
    from jarvis.authority.personal_learning import POLICY_VERSION

    return {**STORED, "schema": POLICY_VERSION}


# (owner text, intent, proposal fields, attribute expected to change)
ONE_ATTRIBUTE = [
    (
        "I misspoke, the Jimny is from September, not October.",
        "correction",
        {"value": "September", "acquired_expression": "September"},
        "acquired",
    ),
    (
        "I misspoke, the Jimny is from September, not October.",
        "correction",
        {"value": "Jimny", "acquired_expression": "September"},
        "acquired",
    ),
    (
        "Correction: the Jimny is the grey one.",
        "correction",
        {"details": "the grey one"},
        "details",
    ),
    (
        "I sold the Jimny last week.",
        "change",
        {"state": "sold", "disposed_expression": "last week"},
        "disposed",
    ),
    (
        "I sold the Jimny last week.",
        "change",
        {"value": "last week", "state": "sold", "disposed_expression": "last week"},
        "disposed",
    ),
]


@pytest.mark.parametrize("text,intent,fields,changed", ONE_ATTRIBUTE)
def test_changing_one_attribute_keeps_identity_and_unrelated_attributes(
    text, intent, fields, changed
):
    stored = _stored_jimny()
    entry = _entry(stored, JIMNY_ID)
    source = _source(text)
    candidate = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent=intent,
        label="Jimny",
        value=fields.pop("value", "Jimny"),
        state=fields.pop("state", "owned"),
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
        **fields,
    )
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    (mutation,) = _correct([entry], JIMNY_ID, source, candidate).mutations
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("Jimny", "Maruti Jimny")
    assert changed in value and value[changed] != stored.get(changed)
    for key in ("aliases", "details", "acquired", "kind", "category"):
        if key != changed:
            assert value[key] == stored[key], key


@pytest.mark.parametrize(
    "label,stored_label",
    [
        ("Tigor", "Tata Tigor"),
        ("Tata Tigor", "Tata Tigor"),
        ("the Tigor", "Tata Tigor"),
    ],
)
def test_a_name_that_refers_to_the_item_never_replaces_its_identity(
    label, stored_label
):
    stored = {
        **_stored_jimny(),
        "label": stored_label,
        "value": stored_label,
        "aliases": [],
        "details": "diesel",
    }
    entry = _entry(stored, "tigor")
    text = f"Sorry, {label} is from April 2017, not March."
    source, candidate = _recorded(
        "story-12",
        text=text,
        label=label,
        value="April 2017",
        time_expression="April 2017",
        acquired_expression="April 2017",
    )
    (mutation,) = _correct([entry], "tigor", source, candidate).mutations
    value = mutation.draft.value
    assert (value["label"], value["value"]) == (stored_label, stored_label)
    assert value["details"] == "diesel"


# -- 2. plan decisions across legitimate label variations -------------------------


def _plan_entry(label, assertion_id="plan-1", options=("Ladakh", "winter Spiti")):
    from jarvis.authority.personal_learning import POLICY_VERSION

    value = {
        "schema": POLICY_VERSION,
        "category": "plan",
        "kind": "other",
        "label": label,
        "value": label,
        "state": "planned",
        "certainty": "confirmed",
        "plan_status": "planned",
        "slots": {
            "destination": {
                "value": None,
                "options": list(options),
                "certainty": "tentative",
            },
            "when": {"value": "January", "options": [], "certainty": "confirmed"},
        },
    }
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=f"plan_{assertion_id}",
        category="plan",
        text=f"plan.other: {label}",
        value=json.dumps(value),
        kind="other",
    )


def _decision(label, text="We're going with winter Spiti, and we'll take the Jimny."):
    source = _source(text)
    return source, LearningCandidate(
        category="plan",
        kind="other",
        intent="new",
        label=label,
        value=text,
        state="planned",
        plan_status="planned",
        slots={"destination": _slot("winter Spiti"), "vehicle": _slot("Jimny")},
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
    )


def _plan(entries, source, candidate, target):
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch(
            resolutions=[
                {"candidate_index": 0, "decision": "match", "target_id": target}
            ]
        ),
    )


@pytest.mark.parametrize(
    "stored_label",
    ["trip", "Ladakh or winter Spiti trip", "January trip", "mountain trip"],
)
@pytest.mark.parametrize(
    "decision_label",
    [
        "winter Spiti",
        "We're going with winter Spiti, and we'll take the Jimny.",
        "Jimny",
    ],
)
def test_a_decision_reaches_the_same_plan_across_label_variations(
    stored_label, decision_label
):
    entry = _plan_entry(stored_label)
    source, candidate = _decision(decision_label)
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    plan = _plan([entry], source, candidate, entry.assertion_id)
    (mutation,) = plan.mutations
    assert mutation.action == "change" and mutation.expected_assertion_id == "plan-1"
    slots = mutation.draft.value["slots"]
    assert slots["destination"]["value"] == "winter Spiti"
    assert slots["vehicle"]["value"] == "Jimny"
    assert slots["when"]["value"] == "January"


def test_a_decision_never_changes_a_plan_that_did_not_offer_it():
    goa = _plan_entry("Goa trip", "plan-goa", options=("Goa", "Gokarna"))
    spiti = _plan_entry("trip")
    source, candidate = _decision("winter Spiti")
    # The resolver points at a plan that never offered the choice.
    assert _plan([goa, spiti], source, candidate, "plan-goa").mutations == ()


def test_two_plans_offering_the_same_option_need_the_name_to_tell_them_apart():
    source, candidate = _decision("winter Spiti")
    # Neither stored name says "winter Spiti": ambiguous, nothing is changed.
    first, twin = _plan_entry("trip"), _plan_entry("another trip", "plan-2")
    assert _plan([first, twin], source, candidate, "plan-1").mutations == ()
    # The owner's words name exactly one of them: that plan changes.
    named = _plan_entry("Ladakh or winter Spiti trip")
    (mutation,) = _plan([named, twin], source, candidate, "plan-1").mutations
    assert mutation.action == "change" and mutation.expected_assertion_id == "plan-1"


# -- 3. told time is never invented ---------------------------------------------

OWNER = "owner_direct"


@pytest.mark.parametrize(
    "observed",
    [None, "", "   ", "not a time", "2026-13-40T00:00:00Z", "2026-11-19T06:30:00", 0],
)
def test_missing_or_unusable_told_time_never_becomes_a_date(observed):
    assert _told_date(observed) is None
    learned = _learned(((OWNER, observed, "the Jimny is from September"),))
    assert learned["told"]["date"] is None
    assert "first_told" not in learned


@pytest.mark.parametrize(
    "source_class",
    ["external_web", "external_file", "assistant_output", "reflection", "tool"],
)
def test_a_non_owner_source_never_gets_a_told_date(source_class):
    learned = _learned(((source_class, "2026-11-19T06:30:00Z", "quoted"),))
    assert learned == {"told": {"how": source_class, "date": None}}


def test_recording_time_is_never_used_for_the_told_date():
    # A row recorded days after it was said: told.date follows observed_at.
    told = datetime(2026, 11, 17, 6, 30, tzinfo=UTC)
    learned = _learned(((OWNER, told.isoformat().replace("+00:00", "Z"), "q"),))
    assert learned["told"]["date"] == "2026-11-17"


def test_without_provenance_no_told_field_is_released():
    from jarvis.memory.personal_context_projection import _released_fact

    class Row:
        subject_scope, subject, predicate = "personal", "owner", "owned_item_x"
        normalized_text = "owned_item.vehicle: Jimny"
        value = "Jimny"
        system_from = datetime(2026, 11, 22, tzinfo=UTC)
        assertion_id = "x"

    from jarvis.memory.types import (
        AssertionState,
        FreshnessClass,
        Sensitivity,
        ValueType,
    )

    Row.state = AssertionState.ACTIVE
    Row.valid_to = None
    Row.sensitivity = Sensitivity.STANDARD
    Row.freshness_class = FreshnessClass.STABLE
    Row.value_type = ValueType.TEXT
    fact = _released_fact(Row, "owned_item.vehicle", 1, datetime.now(UTC))
    assert "told" not in fact and "first_told" not in fact
    assert fact["recorded_at"]
