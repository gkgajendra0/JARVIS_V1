from __future__ import annotations

from jarvis.promotion.evaluation import run_replay_suite


def test_phase7_replay_suite_covers_governed_promotion_failures(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "phase7-replay")

    failures = {item.case_id: item.evidence for item in report.cases if not item.passed}
    assert failures == {}
    assert report.status == "PASS"
    assert [item.case_id for item in report.cases] == [
        "01_exact_candidate_attempt",
        "02_stale_candidate_fails_closed",
        "03_moved_pr_head_rejected",
        "04_wrong_ci_app_rejected",
        "05_skipped_windows_rejected",
        "06_exact_authorized_merge",
        "07_external_merge_reconciled",
        "08_full_success_closes",
        "09_external_failure_does_not_rollback",
        "10_candidate_failure_rolls_back_lkg",
        "11_high_risk_compatibility_blocked",
        "12_control_surfaces_protected",
        "13_unknown_failure_blocks_close",
        "14_deployment_resume_idempotent",
    ]
    assert len(report.suite_digest) == 64
