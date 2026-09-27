from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.capability_acquisition import (
    OWNER_CAPABILITY_ACQUISITION_PROCESS,
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionDisposition,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.engineering_change import ChangeStore, UnsupportedProcess
from jarvis.engineering_change.models import ProcessStageRole
from jarvis.work.models import WorkType
from jarvis.work.store import SQLiteWorkStore


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="JARVIS, get TV control capability",
        requested_capability="TV control",
        required_operations=("power", "volume"),
        target_hints=("living-room", "hisense"),
        source_session_id="session-1",
        source_turn_id="turn-1",
        now_epoch=1000.0,
    )


def _candidate(
    *,
    operations: tuple[str, ...] = ("power", "volume"),
    trust: AcquisitionTrustClass = AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
    source_digest: str | None = "a" * 64,
    strategy: AcquisitionStrategy = AcquisitionStrategy.WRAP,
) -> AcquisitionCandidateV1:
    return AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity="https://example.test/mcp",
        source_version="2026-09",
        source_digest=source_digest,
        trust_class=trust,
        supported_operations=operations,
        evidence_refs=("registry:example", "docs:vendor"),
        strategy=strategy,
        verification_requirements=("contract-test",),
        dependency_refs=("mcp-python-sdk==2",),
        secret_scopes=("tv.remote",),
        network_scopes=("https://example.test",),
        provenance_refs=("vendor-docs",),
        external_acceptance_requirements=("verify-tv-state",),
    )


def _evaluation(
    candidate: AcquisitionCandidateV1,
) -> AcquisitionCandidateEvaluationV1:
    return AcquisitionCandidateEvaluationV1.create(
        candidate,
        requested_operations=_goal().required_operations,
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )


def test_goal_digest_is_stable_under_unordered_semantic_inputs() -> None:
    first = _goal()
    second = OwnerCapabilityGoalV1.create(
        request=first.request,
        requested_capability=first.requested_capability,
        required_operations=("volume", "power"),
        target_hints=("hisense", "living-room"),
        source_session_id=first.source_session_id,
        source_turn_id=first.source_turn_id,
        now_epoch=first.created_at_epoch,
    )

    assert first.canonical_payload() == second.canonical_payload()
    assert first.digest == second.digest
    assert first.goal_id == second.goal_id


def test_goal_rejects_duplicate_operations() -> None:
    with pytest.raises(ValueError, match="unique"):
        OwnerCapabilityGoalV1.create(
            request="Acquire capability",
            requested_capability="TV",
            required_operations=("power", "power"),
            source_session_id="s",
            source_turn_id="t",
            now_epoch=1.0,
        )


def test_verified_candidate_requires_exact_source_digest() -> None:
    with pytest.raises(ValueError, match="source_digest"):
        _candidate(source_digest=None)

    unverified = _candidate(
        trust=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        source_digest=None,
    )
    assert unverified.source_digest is None


def test_candidate_digest_is_stable_under_nonsemantic_order() -> None:
    first = _candidate()
    second = AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity=first.source_identity,
        source_version=first.source_version,
        source_digest=first.source_digest,
        trust_class=first.trust_class,
        supported_operations=("volume", "power"),
        strategy=first.strategy,
        evidence_refs=("docs:vendor", "registry:example"),
        verification_requirements=("contract-test",),
        dependency_refs=("mcp-python-sdk==2",),
        secret_scopes=("tv.remote",),
        network_scopes=("https://example.test",),
        provenance_refs=("vendor-docs",),
        external_acceptance_requirements=("verify-tv-state",),
    )

    assert first.canonical_payload() == second.canonical_payload()
    assert first.digest == second.digest
    assert first.candidate_id == second.candidate_id


def test_evaluation_is_deterministically_blocked_when_operation_is_missing() -> None:
    candidate = _candidate(operations=("power",))
    evaluation = AcquisitionCandidateEvaluationV1.create(
        candidate,
        requested_operations=("power", "volume"),
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )

    assert evaluation.disposition is AcquisitionDisposition.BLOCKED
    assert evaluation.covered_operations == ("power",)
    assert evaluation.missing_operations == ("volume",)
    assert "missing_required_operations" in evaluation.reason_codes


@pytest.mark.parametrize(
    ("evidence", "trust", "requirements", "reason"),
    [
        (False, True, True, "evidence_incomplete"),
        (True, False, True, "trust_not_allowed"),
        (True, True, False, "requirements_incompatible"),
    ],
)
def test_evaluation_cannot_select_when_policy_fact_fails(
    evidence: bool,
    trust: bool,
    requirements: bool,
    reason: str,
) -> None:
    evaluation = AcquisitionCandidateEvaluationV1.create(
        _candidate(),
        requested_operations=("power", "volume"),
        evidence_complete=evidence,
        trust_allowed=trust,
        requirements_compatible=requirements,
    )

    assert evaluation.disposition is AcquisitionDisposition.BLOCKED
    assert reason in evaluation.reason_codes


