from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.engineering_knowledge import (
    EngineeringKnowledgeCandidateBundle,
    KnowledgeLifecycleError,
    KnowledgeLifecycleService,
    KnowledgeLifecycleState,
    KnowledgePromotionError,
    RepairKnowledgeProjector,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_model import HealthState
from jarvis.self_repair import (
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
    RepairVerificationResult,
    RepairVerificationStatus,
)


def _policy() -> RepairPolicy:
    return RepairPolicy(
        policy_id="runtime-child-exit-v1",
        version=1,
        trigger_source="dev_supervisor",
        component_id="runtime.voice",
        reason_code="child_exited",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision", "restart_budget_available"),
        max_attempts=3,
        rolling_window_seconds=300,
        cooldown_seconds=2,
        backoff_multiplier=2,
        verification_contract="runtime_ready_and_live",
        health_states=(HealthState.FAILED,),
        reversible=True,
        automatic=True,
    )


def _persist_verified_candidate(
    store: SqliteIncidentStore,
) -> tuple[str, EngineeringKnowledgeCandidateBundle]:
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    trigger = RepairTrigger.create(
        trigger_id="trigger-lifecycle-1",
        component_id="runtime.voice",
        reason_code="child_exited",
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=("crash_fingerprint:lifecycle",),
        observed_at_epoch=101.0,
    )
    policy = _policy()
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=102.0,
        action_id="action-lifecycle-1",
    )
    attempt = RepairAttempt.start(
        incident_id=incident.incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=102.0,
        attempt_id="attempt-lifecycle-1",
    )
    verification = RepairVerificationResult.create(
        verifier_id="external_runtime_supervisor",
        verifier_version=1,
        contract_id=policy.verification_contract,
        status=RepairVerificationStatus.PASS,
        summary="readiness_and_liveness_stable:6_probes",
        evidence_references=("health:runtime.voice:healthy",),
        observed_at_epoch=110.0,
    )
    completed = attempt.complete(
        execution_result="same-version child restart stabilized",
        verification=verification,
        post_repair_evidence=("health:runtime.voice:healthy",),
        now_epoch=110.0,
    )
    service.record_repair_attempt(completed)

    projector = RepairKnowledgeProjector()
    candidate = projector.build_candidate(incident=incident, attempt=completed)
    result = store.persist_engineering_knowledge_candidate(candidate)
    assert result.created is True
    return result.revision_id, candidate


def test_verified_repair_promotes_candidate_to_accepted(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    revision_id, _ = _persist_verified_candidate(store)
    lifecycle = KnowledgeLifecycleService(store)

    staged, accepted = lifecycle.promote_verified_repair(
        revision_id,
        staged_at_epoch=120.0,
        accepted_at_epoch=121.0,
    )

    assert staged.created is True
    assert staged.from_state is KnowledgeLifecycleState.CANDIDATE
    assert staged.to_state is KnowledgeLifecycleState.STAGED
    assert accepted.created is True
    assert accepted.from_state is KnowledgeLifecycleState.STAGED
    assert accepted.to_state is KnowledgeLifecycleState.ACCEPTED
    assert (
        store.get_engineering_knowledge_lifecycle_state(revision_id)
        is KnowledgeLifecycleState.ACCEPTED
    )
    store.close()


def test_repair_promotion_is_idempotent_after_acceptance(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    revision_id, _ = _persist_verified_candidate(store)
    lifecycle = KnowledgeLifecycleService(store)

    lifecycle.promote_verified_repair(
        revision_id,
        staged_at_epoch=120.0,
        accepted_at_epoch=121.0,
    )
    staged, accepted = lifecycle.promote_verified_repair(
        revision_id,
        staged_at_epoch=130.0,
        accepted_at_epoch=131.0,
    )

    assert staged.created is False
    assert accepted.created is False
    assert (
        store.get_engineering_knowledge_lifecycle_state(revision_id)
        is KnowledgeLifecycleState.ACCEPTED
    )
    store.close()


def test_missing_passing_attestation_blocks_staging(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    trigger = RepairTrigger.create(
        trigger_id="trigger-no-attestation",
        component_id="runtime.voice",
        reason_code="child_exited",
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        observed_at_epoch=101.0,
    )
    policy = _policy()
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=102.0,
        action_id="action-no-attestation",
    )
    started = RepairAttempt.start(
        incident_id=incident.incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=102.0,
        attempt_id="attempt-no-attestation",
    )
    verification = RepairVerificationResult.create(
        verifier_id="external_runtime_supervisor",
        verifier_version=1,
        contract_id=policy.verification_contract,
        status=RepairVerificationStatus.PASS,
        summary="stable",
        observed_at_epoch=110.0,
    )
    completed = started.complete(
        execution_result="restart stabilized",
        verification=verification,
        now_epoch=110.0,
    )
    service.record_repair_attempt(completed)
    projector = RepairKnowledgeProjector()
    candidate = projector.build_candidate(incident=incident, attempt=completed)
    without_attestation = replace(candidate, attestations=())
    write = store.persist_engineering_knowledge_candidate(without_attestation)

    with pytest.raises(
        KnowledgePromotionError,
        match="missing_unique_passing_repair_attestation",
    ):
        KnowledgeLifecycleService(store).stage_verified_repair(
            write.revision_id,
            now_epoch=120.0,
        )

    assert (
        store.get_engineering_knowledge_lifecycle_state(write.revision_id)
        is KnowledgeLifecycleState.CANDIDATE
    )
    store.close()


def test_rejected_knowledge_cannot_be_promoted(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    revision_id, candidate = _persist_verified_candidate(store)
    lifecycle = KnowledgeLifecycleService(store)

    evidence_ids = tuple(item.evidence_id for item in candidate.evidence)
    rejected = lifecycle.reject(
        revision_id,
        reason_code="manual_review_rejected",
        actor="test",
        evidence_ids=evidence_ids,
        now_epoch=120.0,
    )
    assert rejected.to_state is KnowledgeLifecycleState.REJECTED

    with pytest.raises(KnowledgeLifecycleError, match="cannot promote"):
        lifecycle.promote_verified_repair(
            revision_id,
            staged_at_epoch=130.0,
            accepted_at_epoch=131.0,
        )
    store.close()


def test_accepted_knowledge_can_be_retired_but_not_restaged(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    revision_id, candidate = _persist_verified_candidate(store)
    lifecycle = KnowledgeLifecycleService(store)
    lifecycle.promote_verified_repair(
        revision_id,
        staged_at_epoch=120.0,
        accepted_at_epoch=121.0,
    )

    retired = lifecycle.retire(
        revision_id,
        reason_code="revalidation_required",
        actor="test",
        evidence_ids=(candidate.evidence[-1].evidence_id,),
        now_epoch=130.0,
    )
    assert retired.to_state is KnowledgeLifecycleState.RETIRED

    with pytest.raises(KnowledgeLifecycleError, match="cannot stage"):
        lifecycle.stage_verified_repair(revision_id, now_epoch=140.0)
    store.close()


def test_model_confidence_is_not_part_of_repair_promotion_contract(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    revision_id, _ = _persist_verified_candidate(store)

    staged, accepted = KnowledgeLifecycleService(store).promote_verified_repair(
        revision_id,
        staged_at_epoch=120.0,
        accepted_at_epoch=121.0,
    )

    assert staged.created is True
    assert accepted.created is True
    store.close()
