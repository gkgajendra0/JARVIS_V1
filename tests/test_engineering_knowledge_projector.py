from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from jarvis.engineering_knowledge import (
    ApplicabilityMatcherRegistry,
    EngineeringKnowledgePersistenceConflictError,
    RepairKnowledgeProjectionError,
    RepairKnowledgeProjector,
    build_default_facet_registry,
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


def _started_attempt(
    incident_id: str,
    *,
    attempt_id: str = "attempt-verified-1",
) -> RepairAttempt:
    trigger = RepairTrigger.create(
        trigger_id="trigger-verified-1",
        component_id="runtime.voice",
        reason_code="child_exited",
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=("crash_fingerprint:abc123",),
        observed_at_epoch=101.0,
    )
    policy = _policy()
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=102.0,
        action_id="action-verified-1",
    )
    return RepairAttempt.start(
        incident_id=incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=102.0,
        attempt_id=attempt_id,
    )


def _completed_attempt(
    incident_id: str,
    *,
    status: RepairVerificationStatus = RepairVerificationStatus.PASS,
    attempt_id: str = "attempt-verified-1",
) -> RepairAttempt:
    started = _started_attempt(incident_id, attempt_id=attempt_id)
    verification = RepairVerificationResult.create(
        verifier_id="external_runtime_supervisor",
        verifier_version=1,
        contract_id=_policy().verification_contract,
        status=status,
        summary=(
            "readiness_and_liveness_stable:6_probes"
            if status is RepairVerificationStatus.PASS
            else "readiness_not_stable"
        ),
        evidence_references=("health:runtime.voice:healthy",),
        observed_at_epoch=110.0,
    )
    return started.complete(
        execution_result="same-version child restart stabilized",
        verification=verification,
        post_repair_evidence=("health:runtime.voice:healthy",),
        next_retry_eligible_epoch=112.0,
        now_epoch=110.0,
    )


def _persist_attempt(
    store: SqliteIncidentStore,
    *,
    status: RepairVerificationStatus = RepairVerificationStatus.PASS,
) -> RepairAttempt:
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    attempt = _completed_attempt(incident.incident_id, status=status)
    service.record_repair_attempt(attempt)
    return attempt


