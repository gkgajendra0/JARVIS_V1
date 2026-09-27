from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.capability_acquisition.evaluation import (
    RealCapabilityEvidenceError,
    build_real_capability_evidence,
    run_replay_suite,
    validate_real_capability_evidence,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.verification import (
    CapabilityCandidateError,
    ensure_capability_substrate_requirements_current,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.models import ChangeArtifact
from jarvis.work.store import SQLiteWorkStore


def _real_payload(commit: str) -> dict[str, object]:
    return build_real_capability_evidence(
        tested_commit=commit,
        change_id="change_real_phase9",
        acquisition_work_id="work_acquisition",
        development_work_id="work_development",
        goal_digest="1" * 64,
        plan_digest="2" * 64,
        architecture_digest="3" * 64,
        candidate_digest="4" * 64,
        capability_id="tv.control",
        package_id="tv.control.package",
        package_version="1.0.0",
        package_digest="5" * 64,
        promotion_attempt_id="promotion_phase9",
        active_release_sha="6" * 40,
        lifecycle_evidence_ref="lifecycle:event:1",
        operation="power",
        target="living-room-tv",
        observed_effect="TV power state changed",
        observation_method="owner_observed",
        production_observation_ref="observation:phase9:1",
        rollback_disable_evidence_ref="rollback:phase9:1",
        recorded_at="2026-09-27T16:30:00+00:00",
        owner_confirmed=True,
        production_observed=True,
        rollback_disable_verified=True,
    )


def test_phase9_replay_has_all_24_required_cases(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "replay")

    assert report.status == "PASS"
    assert len(report.cases) == 24
    assert all(case.passed for case in report.cases)
    assert len(report.suite_digest) == 64
    assert tuple(case.case_id for case in report.cases) == (
        "01_existing_capability_no_build",
        "02_disabled_package_lifecycle_reuse",
        "03_duplicate_candidates_deduplicate",
        "04_stronger_verified_evidence_wins",
        "05_wrap_beats_generate_custom",
        "06_unverified_source_not_selected",
        "07_no_candidate_no_safe_route",
        "08_stale_candidate_invalidates_plan",
        "09_restart_during_acquisition_research",
        "10_provider_pressure_waiting_resource",
        "11_owner_pairing_waiting_for_owner",
        "12_architecture_approval_exact_plan_digest",
        "13_architecture_revision_invalidates_approval",
        "14_development_blocked_before_approval",
        "15_dependency_provenance_failure_blocks",
        "16_plaintext_secret_injection_rejected",
        "17_external_metadata_cannot_execute",
        "18_protected_surface_fails_closed",
        "19_package_registration_no_auto_enable",
        "20_package_compatibility_failure_unavailable",
        "21_protected_main_only_phase7",
        "22_rollback_disable_restores_safe_state",
        "23_real_external_owner_evidence_required",
        "24_cold_restart_preserves_identity",
    )


def test_real_capability_evidence_binds_exact_commit_and_digest() -> None:
    commit = "a" * 40
    payload = _real_payload(commit)

    validated = validate_real_capability_evidence(payload, tested_commit=commit)

    assert validated["tested_commit"] == commit
    assert validated["owner_confirmed"] is True
    assert validated["production_observed"] is True
    assert validated["rollback_disable_verified"] is True
    assert len(str(validated["evidence_digest"])) == 64


def test_real_capability_evidence_rejects_wrong_tested_commit() -> None:
    payload = _real_payload("a" * 40)

    with pytest.raises(RealCapabilityEvidenceError, match="tested commit"):
        validate_real_capability_evidence(payload, tested_commit="b" * 40)


def test_real_capability_evidence_cannot_self_approve_effect() -> None:
    payload = _real_payload("a" * 40)
    payload["owner_confirmed"] = False

    with pytest.raises(RealCapabilityEvidenceError, match="owner confirmation"):
        validate_real_capability_evidence(payload, tested_commit="a" * 40)


def test_real_capability_evidence_digest_tampering_fails_closed() -> None:
    payload = _real_payload("a" * 40)
    payload["observed_effect"] = "different effect"

    with pytest.raises(RealCapabilityEvidenceError, match="digest mismatch"):
        validate_real_capability_evidence(payload, tested_commit="a" * 40)


def test_declared_dependency_requires_phase5_substrate_evidence(tmp_path) -> None:
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    change = store.create(
        request="dependency-backed capability",
        process_key="engineering.change",
        process_version=1,
        source_session_id="phase9-test",
        source_turn_id="dependency",
    )
    architecture = ChangeArtifact(
        artifact_id="artifact_dependency",
        change_id=change.change_id,
        kind="architecture",
        revision=1,
        digest="d" * 64,
        payload={
            "dependency_refs": ["vendor-sdk==1.0.0"],
            "secret_scopes": [],
            "discovery_scopes": [],
        },
        created_at="2026-09-27T00:00:00+00:00",
    )

    with pytest.raises(CapabilityCandidateError) as error:
        ensure_capability_substrate_requirements_current(
            store,
            change.change_id,
            architecture,
        )

    assert error.value.reason_code == "substrate_manifest_missing"


def test_plaintext_secret_is_not_a_phase9_candidate_field() -> None:
    with pytest.raises(TypeError):
        AcquisitionCandidateV1.create(
            source_kind=AcquisitionSourceKind.MCP,
            source_identity="mcp:tv",
            source_digest="e" * 64,
            trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
            supported_operations=("power",),
            strategy=AcquisitionStrategy.WRAP,
            evidence_refs=("vendor:mcp",),
            verification_requirements=("mcp-contract",),
            secret_value="plaintext",
        )


def test_plan_tampering_still_invalidates_digest() -> None:
    goal = OwnerCapabilityGoalV1.create(
        request="Acquire TV capability",
        requested_capability="TV control",
        required_operations=("power",),
        source_session_id="s",
        source_turn_id="t",
        now_epoch=1.0,
    )
    candidate = AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity="mcp:tv",
        source_digest="f" * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        supported_operations=("power",),
        strategy=AcquisitionStrategy.WRAP,
        evidence_refs=("vendor:mcp",),
        verification_requirements=("mcp-contract",),
    )
    evaluation = AcquisitionCandidateEvaluationV1.create(
        candidate,
        requested_operations=("power",),
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )
    plan = CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id="tv.control",
        proposed_package_id="tv.control.package",
        proposed_package_version="1.0.0",
        rollback_summary="Disable.",
        changed_paths=("src/jarvis/tv.py",),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("tv.verify.v1",),
        development_test_targets=("tests/test_tv.py",),
        evidence_refs=("vendor:mcp",),
    )

    with pytest.raises(ValueError, match="digest mismatch"):
        replace(plan, candidate_digest="0" * 64)
