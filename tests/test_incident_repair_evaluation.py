from __future__ import annotations

from jarvis.incident_repair.evaluation import run_replay_suite


def test_phase6_replay_suite_covers_all_approved_cases(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "phase6-replay")

    failures = {
        item.case_id: item.evidence
        for item in report.cases
        if not item.passed
    }
    assert failures == {}
    assert report.status == "PASS"
    assert len(report.cases) == 15
    assert [item.case_id for item in report.cases] == [
        "01_local_defect_repaired",
        "02_inconclusive",
        "03_wrong_first_hypothesis",
        "04_knowledge_advisory_only",
        "05_provider_pressure",
        "06_restart_during_diagnostics",
        "07_restart_after_approval",
        "08_restart_during_development",
        "09_failed_candidate_tests",
        "10_protected_surface",
        "11_secret_evidence_negative_control",
        "12_known_repair_priority",
        "13_duplicate_trigger_idempotency",
        "14_protected_main_unchanged",
        "15_candidate_exact_digest",
    ]
    assert len(report.suite_digest) == 64
