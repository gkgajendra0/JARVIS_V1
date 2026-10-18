"""Offline-only adversarial tests for a synthetic memory decision projection."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tools.research.step5_memory_decision_acceptance import (
    case_decisions,
    compare_pinned_recall_shadow,
    decide_from_pinned_recall,
    frozen_assertions,
    large_fictional_corpus,
    verify_large_synthetic,
    verify_nine_cases,
)

from jarvis.memory.hindsight_transfer_shadow import PINNED_FACTS
from jarvis.memory.research_decision_gate import (
    Assertion,
    DecisionSafetyError,
    MemoryDecision,
    MemoryDecisionIndex,
    MemoryQuestion,
    compare_shadow,
)


def _index() -> MemoryDecisionIndex:
    return MemoryDecisionIndex(frozen_assertions())


def _at(assertion_id: str, *, changed: dict[str, object] | None = None) -> Assertion:
    fact = next(f for f in frozen_assertions() if f.assertion_id == assertion_id)
    return replace(fact, **(changed or {}))


def test_frozen_decision_acceptance_nine_of_nine():
    result = verify_nine_cases()
    assert result["passed"] is True
    assert result["cases"] == result["passed_cases"] == 9
    assert result["answer_cases"] == 7
    assert result["abstention_cases"] == 2
    assert result["real_llm_accuracy_measured"] is False
    assert result["real_hindsight_decision_accuracy_measured"] is False
    assert result["production_promotion_allowed"] is False


def test_correction_current_original_and_full_lineage():
    decisions = case_decisions()
    current = decisions["atlas_current_day"]
    assert current.answer_code == "sunday"
    assert current.evidence_assertion_ids == ("synthetic-workshop-day-v2",)
    assert decisions["atlas_original_day"].answer_code == "saturday"
    history = decisions["atlas_correction_trace"]
    assert history.answer_code == "saturday_corrected_to_sunday"
    assert history.evidence_assertion_ids == (
        "synthetic-workshop-day-v1",
        "synthetic-workshop-day-v2",
    )
    assert history.reason_code == "grounded_correction"


def test_historical_change_keeps_older_state():
    decisions = case_decisions()
    assert decisions["nile_current_report_day"].answer_code == "thursday"
    assert decisions["nile_previous_report_day"].answer_code == "monday"
    history = decisions["nile_historical_change"]
    assert history.answer_code == "monday_then_thursday"
    assert history.reason_code == "grounded_historical_change"


def test_unknown_information_requires_explicit_abstention():
    decisions = case_decisions()
    for case_id in ("unknown_start_time", "unresolved_ambiguous_statement"):
        result = decisions[case_id]
        assert result.status == "abstain"
        assert result.answer_code is None
        assert result.evidence_assertion_ids == ()
        assert result.reason_code == "insufficient_evidence"


def test_independent_venue_does_not_inherit_day_corrections():
    result = case_decisions()["atlas_unrelated_venue"]
    assert result.status == "answer"
    assert result.answer_code == "hall_b"
    assert result.evidence_assertion_ids == ("synthetic-workshop-venue-v1",)


def test_empty_corpus_always_abstains():
    result = MemoryDecisionIndex(()).decide(
        MemoryQuestion("synthetic-atlas", "workshop_day", "current")
    )
    assert result.status == "abstain"
    assert result.reason_code == "insufficient_evidence"


def test_missing_predecessor_cannot_turn_latest_into_truth():
    current = _at("synthetic-workshop-day-v2")
    index = MemoryDecisionIndex((current,))
    result = index.decide(MemoryQuestion("synthetic-atlas", "workshop_day", "current"))
    assert result.status == "abstain"
    assert result.reason_code == "conflicting_roots"


def test_multiple_roots_for_same_predicate_abstain():
    original = _at("synthetic-workshop-day-v1")
    other = replace(
        original, assertion_id="synthetic-workshop-day-another", value="friday"
    )
    result = MemoryDecisionIndex((original, other)).decide(
        MemoryQuestion("synthetic-atlas", "workshop_day", "current")
    )
    assert result.status == "abstain"
    assert result.reason_code == "conflicting_roots"


def test_branching_successors_abstain_not_latest_timestamp():
    original = _at("synthetic-workshop-day-v1")
    corrected = _at("synthetic-workshop-day-v2")
    other = replace(
        corrected, assertion_id="synthetic-workshop-day-v2-other", value="friday"
    )
    result = MemoryDecisionIndex((original, corrected, other)).decide(
        MemoryQuestion("synthetic-atlas", "workshop_day", "current")
    )
    assert result.status == "abstain"
    assert result.reason_code == "conflicting_successors"


def test_invalid_version_gap_does_not_forge_lineage():
    original = _at("synthetic-workshop-day-v1")
    changed = _at("synthetic-workshop-day-v2", changed={"version": 3})
    result = MemoryDecisionIndex((original, changed)).decide(
        MemoryQuestion("synthetic-atlas", "workshop_day", "current")
    )
    assert result.status == "abstain"
    assert result.reason_code == "invalid_lineage"


def test_wrong_subject_predecessor_abstains():
    original = _at("synthetic-workshop-day-v1")
    corrected = _at("synthetic-workshop-day-v2", changed={"subject": "synthetic-nile"})
    result = MemoryDecisionIndex((original, corrected)).decide(
        MemoryQuestion("synthetic-nile", "workshop_day", "current")
    )
    assert result.status == "abstain"


def test_backdated_revision_abstains():
    original = _at("synthetic-workshop-day-v1")
    changed = _at(
        "synthetic-workshop-day-v2",
        changed={"mentioned_at": "2025-01-01T10:00:00Z"},
    )
    assert (
        MemoryDecisionIndex((original, changed))
        .decide(MemoryQuestion("synthetic-atlas", "workshop_day", "current"))
        .status
        == "abstain"
    )


def test_mixed_correction_and_history_requires_review():
    original = _at("synthetic-workshop-day-v1")
    corrected = _at("synthetic-workshop-day-v2")
    third = replace(
        corrected,
        assertion_id="synthetic-workshop-day-v3",
        version=3,
        value="tuesday",
        mentioned_at="2026-01-04T10:00:00Z",
        revision_kind="historical_change",
        supersedes_id="synthetic-workshop-day-v2",
    )
    decision = MemoryDecisionIndex((original, corrected, third)).decide(
        MemoryQuestion("synthetic-atlas", "workshop_day", "history")
    )
    assert decision.status == "abstain"
    assert decision.reason_code == "mixed_revision_semantics"


def test_duplicate_assertion_rejected():
    original = _at("synthetic-workshop-day-v1")
    with pytest.raises(DecisionSafetyError, match="duplicate_assertion"):
        MemoryDecisionIndex((original, original))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("assertion_id", "owner-memory"),
        ("subject", "owner-private"),
        ("predicate", "danger!!!"),
        ("value", "my private data"),
        ("source_ref", "conversation:owner:123"),
        ("version", True),
        ("revision_kind", "unknown_future_state"),
        ("mentioned_at", "2026-01-02"),
        ("supersedes_id", "non-synthetic-owner-id"),
        ("assertion_id", None),
        ("subject", None),
        ("predicate", None),
        ("value", None),
    ],
)
def test_synthetic_boundary_rejects_untrusted_assertions(field: str, value: object):
    bad = _at("synthetic-workshop-day-v1", changed={field: value})
    with pytest.raises(DecisionSafetyError):
        MemoryDecisionIndex((bad,))


@pytest.mark.parametrize(
    ("subject", "predicate", "intent"),
    [
        ("owner-jimny", "workshop_day", "current"),
        ("synthetic-atlas", "owner secret", "current"),
        ("synthetic-atlas", "workshop_day", "guess"),
    ],
)
def test_unsafe_questions_fail_closed(subject: str, predicate: str, intent: str):
    with pytest.raises(DecisionSafetyError, match="untrusted_question"):
        _index().decide(MemoryQuestion(subject, predicate, intent))


def test_no_implicit_winner_by_input_order():
    facts = frozen_assertions()
    question = MemoryQuestion("synthetic-atlas", "workshop_day", "current")
    assert MemoryDecisionIndex(facts).decide(question) == MemoryDecisionIndex(
        tuple(reversed(facts))
    ).decide(question)


def test_shadow_disagreement_never_changes_canonical():
    canonical = case_decisions()["atlas_current_day"]
    proposal = MemoryDecision(
        "answer", "saturday", ("synthetic-workshop-day-v1",), "incorrect_proposal"
    )
    result = compare_shadow(canonical, proposal)
    assert result["equal"] is False
    assert result["canonical_unmodified"] is True
    assert result["memory_write_performed"] is False
    assert result["production_promotion_allowed"] is False
    assert canonical.answer_code == "sunday"


def test_shadow_comparison_requires_structured_decisions():
    with pytest.raises(DecisionSafetyError, match="invalid_shadow_decision"):
        compare_shadow("raw canonical response", case_decisions()["atlas_current_day"])


def test_large_synthetic_workload_covers_thousands_without_real_memory():
    corpus = large_fictional_corpus()
    assert len(corpus) == 3600
    assert len({f.assertion_id for f in corpus}) == 3600
    report = verify_large_synthetic()
    assert report["status"] == "pass"
    assert report["assertions"] == 3600
    assert report["decision_cases"] == report["passed_cases"] == 4200
    assert report["mismatches"] == 0
    assert report["shadow_disagreement_detected"] is True
    assert report["memory_write_performed"] is False
    assert report["real_server_benchmark"] is False


def test_large_corpus_input_is_bounded():
    for count in (-1, 0, 601, True):
        with pytest.raises(ValueError, match="unbounded_synthetic_groups"):
            large_fictional_corpus(count)


def test_isolated_cli_launch_nine_cases_and_large_workload():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "research" / "step5_memory_decision_acceptance.py"
    for args, expected_kind in (
        ([], "OFFLINE_MEMORY_DECISION_ACCEPTANCE"),
        (["--large-synthetic"], "OFFLINE_LARGE_SYNTHETIC_DECISION_BENCHMARK"),
    ):
        run = subprocess.run(
            [sys.executable, "-I", str(script), *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert run.returncode == 0, run.stderr
        data = json.loads(run.stdout)
        assert data["kind"] == expected_kind
        assert data["production_promotion_allowed"] is False


def test_abstention_does_not_claim_llm_or_server_accuracy():
    summary = verify_nine_cases()
    assert summary["real_llm_accuracy_measured"] is False
    assert summary["real_hindsight_decision_accuracy_measured"] is False
    assert summary["no_memory_write"] is True


def _recalled(*assertion_ids: str) -> dict[str, object]:
    """Fake responses use frozen facts and full metadata; never contact a server."""
    by_id = {fact.assertion_id: fact for fact in PINNED_FACTS}
    items = []
    for assertion_id in assertion_ids:
        fact = by_id[assertion_id]
        metadata = {
            "assertion_id": fact.assertion_id,
            "assertion_version": str(fact.version),
            "source_turn_id": fact.source_turn_id,
            "canonical_source_ref": f"conversation:synthetic:{fact.source_turn_id}",
            "predicate": fact.predicate,
            "revision_kind": fact.revision_kind,
            "source_class": "synthetic_owner_direct",
            "admission_policy": "shadow_only_no_write",
        }
        if fact.supersedes_id is not None:
            metadata["supersedes_id"] = fact.supersedes_id
        items.append(
            {
                "type": "world",
                "text": fact.text,
                "document_id": f"jarvis-dev-only-{fact.assertion_id}",
                "metadata": metadata,
            }
        )
    return {"results": items}


def test_shadow_candidate_uses_only_retrieved_correction_lineage():
    complete = _recalled("synthetic-workshop-day-v2", "synthetic-workshop-day-v1")
    result = decide_from_pinned_recall("atlas_current_day", complete)
    assert result.status == "answer"
    assert result.answer_code == "sunday"
    assert result.evidence_assertion_ids == ("synthetic-workshop-day-v2",)
    compare = compare_pinned_recall_shadow("atlas_current_day", complete)
    assert compare["equal"] is True
    assert compare["memory_write_performed"] is False


def test_shadow_candidate_abstains_if_recall_omits_predecessor():
    partial = _recalled("synthetic-workshop-day-v2")
    result = decide_from_pinned_recall("atlas_current_day", partial)
    assert result.status == "abstain"
    assert result.answer_code is None
    compare = compare_pinned_recall_shadow("atlas_current_day", partial)
    assert compare["equal"] is False
    assert compare["candidate_status"] == "abstain"
    assert compare["production_promotion_allowed"] is False


def test_shadow_candidate_never_borrows_global_fixture_for_history():
    partial = _recalled("synthetic-report-day-v2")
    result = decide_from_pinned_recall("nile_historical_change", partial)
    assert result.status == "abstain"


def test_shadow_candidate_rejects_fake_provenance_and_duplicates():
    good = _recalled("synthetic-workshop-day-v1")
    duplicate = {"results": good["results"] + good["results"]}
    with pytest.raises(ValueError, match="duplicate_recall_result"):
        decide_from_pinned_recall("atlas_original_day", duplicate)
    bad = _recalled("synthetic-workshop-day-v1")
    bad["results"][0]["metadata"]["canonical_source_ref"] = "forged-owner-ref"
    with pytest.raises(ValueError, match="fact_provenance_mismatch"):
        decide_from_pinned_recall("atlas_original_day", bad)


def test_shadow_candidate_unknown_case_and_large_payload_fail_closed():
    for case, payload in (
        ("owner-schedule", _recalled()),
        ("atlas_current_day", {"results": [None] * 100}),
    ):
        with pytest.raises(ValueError):
            decide_from_pinned_recall(case, payload)
