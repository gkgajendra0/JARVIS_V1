"""One grounded plan date, whether the model repeats it in both fields or not."""

import json
from datetime import date
from pathlib import Path

import pytest
from test_slice1_d12_d16 import _source

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
from jarvis.memory.personal_time import date_status

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_7e787c53_d13.json").read_text(
        encoding="utf-8"
    )
)


def _candidate(text, when=None, *, day="2026-09-15", **fields):
    source = _source(text, day)
    slots = fields.pop("slots", {})
    if when is not None:
        slots["when"] = {"value": when, "certainty": "confirmed"}
    return source, LearningCandidate(
        category="plan",
        kind="other",
        label="Alpine trip",
        value="Alpine trip",
        intent=fields.pop("intent", "new"),
        state="planned",
        plan_status="planned",
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
        slots=slots,
        **fields,
    )


def _plan(source, candidate, old=None):
    entries = (
        []
        if old is None
        else [
            LearningCatalogEntry(
                assertion_id="existing-plan",
                predicate="plan_alpine",
                category="plan",
                kind="other",
                text="plan.other: Alpine trip",
                value=json.dumps(old),
            )
        ]
    )
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=entries),
        LearningResolutionBatch(
            resolutions=[
                {
                    "candidate_index": 0,
                    "decision": "new" if old is None else "match",
                    "target_id": None if old is None else "existing-plan",
                }
            ]
        ),
    )


def _stored():
    source, candidate = _candidate(
        "Alpine trip in October 2026.", "October 2026", time_expression="October 2026"
    )
    return _plan(source, candidate).mutations[0].draft.value


def test_recorded_plan_when_without_duplicate_time_has_elapsed_metadata():
    source = _source(RECORDED["utterance"], RECORDED["told_date"])
    raw = json.loads(json.dumps(RECORDED["extraction"]["candidates"][0]))
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    candidate = LearningCandidate.model_validate(raw)
    assert candidate.time_expression is None
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    value = _plan(source, candidate).mutations[0].draft.value
    temporal = value["temporal"]
    assert temporal["expression"] == "October 2026"
    assert temporal["date"] is None
    assert (temporal["precision"], temporal["earliest"], temporal["latest"]) == (
        "month",
        "2026-10-01",
        "2026-10-31",
    )
    assert date_status(temporal, date(2026, 11, 20)) == "passed_outcome_unknown"


@pytest.mark.parametrize(
    "expression, precision, first, last",
    [
        ("October 2026", "month", "2026-10-01", "2026-10-31"),
        ("2027", "year", "2027-01-01", "2027-12-31"),
        ("14 October 2026", "day", "2026-10-14", "2026-10-14"),
        ("between October 2026 and November 2026", "range", "2026-10-01", "2026-11-30"),
        ("January", "unresolved", None, None),
    ],
)
def test_confirmed_when_keeps_stated_precision(expression, precision, first, last):
    source, candidate = _candidate("Alpine trip in " + expression + ".", expression)
    value = _plan(source, candidate).mutations[0].draft.value
    assert (
        value["temporal"]["precision"],
        value["temporal"]["earliest"],
        value["temporal"]["latest"],
    ) == (precision, first, last)


@pytest.mark.parametrize("intent", ["change", "correction"])
def test_when_only_date_update_keeps_schedule_and_calendar_together(intent):
    source, candidate = _candidate(
        "Alpine trip is in November 2026, not October 2026.",
        "November 2026",
        intent=intent,
    )
    mutation = _plan(source, candidate, _stored()).mutations[0]
    assert mutation.action == ("correct" if intent == "correction" else "change")
    assert mutation.draft.value["slots"]["when"]["value"] == "November 2026"
    assert mutation.draft.value["temporal"]["earliest"] == "2026-11-01"


def test_adding_missing_when_refines_calendar_too():
    old = _stored()
    old.pop("slots")
    old["temporal"] = {"expression": None, "date": None}
    source, candidate = _candidate("Alpine trip in October 2026.", "October 2026")
    mutation = _plan(source, candidate, old).mutations[0]
    assert mutation.action == "refine"
    assert mutation.draft.value["temporal"]["earliest"] == "2026-10-01"


def test_refinement_cannot_contradict_existing_calendar_without_a_when_slot():
    old = _stored()
    old.pop("slots")
    source, candidate = _candidate("Alpine trip in November 2026.", "November 2026")
    plan = _plan(source, candidate, old)
    assert not plan.mutations
    assert [o.reason for o in plan.outcomes] == ["refine_conflicts_existing_detail"]


