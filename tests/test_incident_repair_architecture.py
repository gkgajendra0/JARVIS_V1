from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_change.models import ChangeConflict
from jarvis.incident_repair.architecture import (
    IncidentRepairSourceCompletionHandler,
    ensure_incident_repair_architecture_current,
)
from jarvis.incident_repair.models import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    IncidentRepairTrigger,
    ReproductionState,
)
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.models import WorkPriority, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore

REVISION = "a" * 40


@dataclass
class Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def _coordinator(store: ChangeStore, backend: Backend) -> ChangeCoordinator:
    return ChangeCoordinator(
        store,
        backend,
        source_completion_handlers=(IncidentRepairSourceCompletionHandler(store),),
    )


def _supported_diagnosis(*, change_id: str, work_id: str) -> IncidentDiagnosis:
    hypothesis = DiagnosticHypothesis.create(
        statement="voice supervisor race",
        affected_components=("runtime.voice",),
        affected_paths=("src/jarvis/voice/runtime.py",),
        supporting_evidence_ids=("evidence-1",),
        status=HypothesisState.SUPPORTED,
        discriminator="failure occurs before supervisor state commit",
    )
    return IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id=change_id,
        work_id=work_id,
        source_revision=REVISION,
        evidence_ids=("evidence-1",),
        knowledge_revision_ids=("knowledge-r1",),
        reproduction_state=ReproductionState.REPRODUCED,
        hypotheses=(hypothesis,),
        selected_hypothesis_id=hypothesis.hypothesis_id,
        affected_paths=("src/jarvis/voice/runtime.py",),
        affected_components=("runtime.voice",),
        proposed_repair_scope="serialize supervisor state commit",
        verification_targets=("tests/test_voice_runtime.py",),
        reason_codes=("reproduced", "supported_hypothesis"),
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=200.0,
    )


def _inconclusive_diagnosis(*, change_id: str, work_id: str) -> IncidentDiagnosis:
    hypothesis = DiagnosticHypothesis.create(
        statement="hardware timing may be involved",
        status=HypothesisState.INCONCLUSIVE,
    )
    return IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id=change_id,
        work_id=work_id,
        source_revision=REVISION,
        evidence_ids=("evidence-1",),
        reproduction_state=ReproductionState.INCONCLUSIVE,
        hypotheses=(hypothesis,),
        reason_codes=("reproduction_impossible",),
        disposition=DiagnosisDisposition.INCONCLUSIVE,
        now_epoch=200.0,
    )


def _fixture(tmp_path, *, inconclusive: bool = False):
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    change_store = ChangeStore(
        work_store,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    backend = Backend([])
    coordinator = _coordinator(change_store, backend)
    change = coordinator.start(
        "Investigate incident incident-1 at exact source revision " + REVISION,
        "incident:incident-1",
        "revision:" + REVISION,
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
    )
    stage = change_store.list_stages(change.change_id)[0]
    diagnostic_work = work_store.require(stage.work_id)

    trigger = IncidentRepairTrigger.create(
        incident_id="incident-1",
        source_revision=REVISION,
        component_ids=("runtime.voice",),
        evidence_ids=("evidence-1",),
        reason_code="unknown_failure",
        now_epoch=100.0,
    )
    change_store.add_artifact(
        change.change_id,
        kind="incident_repair_trigger",
        payload={
            "trigger_id": trigger.trigger_id,
            **trigger.canonical_payload(),
            "digest": trigger.digest,
        },
    )

    diagnosis = (
        _inconclusive_diagnosis(
            change_id=change.change_id,
            work_id=stage.work_id,
        )
        if inconclusive
        else _supported_diagnosis(
            change_id=change.change_id,
            work_id=stage.work_id,
        )
    )
    diagnosis_payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    diagnosis_artifact = change_store.add_artifact(
        change.change_id,
        kind="diagnosis",
        payload={
            "diagnosis": diagnosis_payload,
            "suspicious_locations": [],
            "reproduction_impossible_reason": (
                "hardware timing unavailable" if inconclusive else None
            ),
        },
    )

    running = diagnostic_work.transition(WorkState.RUNNING)
    work_store.save(running, expected_version=diagnostic_work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "diagnosis": diagnosis_payload,
            "diagnosis_artifact_id": diagnosis_artifact.artifact_id,
            "diagnosis_artifact_digest": diagnosis_artifact.digest,
            "suspicious_locations": [],
        },
    )
    work_store.save(completed, expected_version=running.version)
    return (
        work_store,
        change_store,
        backend,
        coordinator,
        change.change_id,
        stage.work_id,
        diagnosis,
        diagnosis_artifact,
    )


