from __future__ import annotations

from jarvis.capability_registry.evaluation import run_replay_suite


_EXPECTED_CASES = [
    "01_package_schema_validation",
    "02_strict_semver",
    "03_same_version_changed_digest_rejected",
    "04_unknown_manifest_version_rejected",
    "05_manifest_digest_mismatch_rejected",
    "06_untrusted_provider_rejected",
    "07_raw_execution_fields_impossible",
    "08_corrupt_artifact_blocked",
    "09_runtime_api_mismatch_blocked",
    "10_platform_mismatch_blocked",
    "11_registration_does_not_enable",
    "12_enable_requires_ready",
    "13_stale_generation_rejected",
    "14_one_selected_version",
    "15_disable_removes_routing",
    "16_disable_does_not_claim_unload",
    "17_new_version_no_auto_switch",
    "18_version_switch_exact_event",
    "19_supported_rollback_succeeds",
    "20_absent_old_descriptor_rollback_blocked",
    "21_retired_cannot_select",
    "22_quarantined_cannot_select",
    "23_failed_health_blocks",
    "24_desired_and_effective_distinct",
    "25_registry_restart_survives",
    "26_newer_schema_fails_closed",
    "27_untrusted_entrypoint_cannot_execute",
    "28_artifact_retention",
    "29_core_pinned_unaffected",
    "30_prior_governance_regressions",
    "31_disable_commit_no_stale_route",
    "32_version_switch_no_stale_generation",
    "33_reconciler_idempotent",
    "34_crash_after_commit_recovers",
    "35_cas_event_atomic",
    "36_reconciler_no_authority_or_intent_write",
    "37_dbos_not_registry_truth",
    "38_concurrent_mutation_one_winner",
    "39_stale_projection_fails_closed",
    "40_corrupt_selected_no_fallback",
    "41_release_sha_change_invalidates",
    "42_metadata_cannot_choose_execution_model",
    "43_core_pinned_ignores_managed_fence",
    "44_registry_file_restart_handle",
    "45_quarantine_removes_routing_preserves_intent",
]


def test_phase8_replay_suite_covers_complete_approved_matrix(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "phase8-replay")

    failures = {item.case_id: item.evidence for item in report.cases if not item.passed}
    assert failures == {}
    assert report.status == "PASS"
    assert [item.case_id for item in report.cases] == _EXPECTED_CASES
    assert len(report.cases) == 45
    assert len(report.suite_digest) == 64