def test_verified_repair_projects_one_provenance_linked_candidate(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    attempt = _persist_attempt(store)

    result = RepairKnowledgeProjector().project_attempt(store, attempt.attempt_id)

    assert result.created is True
    assert result.source_attempt_id == attempt.attempt_id
    assert result.source_incident_id == attempt.incident_id

    facets = store.list_engineering_knowledge_facets(result.revision_id)
    assert len(facets) == 1

    matcher_registry = ApplicabilityMatcherRegistry()
    matcher_registry.register(
        target_namespace="jarvis.component",
        matcher_type="exact",
    )
    validated = build_default_facet_registry().validate_for_decision(
        facets[0],
        applicability_registry=matcher_registry,
    )
    assert validated.payload["component_id"] == "runtime.voice"
    assert validated.payload["verification"] == {
        "contract_id": "runtime_ready_and_live",
        "verdict": "recovered",
    }

    store.close()

    connection = sqlite3.connect(path)
    try:
        state = connection.execute(
            """
            SELECT lifecycle_state
            FROM engineering_knowledge_revision_state
            WHERE revision_id = ?
            """,
            (result.revision_id,),
        ).fetchone()
        assert state == ("candidate",)

        references = {
            row[0]
            for row in connection.execute(
                """
                SELECT evidence.canonical_reference
                FROM engineering_evidence AS evidence
                JOIN engineering_knowledge_evidence_link AS link
                  ON link.evidence_id = evidence.evidence_id
                WHERE link.revision_id = ?
                """,
                (result.revision_id,),
            ).fetchall()
        }
        assert references == {
            f"incident:{attempt.incident_id}",
            f"repair-attempt:{attempt.attempt_id}",
            f"repair-trigger:{attempt.trigger_id}",
            f"repair-policy:{attempt.policy_id}:v{attempt.policy_version}",
            f"repair-verification:{attempt.attempt_id}",
        }

        relation_counts = dict(
            connection.execute(
                """
                SELECT relation_type, COUNT(*)
                FROM engineering_knowledge_evidence_link
                WHERE revision_id = ?
                GROUP BY relation_type
                """,
                (result.revision_id,),
            ).fetchall()
        )
        assert relation_counts == {"derived_from": 4, "verified_by": 1}

        attestation = connection.execute(
            """
            SELECT subject_id, verdict, producer
            FROM engineering_attestation
            WHERE subject_id = ?
            """,
            (result.revision_id,),
        ).fetchone()
        assert attestation == (
            result.revision_id,
            "pass",
            "external_runtime_supervisor:v1",
        )
    finally:
        connection.close()


def test_repair_projection_is_idempotent_for_same_attempt(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    attempt = _persist_attempt(store)
    projector = RepairKnowledgeProjector()

    first = projector.project_attempt(store, attempt.attempt_id)
    second = projector.project_attempt(store, attempt.attempt_id)

    assert first.created is True
    assert second.created is False
    assert second.knowledge_id == first.knowledge_id
    assert second.revision_id == first.revision_id

    store.close()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_knowledge_identity"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_knowledge_revision"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_knowledge_facet"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_evidence"
        ).fetchone() == (5,)
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_knowledge_lifecycle_event"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_attestation"
        ).fetchone() == (1,)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "status",
    [
        RepairVerificationStatus.FAIL,
        RepairVerificationStatus.INCONCLUSIVE,
    ],
)
def test_failed_or_inconclusive_repair_does_not_project(
    tmp_path,
    status: RepairVerificationStatus,
) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    attempt = _persist_attempt(store, status=status)

    with pytest.raises(
        RepairKnowledgeProjectionError,
        match="only RECOVERED repair attempts",
    ):
        RepairKnowledgeProjector().project_attempt(store, attempt.attempt_id)

    store.close()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM engineering_knowledge_revision"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_projection_requires_immutable_trigger_and_policy_provenance(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    completed = _completed_attempt(incident.incident_id)
    legacy_like = replace(completed, trigger_snapshot=None)
    service.record_repair_attempt(legacy_like)

    with pytest.raises(
        RepairKnowledgeProjectionError,
        match="no immutable trigger snapshot",
    ):
        RepairKnowledgeProjector().project_attempt(
            store,
            legacy_like.attempt_id,
        )

    store.close()


def test_projection_is_stable_if_mutable_incident_metadata_changes(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    attempt = _completed_attempt(incident.incident_id)
    service.record_repair_attempt(attempt)

    projector = RepairKnowledgeProjector()
    first = projector.project_attempt(store, attempt.attempt_id)

    resolved = incident.resolve(
        root_cause="runtime process exited",
        accepted_fix="bounded same-version restart",
        regression_tests=("runtime_ready_and_live",),
        now_epoch=120.0,
    )
    store.upsert(resolved)

    replay = projector.project_attempt(store, attempt.attempt_id)
    assert replay.created is False
    assert replay.knowledge_id == first.knowledge_id
    assert replay.revision_id == first.revision_id
    store.close()


def test_atomic_persistence_rejects_same_identity_with_different_content(
    tmp_path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    incident = service.create_manual(
        symptom="runtime child exited unexpectedly",
        affected_components=("runtime.voice",),
        now_epoch=100.0,
    )
    attempt = _completed_attempt(incident.incident_id)
    service.record_repair_attempt(attempt)

    projector = RepairKnowledgeProjector()
    candidate = projector.build_candidate(incident=incident, attempt=attempt)
    first = store.persist_engineering_knowledge_candidate(candidate)
    assert first.created is True

    changed_revision = replace(
        candidate.revision,
        normalized_summary="conflicting deterministic content",
    )
    conflicting = replace(candidate, revision=changed_revision)

    with pytest.raises(
        EngineeringKnowledgePersistenceConflictError,
        match="different content",
    ):
        store.persist_engineering_knowledge_candidate(conflicting)

    store.close()
