"""Plan corrections change only what they restate (shared update rule), and
D1's ambiguous "have ... from 2021" never establishes a purchase date.

Owner decisions 2026-11-23 17:27.
"""

from __future__ import annotations

import json

from test_slice1_d12_d16 import _source
from test_slice1_lab7 import D1_TEXT, _recorded, _stored_items

from jarvis.authority.personal_learning import POLICY_VERSION
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


def _slot(value=None, options=()):
    return {"value": value, "options": list(options), "certainty": "confirmed"}


STORED_PLAN = {
    "schema": POLICY_VERSION,
    "category": "plan",
    "kind": "other",
    "label": "winter Spiti",
    "value": "winter Spiti",
    "state": "planned",
    "certainty": "confirmed",
    "plan_status": "planned",
    "location": "Spiti",
    "temporal": {"expression": "January", "precision": "unresolved"},
    "slots": {
        "destination": _slot("winter Spiti"),
        "vehicle": _slot("Jimny"),
        "when": _slot("January"),
        "stay": _slot("homestay"),
        "companions": _slot("Ravi"),
    },
}


def _entry(value=STORED_PLAN, assertion_id="plan-spiti"):
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=f"plan_{assertion_id}",
        category="plan",
        text=f"plan.other: {value['label']}",
        value=json.dumps(value),
        kind="other",
    )


def _correct(text, label, entries=None, **fields):
    source = _source(text)
    candidate = LearningCandidate(
        category="plan",
        kind="other",
        intent="correction",
        label=label,
        value=fields.pop("value", label),
        state="planned",
        plan_status=fields.pop("plan_status", "planned"),
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
        **fields,
    )
    assert LearningPolicy().evaluate(source, candidate).status == "eligible", text
    entries = entries or [_entry()]
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=entries),
        LearningResolutionBatch(
            resolutions=[
                {
                    "candidate_index": 0,
                    "decision": "match",
                    "target_id": entries[0].assertion_id,
                }
            ]
        ),
    )


def test_a_plan_date_correction_keeps_destination_vehicle_and_other_details():
    plan = _correct(
        "Correction: the Spiti trip is in February, not January.",
        "Spiti trip",
        value="Spiti trip",
        time_expression="February",
        slots={"when": _slot("February")},
    )
    (mutation,) = plan.mutations
    assert mutation.action == "correct"
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("winter Spiti", "winter Spiti")
    slots = value["slots"]
    assert slots["when"]["value"] == "February"
    for name in ("destination", "vehicle", "stay", "companions"):
        assert slots[name] == STORED_PLAN["slots"][name], name
    assert value["temporal"]["expression"] == "February"
    assert value["location"] == "Spiti" and value["plan_status"] == "planned"


def test_a_correction_naming_a_different_plan_renames_it_and_keeps_the_rest():
    plan = _correct(
        "I misspoke, it's the Kerala trip, not the Spiti trip.",
        "Kerala trip",
        slots={"destination": _slot("Kerala")},
    )
    (mutation,) = plan.mutations
    value = mutation.draft.value
    assert value["label"] == "Kerala trip"
    assert value["slots"]["destination"]["value"] == "Kerala"
    assert value["slots"]["vehicle"]["value"] == "Jimny"
    assert value["slots"]["when"]["value"] == "January"