def test_pending_dates_do_not_acquire_one_options_calendar():
    source, candidate = _candidate(
        "Alpine trip in October 2026 or November 2026.",
        slots={
            "when": {
                "options": ["October 2026", "November 2026"],
                "certainty": "confirmed",
            }
        },
        time_expression="October 2026",
    )
    value = _plan(source, candidate).mutations[0].draft.value
    assert not value["temporal"].get("precision")
    assert not value["temporal"].get("date")
    assert "when" not in value.get("slots", {})


def test_unrelated_plan_detail_preserves_existing_date_and_anchor():
    old = _stored()
    source, candidate = _candidate(
        "Alpine trip with Jimny.", slots={"vehicle": {"value": "Jimny"}}
    )
    value = _plan(source, candidate, old).mutations[0].draft.value
    assert value["temporal"] == old["temporal"]


def test_when_still_requires_owner_evidence():
    source, candidate = _candidate("Alpine trip.", "October 2026")
    assert not _plan(source, candidate).mutations


def test_relative_schedule_uses_its_quoted_turn_not_later_confirmation():
    from test_slice1_d12_d16 import StampedConversation

    from jarvis.memory.learning_contracts import AcceptedLearningSource

    conversation = StampedConversation()
    conversation.start()
    first = conversation.say("Alpine trip next month.", "2026-09-15")
    last = conversation.say("Alpine trip is still planned.", "2026-11-20")
    source = AcceptedLearningSource.from_turn("runtime", conversation, last, now=100)
    candidate = LearningCandidate(
        category="plan",
        kind="other",
        intent="new",
        label="Alpine trip",
        value="Alpine trip",
        state="planned",
        plan_status="planned",
        slots={"when": {"value": "next month"}},
        evidence=[
            EvidenceSpan(turn_id=t.turn_id, start=0, end=len(t.text))
            for t in (first, last)
        ],
    )
    temporal = _plan(source, candidate).mutations[0].draft.value["temporal"]
    assert temporal["earliest"] == "2026-10-01"
    assert temporal["local_date"] == "2026-09-15"
    assert temporal["recorded_at"].startswith("2026-11-20")


def test_refine_cannot_reanchor_an_existing_relative_schedule():
    source, candidate = _candidate("Alpine trip next month.", "next month")
    old = _plan(source, candidate).mutations[0].draft.value
    source, candidate = _candidate(
        "Alpine trip next month with Jimny.",
        "next month",
        day="2026-11-20",
        slots={"vehicle": {"value": "Jimny"}},
    )
    assert not _plan(source, candidate, old).mutations


@pytest.mark.parametrize("intent", ["change", "correction"])
def test_accepted_undecided_schedule_cannot_keep_the_old_decided_calendar(intent):
    source, candidate = _candidate(
        "Alpine trip in October 2026 or November 2026.",
        intent=intent,
        slots={"when": {"options": ["October 2026", "November 2026"]}},
        owner_confirmed=("when",),
    )
    value = _plan(source, candidate, _stored()).mutations[0].draft.value
    assert value["slots"]["when"]["value"] is None
    assert not value["temporal"].get("precision")


def test_top_level_time_still_supports_legacy_proposals_without_schedule_slot():
    source, candidate = _candidate(
        "Alpine trip in October 2026.", time_expression="October 2026"
    )
    assert (
        _plan(source, candidate).mutations[0].draft.value["temporal"]["earliest"]
        == "2026-10-01"
    )


def test_explicit_schedule_is_the_canonical_plan_calendar():
    source, candidate = _candidate(
        "Alpine trip in November 2026, discussed in October 2026.",
        "November 2026",
        time_expression="October 2026",
    )
    value = _plan(source, candidate).mutations[0].draft.value
    assert value["temporal"]["expression"] == value["slots"]["when"]["value"]


@pytest.mark.parametrize("other_slots", [{}, {"vehicle": {"value": "Jimny"}}])
def test_relative_schedule_correction_compares_anchored_window(other_slots):
    source, candidate = _candidate("Alpine trip next month.", "next month")
    old = _plan(source, candidate).mutations[0].draft.value
    assert old["temporal"]["earliest"] == "2026-10-01"
    source, candidate = _candidate(
        "Correction: Alpine trip next month with Jimny.",
        "next month",
        day="2026-11-20",
        intent="correction",
        slots=other_slots,
    )
    mutation = _plan(source, candidate, old).mutations[0]
    assert mutation.action == "correct"
    assert mutation.draft.value["temporal"]["earliest"] == "2026-12-01"
