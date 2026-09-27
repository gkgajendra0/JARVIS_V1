from __future__ import annotations

import pytest

from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.incident_repair import (
    UNKNOWN_INCIDENT_REPAIR_PROCESS,
    IncidentRepairAdmissionBlocked,
    IncidentRepairCoordinator,
    IncidentRepairTrigger,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.incidents.models import EvidenceReference, IncidentStatus
from jarvis.self_model.health import HealthState
from jarvis.self_repair.domain import (
    RepairActionKind,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
)
from jarvis.self_repair.registry import RepairRegistry
from jarvis.work.models import WorkType
from jarvis.work.store import SQLiteWorkStore

REVISION = "a" * 40


class Backend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id, *, priority):
        del priority
        self.submissions.append(work_id)
        return work_id


def _fixture(tmp_path, *, registry: RepairRegistry | None = None):
    incident_store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(incident_store)
    work_path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(work_path)
    changes = ChangeStore(work, processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,))
    backend = Backend()
    change_coordinator = ChangeCoordinator(changes, backend)
    admission = IncidentRepairCoordinator(
        incidents=incidents,
        changes=change_coordinator,
        repair_registry=registry,
    )
    return incidents, work_path, changes, backend, admission


def _incident(incidents: IncidentService, *, reason: str = "unknown_failure"):
    incident = incidents.create_manual(
        title="voice runtime failed",
        symptom=reason,
        affected_components=("voice_runtime",),
        now_epoch=100.0,
    )
    evidence = EvidenceReference.create(
        kind="crash_fingerprint",
        reference=f"crash:{reason}:1",
        summary=f"reason={reason}; exit_code=1",
        component_id="voice_runtime",
        occurred_at_epoch=100.0,
    )
    return incidents.add_evidence(
        incident.incident_id,
        evidence,
        now_epoch=100.0,
    ), evidence


def _phase6_trigger(incident_id: str, evidence_id: str, *, reason: str):
    return IncidentRepairTrigger.create(
        incident_id=incident_id,
        source_revision=REVISION,
        component_ids=("voice_runtime",),
        evidence_ids=(evidence_id,),
        reason_code=reason,
        now_epoch=101.0,
    )


def test_unknown_incident_creates_one_canonical_diagnostics_change(tmp_path) -> None:
    incidents, work_path, changes, backend, admission = _fixture(tmp_path)
    incident, evidence = _incident(incidents)
    trigger = _phase6_trigger(
        incident.incident_id,
        evidence.evidence_id,
        reason="unknown_failure",
    )

    first = admission.admit(trigger)
    second = admission.admit(trigger)

    assert first.change.change_id == second.change.change_id
    assert first.diagnostics_work_id == second.diagnostics_work_id
    assert first.trigger_artifact_id == second.trigger_artifact_id
    assert first.evidence_artifact_id == second.evidence_artifact_id
    assert first.package.source_revision == REVISION
    assert first.package.trigger_digest == trigger.digest
    assert (
        changes.require(first.change.change_id).process_key == "unknown_incident_repair"
    )
    assert (
        changes.work.require(first.diagnostics_work_id).work_type
        is WorkType.DIAGNOSTICS
    )
    assert incidents.get(incident.incident_id).status is IncidentStatus.INVESTIGATING

    restarted_work = SQLiteWorkStore(work_path)
    restarted_changes = ChangeStore(
        restarted_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    restarted = IncidentRepairCoordinator(
        incidents=incidents,
        changes=ChangeCoordinator(restarted_changes, Backend()),
    )
    third = restarted.admit(trigger)

    assert third.change.change_id == first.change.change_id
    assert third.diagnostics_work_id == first.diagnostics_work_id
    assert len(restarted_changes.list_stages(first.change.change_id)) == 1
    assert backend.submissions


def test_registered_deterministic_repair_keeps_priority_over_phase6(tmp_path) -> None:
    policy = RepairPolicy(
        policy_id="known-runtime-restart",
        version=1,
        trigger_source="test_supervisor",
        component_id="voice_runtime",
        reason_code="known_failure",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=(),
        max_attempts=3,
        rolling_window_seconds=300.0,
        cooldown_seconds=1.0,
        backoff_multiplier=2.0,
        verification_contract="runtime-liveness-v1",
        reversible=True,
        automatic=True,
    )
    registry = RepairRegistry((policy,))
    incidents, _, changes, _, admission = _fixture(tmp_path, registry=registry)
    incident, evidence = _incident(incidents, reason="known_failure")
    trigger = _phase6_trigger(
        incident.incident_id,
        evidence.evidence_id,
        reason="known_failure",
    )
    repair_trigger = RepairTrigger.create(
        component_id="voice_runtime",
        reason_code="known_failure",
        source="test_supervisor",
        health_state=HealthState.FAILED,
        evidence_references=(evidence.reference,),
        observed_at_epoch=101.0,
    )

    with pytest.raises(
        IncidentRepairAdmissionBlocked,
        match="deterministic automatic repair has priority",
    ):
        admission.admit(trigger, repair_trigger=repair_trigger)

    assert incidents.get(incident.incident_id).status is IncidentStatus.OPEN
    assert (
        changes.find_by_source(
            f"incident:{incident.incident_id}",
            f"revision:{REVISION}",
            "unknown_incident_repair",
        )
        is None
    )


def test_trigger_must_reference_canonical_incident_evidence(tmp_path) -> None:
    incidents, _, _, _, admission = _fixture(tmp_path)
    incident, _ = _incident(incidents)
    trigger = _phase6_trigger(
        incident.incident_id,
        "not-a-real-evidence-id",
        reason="unknown_failure",
    )

    with pytest.raises(
        RuntimeError,
        match="evidence outside canonical incident",
    ):
        admission.admit(trigger)


def test_new_incident_evidence_revises_package_without_duplicate_work(tmp_path) -> None:
    incidents, _, changes, _, admission = _fixture(tmp_path)
    incident, evidence = _incident(incidents)
    trigger = _phase6_trigger(
        incident.incident_id,
        evidence.evidence_id,
        reason="unknown_failure",
    )
    first = admission.admit(trigger)

    additional = EvidenceReference.create(
        kind="structured_log",
        reference="log:voice:after",
        summary="additional safe runtime evidence",
        component_id="voice_runtime",
        occurred_at_epoch=102.0,
    )
    incidents.add_evidence(
        incident.incident_id,
        additional,
        now_epoch=102.0,
    )
    second = admission.admit(trigger)

    assert second.change.change_id == first.change.change_id
    assert second.diagnostics_work_id == first.diagnostics_work_id
    assert second.evidence_artifact_id != first.evidence_artifact_id
    assert (
        changes.latest_artifact(
            first.change.change_id,
            "incident_evidence",
        ).revision
        == 2
    )