def test_a_stated_removal_cannot_delete_a_detail_and_is_recorded():
    # The slice-1 proposal schema has no removal marker: an empty slot means
    # "not said". The vehicle is kept and the correction is recorded unclear.
    plan = _correct(
        "Correction: we're not taking the Jimny on the Spiti trip.",
        "Spiti trip",
        value="Spiti trip",
        slots={"vehicle": _slot()},
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["correction_unclear"]


def test_a_correction_that_restates_nothing_different_is_unclear():
    plan = _correct(
        "Correction: the winter Spiti trip.",
        "winter Spiti",
        slots={"destination": _slot("winter Spiti")},
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["correction_unclear"]


def test_a_status_correction_changes_only_the_status():
    plan = _correct(
        "Correction: the Spiti trip is only being considered.",
        "Spiti trip",
        value="Spiti trip",
        plan_status="considering",
    )
    (mutation,) = plan.mutations
    value = mutation.draft.value
    assert value["plan_status"] == "considering"
    assert value["slots"] == STORED_PLAN["slots"]
    assert value["label"] == "winter Spiti"


# -- D1: "I have a Royal Enfield Classic 350 from 2021" ------------------------------


def test_d1_original_ambiguous_from_2021_never_becomes_a_purchase_date():
    entries = _stored_items()  # lab 7's recorded D1 proposals, replayed
    classic = json.loads(entries["Royal Enfield Classic 350"].value)
    tigor = json.loads(entries["Tata Tigor"].value)
    jimny = json.loads(entries["Jimny"].value)
    assert "acquired" not in classic  # "from 2021": model year or since? unclear
    assert tigor["acquired"]["earliest"] == "2017-03-01"  # "I bought in March 2017"
    assert jimny["acquired"]["earliest"] == "2026-10-01"  # "last month I got"


def test_d1_ambiguity_is_recorded_when_nothing_else_is_said():
    entries = _stored_items()
    text = "My Classic 350 is from 2021."
    source, candidate = _recorded(
        "story-02",
        0,
        text=text,
        label="Classic 350",
        value="Classic 350",
        acquired_expression="2021",
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries.values())),
        LearningResolutionBatch(
            resolutions=[
                {
                    "candidate_index": 0,
                    "decision": "match",
                    "target_id": entries["Royal Enfield Classic 350"].assertion_id,
                }
            ]
        ),
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_evidence_missing"]


def test_explicit_purchase_or_since_wording_still_establishes_the_date():
    for text in (
        "I bought a Royal Enfield Classic 350 in 2021.",
        "I've had a Royal Enfield Classic 350 since 2021.",
    ):
        source, candidate = _recorded(
            "story-02", 0, text=text, acquired_expression="2021"
        )
        plan = LearningReconciler(None, None).plan(
            source,
            LearningBatch(candidates=[candidate]),
            LearningCatalog(),
            LearningResolutionBatch(
                resolutions=[{"candidate_index": 0, "decision": "new"}]
            ),
        )
        (mutation,) = plan.mutations
        acquired = mutation.draft.value["acquired"]
        assert (acquired["precision"], acquired["earliest"]) == ("year", "2021-01-01")


def test_d1_text_is_the_frozen_wording():
    assert D1_TEXT.startswith("I have a Royal Enfield Classic 350 from 2021,")


# Proposed amendment 1 (not frozen, not yet approved): D1 with explicit
# purchase wording. Assessed in code with lab 7's recorded proposals.
AMENDED_D1 = (
    "I have a Royal Enfield Classic 350 I bought in 2021, a Tata Tigor I bought"
    " in March 2017, and last month I got a Jimny."
)


def test_proposed_amended_d1_wording_establishes_all_three_dates():
    from test_slice1_lab7 import S

    source = _source(AMENDED_D1, "2026-11-17")
    candidates = [
        LearningCandidate.model_validate(
            {
                **json.loads(json.dumps(S["story-02"]["extraction"]["candidates"][i])),
                "evidence": [
                    {"turn_id": source.turn_id, "start": 0, "end": len(AMENDED_D1)}
                ],
            }
        )
        for i in range(3)
    ]
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=candidates),
        LearningCatalog(),
        LearningResolutionBatch.model_validate(S["story-02"]["resolution"]),
    )
    got = {
        m.draft.value["label"]: (
            m.draft.value["acquired"]["precision"],
            m.draft.value["acquired"]["earliest"],
            m.draft.value["acquired"]["latest"],
        )
        for m in plan.mutations
    }
    assert got == {
        "Royal Enfield Classic 350": ("year", "2021-01-01", "2021-12-31"),
        "Tata Tigor": ("month", "2017-03-01", "2017-03-31"),
        "Jimny": ("month", "2026-10-01", "2026-10-31"),
    }
