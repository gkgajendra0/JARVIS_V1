from __future__ import annotations

from jarvis.engineering_learning.evaluation import run_replay_suite

_EXPECTED_CASES = (
    "01_verified_success_accepted",
    "02_candidate_regression_negative_evidence",
    "03_external_provider_not_candidate_truth",
    "04_external_hardware_not_candidate_truth",
    "05_unknown_cause_inconclusive",
    "06_compatibility_ready_learned",
    "07_compatibility_blocked_learned",
    "08_contradiction_supersedes_prior",
    "09_restart_replay_idempotent",
    "10_crash_gap_recovery",
    "11_missing_attestation_blocks",
    "12_unknown_schema_blocks",
    "13_rejected_not_resurrected",
    "14_phase6_advisory_retrieval",
    "15_malformed_integrity_reference_blocks",
)


def test_phase10_replay_suite_covers_complete_approved_matrix(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "phase10-replay")

    failures = {item.case_id: item.evidence for item in report.cases if not item.passed}
    assert failures == {}
    assert report.status == "PASS"
    assert tuple(item.case_id for item in report.cases) == _EXPECTED_CASES
    assert len(report.cases) == 15
    assert len(report.suite_digest) == 64