def test_evaluation_rejects_truthy_non_boolean_policy_values() -> None:
    with pytest.raises(TypeError, match="evidence_complete"):
        AcquisitionCandidateEvaluationV1.create(
            _candidate(),
            requested_operations=("power", "volume"),
            evidence_complete=1,
            trust_allowed=True,
            requirements_compatible=True,
        )


def test_selectable_candidate_produces_digest_bound_plan() -> None:
    goal = _goal()
    candidate = _candidate()
    evaluation = _evaluation(candidate)

    plan = CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id="Device.TV.Control",
        proposed_package_id="Device.TV.Control.MCP",
        proposed_package_version="1.0.0",
        rollback_summary="Disable package and restore prior selected version.",
        changed_components=("capability-provider",),
        changed_paths=("src/jarvis/tv/provider.py",),
        dependency_refs=("mcp-python-sdk==2",),
        secret_scopes=("tv.remote",),
        sandbox_profile_ids=("network-bounded",),
        network_scopes=("https://example.test",),
        device_scopes=("device:living-room-tv",),
        verification_contract_ids=("tv-contract-v1",),
        owner_acceptance_contract_ids=("tv-physical-v1",),
        evidence_refs=("registry:example", "docs:vendor"),
    )

    assert plan.goal_digest == goal.digest
    assert plan.candidate_digest == candidate.digest
    assert plan.evaluation_digest == evaluation.digest
    assert plan.strategy is AcquisitionStrategy.WRAP
    assert plan.proposed_capability_id == "device.tv.control"
    assert plan.proposed_package_id == "device.tv.control.mcp"
    assert plan.device_scopes == ("device:living-room-tv",)
    assert len(plan.digest) == 64


def test_blocked_candidate_cannot_produce_plan() -> None:
    goal = _goal()
    candidate = _candidate(operations=("power",))
    evaluation = AcquisitionCandidateEvaluationV1.create(
        candidate,
        requested_operations=goal.required_operations,
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )

    with pytest.raises(ValueError, match="blocked"):
        CapabilityAcquisitionPlanV1.create(
            goal,
            candidate,
            evaluation,
            proposed_capability_id="tv",
            proposed_package_id="tv.mcp",
            proposed_package_version="1.0.0",
            rollback_summary="Disable.",
            verification_contract_ids=("tv-contract-v1",),
            evidence_refs=("registry:example",),
        )


def test_plan_rejects_invalid_semver_and_missing_verification() -> None:
    goal = _goal()
    candidate = _candidate()
    evaluation = _evaluation(candidate)

    with pytest.raises(ValueError):
        CapabilityAcquisitionPlanV1.create(
            goal,
            candidate,
            evaluation,
            proposed_capability_id="tv",
            proposed_package_id="tv.mcp",
            proposed_package_version="v1",
            rollback_summary="Disable.",
            verification_contract_ids=("tv-contract-v1",),
            evidence_refs=("registry:example",),
        )

    with pytest.raises(ValueError, match="verification_contract_id"):
        CapabilityAcquisitionPlanV1.create(
            goal,
            candidate,
            evaluation,
            proposed_capability_id="tv",
            proposed_package_id="tv.mcp",
            proposed_package_version="1.0.0",
            rollback_summary="Disable.",
            evidence_refs=("registry:example",),
        )


def test_contract_digest_tampering_fails_closed() -> None:
    goal = _goal()
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(goal, request="changed")


def test_phase9_process_reuses_research_and_development_roles() -> None:
    process = OWNER_CAPABILITY_ACQUISITION_PROCESS

    assert process.key == "owner_capability_acquisition"
    assert process.version == 1
    assert process.architecture_source_stage.stage_key == "acquisition"
    assert process.architecture_source_stage.work_type is WorkType.RESEARCH
    assert (
        process.architecture_source_stage.role is ProcessStageRole.ARCHITECTURE_SOURCE
    )
    assert process.development_stage.stage_key == "development"
    assert process.development_stage.work_type is WorkType.DEVELOPMENT
    assert process.development_stage.role is ProcessStageRole.DEVELOPMENT


def test_process_registration_is_restart_fail_closed(tmp_path) -> None:
    path = tmp_path / "work.sqlite3"
    store = ChangeStore(
        SQLiteWorkStore(path),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = store.create(
        request="Acquire TV control",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="s",
        source_turn_id="t",
    )
    assert store.require(change.change_id) == change

    without_phase9 = ChangeStore(SQLiteWorkStore(path))
    with pytest.raises(UnsupportedProcess):
        without_phase9.require(change.change_id)
