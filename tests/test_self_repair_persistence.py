from __future__ import annotations

from dataclasses import replace

import pytest

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


def _attempt(
    incident_id: str,
    *,
    attempt_id: str = "attempt-1",
    attempt_number: int = 1,
    started_at_epoch: float = 102,
) -> RepairAttempt:
    trigger = RepairTrigger.create(
        trigger_id=f"trigger-{attempt_number}",
        component_id="runtime.voice",
        reason_code="child_exited",
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=(f"crash:fingerprint:{attempt_number}",),
        observed_at_epoch=101,
    )
    policy = _policy()
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=started_at_epoch,
        action_id=f"action-{attempt_number}",
    )
    return RepairAttempt.start(
        incident_id=incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=attempt_number,
        now_epoch=started_at_epoch,
        attempt_id=attempt_id,
    )


def _verification(
    status: RepairVerificationStatus,
    *,
    summary: str,
    now_epoch: float,
) -> RepairVerificationResult:
    return RepairVerificationResult.create(
        verifier_id="test-verifier",
        verifier_version=1,
        contract_id=_policy().verification_contract,
        status=status,
        summary=summary,
        evidence_references=("test:verification",),
        observed_at_epoch=now_epoch,
    )


def test_repair_attempt_persists_completion_with_canonical_incident(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100,
    )
    attempt = _attempt(incident.incident_id)

    service.record_repair_attempt(attempt)
    assert service.get_repair_attempt(attempt.attempt_id) == attempt

    completed = attempt.complete(
        execution_result="same revision child restarted",
        verification=_verification(
            RepairVerificationStatus.PASS,
            summary="readiness and liveness stable",
            now_epoch=110,
        ),
        post_repair_evidence=("health:runtime.voice:healthy",),
        now_epoch=110,
    )
    service.record_repair_attempt(completed)
    assert service.get_repair_attempt(attempt.attempt_id) == completed
    store.close()

    reopened = SqliteIncidentStore(path)
    reopened_service = IncidentService(reopened)
    assert reopened_service.get_repair_attempt(attempt.attempt_id) == completed
    assert reopened_service.list_repair_attempts(incident.incident_id) == (completed,)
    reopened.close()


def test_repair_attempt_requires_existing_incident(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    attempt = _attempt("missing-incident")

    with pytest.raises(KeyError, match="unknown incident"):
        service.record_repair_attempt(attempt)

    store.close()


def test_completed_repair_attempt_cannot_be_overwritten_by_stale_state(
    tmp_path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100,
    )
    started = _attempt(incident.incident_id)
    completed = started.complete(
        execution_result="child restarted",
        verification=_verification(
            RepairVerificationStatus.FAIL,
            summary="readiness failed",
            now_epoch=110,
        ),
        next_retry_eligible_epoch=120,
        now_epoch=110,
    )
    service.record_repair_attempt(completed)

    with pytest.raises(
        ValueError,
        match="completed repair attempt cannot be overwritten",
    ):
        service.record_repair_attempt(started)

    assert service.get_repair_attempt(started.attempt_id) == completed
    store.close()


def test_repair_attempt_identity_cannot_be_reparented(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    first = service.create_manual(
        symptom="first incident",
        affected_components=("runtime.voice",),
        now_epoch=100,
    )
    second = service.create_manual(
        symptom="second incident",
        affected_components=("runtime.voice",),
        now_epoch=101,
    )
    attempt = _attempt(first.incident_id)
    service.record_repair_attempt(attempt)

    with pytest.raises(ValueError, match="identity cannot change"):
        service.record_repair_attempt(replace(attempt, incident_id=second.incident_id))

    assert service.get_repair_attempt(attempt.attempt_id) == attempt
    store.close()


def test_repair_attempt_listing_is_bounded_and_attempt_ordered(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime crash loop",
        affected_components=("runtime.voice",),
        now_epoch=100,
    )
    second = _attempt(
        incident.incident_id,
        attempt_id="attempt-2",
        attempt_number=2,
        started_at_epoch=104,
    )
    first = _attempt(
        incident.incident_id,
        attempt_id="attempt-1",
        attempt_number=1,
        started_at_epoch=102,
    )
    service.record_repair_attempt(second)
    service.record_repair_attempt(first)

    assert service.list_repair_attempts(incident.incident_id) == (first, second)
    assert service.list_repair_attempts(incident.incident_id, limit=1) == (second,)
    assert service.list_repair_attempts(incident.incident_id, limit=0) == ()
    store.close()