def test_supported_diagnosis_derives_exact_architecture_without_development(
    tmp_path,
) -> None:
    (
        _,
        store,
        _,
        coordinator,
        change_id,
        diagnostic_work_id,
        diagnosis,
        diagnosis_artifact,
    ) = _fixture(tmp_path)

    reconciled = coordinator.reconcile_for_work(diagnostic_work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.ARCHITECTURE_READY
    architecture = ensure_incident_repair_architecture_current(store, change_id)
    assert (
        architecture.payload["diagnosis_artifact_id"] == diagnosis_artifact.artifact_id
    )
    assert (
        architecture.payload["diagnosis_artifact_digest"] == diagnosis_artifact.digest
    )
    assert architecture.payload["diagnosis_id"] == diagnosis.diagnosis_id
    assert architecture.payload["diagnosis_digest"] == diagnosis.digest
    assert architecture.payload["source_revision"] == REVISION
    assert architecture.payload["repair_scope"] == ("serialize supervisor state commit")
    assert architecture.payload["allowed_paths"] == ["src/jarvis/voice/runtime.py"]
    assert architecture.payload["verification_targets"] == [
        "tests/test_voice_runtime.py"
    ]
    assert architecture.payload["build_permitted"] is True
    assert [stage.stage_key for stage in store.list_stages(change_id)] == [
        "diagnostics"
    ]


def test_owner_rejection_never_creates_development_work(tmp_path) -> None:
    _, store, _, coordinator, change_id, diagnostic_work_id, _, _ = _fixture(tmp_path)
    coordinator.reconcile_for_work(diagnostic_work_id)
    architecture = store.latest_artifact(change_id, "architecture")
    assert architecture is not None

    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(change_id, GateKind.ARCHITECTURE, architecture.artifact_id)
    decision = gates.decide(
        gate.gate_id,
        approved=False,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="reject",
        request_key="phase6e:reject",
    )

    assert decision.approved is False
    assert store.require(change_id).state is ChangeState.REJECTED
    assert [stage.stage_key for stage in store.list_stages(change_id)] == [
        "diagnostics"
    ]


def test_stale_architecture_gate_cannot_be_approved(tmp_path) -> None:
    _, store, _, coordinator, change_id, diagnostic_work_id, _, _ = _fixture(tmp_path)
    coordinator.reconcile_for_work(diagnostic_work_id)
    architecture = store.latest_artifact(change_id, "architecture")
    assert architecture is not None

    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(change_id, GateKind.ARCHITECTURE, architecture.artifact_id)
    store.add_artifact(
        change_id,
        kind="architecture",
        payload={**architecture.payload, "repair_scope": "superseding scope"},
    )

    with pytest.raises(ChangeConflict, match="superseded"):
        gates.decide(
            gate.gate_id,
            approved=True,
            artifact_digest=architecture.digest,
            actor_id="owner",
            source_session_id="owner",
            source_turn_id="approve-stale",
            request_key="phase6e:stale",
        )


def test_exact_owner_approval_creates_one_bound_development_workitem(
    tmp_path,
) -> None:
    (
        work_store,
        store,
        backend,
        coordinator,
        change_id,
        diagnostic_work_id,
        diagnosis,
        _,
    ) = _fixture(tmp_path)
    coordinator.reconcile_for_work(diagnostic_work_id)
    architecture = ensure_incident_repair_architecture_current(store, change_id)

    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(change_id, GateKind.ARCHITECTURE, architecture.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="approve",
        request_key="phase6e:approve",
    )

    first = coordinator.reconcile(change_id)
    second = coordinator.reconcile(change_id)

    assert first.state is ChangeState.DEVELOPING
    assert second.state is ChangeState.DEVELOPING
    stages = store.list_stages(change_id)
    assert [stage.stage_key for stage in stages] == [
        "diagnostics",
        "development",
    ]
    development = stages[1]
    assert development.plan_artifact_id == architecture.artifact_id
    dev_work = work_store.require(development.work_id)
    assert dev_work.work_type is WorkType.DEVELOPMENT
    assert dev_work.dependencies == (diagnostic_work_id,)
    assert architecture.artifact_id in dev_work.request
    assert architecture.digest in dev_work.request
    assert diagnosis.diagnosis_id in dev_work.request
    assert diagnosis.digest in dev_work.request
    assert backend.submitted.count(development.work_id) >= 1
    assert len([stage for stage in stages if stage.stage_key == "development"]) == 1


def test_restart_cannot_skip_architecture_owner_gate(tmp_path) -> None:
    work_store, store, _, coordinator, change_id, diagnostic_work_id, _, _ = _fixture(
        tmp_path
    )
    coordinator.reconcile_for_work(diagnostic_work_id)
    architecture = ensure_incident_repair_architecture_current(store, change_id)
    assert store.require(change_id).state is ChangeState.ARCHITECTURE_READY

    restarted_store = ChangeStore(
        SQLiteWorkStore(work_store.path),
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    restarted_backend = Backend([])
    restarted = _coordinator(restarted_store, restarted_backend)

    restarted.reconcile_active()

    assert restarted_store.require(change_id).state is ChangeState.ARCHITECTURE_READY
    assert [stage.stage_key for stage in restarted_store.list_stages(change_id)] == [
        "diagnostics"
    ]
    assert (
        architecture.artifact_id
        == restarted_store.latest_artifact(
            change_id,
            "architecture",
        ).artifact_id
    )


def test_inconclusive_diagnosis_stops_without_build_architecture(tmp_path) -> None:
    _, store, _, coordinator, change_id, diagnostic_work_id, _, _ = _fixture(
        tmp_path,
        inconclusive=True,
    )

    result = coordinator.reconcile_for_work(diagnostic_work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    assert store.latest_artifact(change_id, "architecture") is None
    assert [stage.stage_key for stage in store.list_stages(change_id)] == [
        "diagnostics"
    ]
