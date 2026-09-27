from __future__ import annotations

import pytest

from jarvis.engineering_change import (
    ChangeConflict,
    ChangeState,
    ChangeStore,
    ProcessStageRole,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.incident_repair import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.models import WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id: str, *, priority) -> str:
        del priority
        self.submissions.append(work_id)
        return work_id


def _complete(work: SQLiteWorkStore, work_id: str) -> None:
    item = work.require(work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED),
        expected_version=running.version,
    )


def test_default_engineering_process_keeps_research_then_development() -> None:
    process = ChangeStore.DEFAULT_PROCESS

    assert process.architecture_source_stage.stage_key == "research"
    assert process.architecture_source_stage.work_type is WorkType.RESEARCH
    assert (
        process.architecture_source_stage.role is ProcessStageRole.ARCHITECTURE_SOURCE
    )
    assert process.development_stage.stage_key == "development"
    assert process.development_stage.work_type is WorkType.DEVELOPMENT


def test_phase6_process_declares_diagnostics_then_development() -> None:
    process = UNKNOWN_INCIDENT_REPAIR_PROCESS

    assert process.key == "unknown_incident_repair"
    assert process.version == 1
    assert process.architecture_source_stage.stage_key == "diagnostics"
    assert process.architecture_source_stage.work_type is WorkType.DIAGNOSTICS
    assert process.development_stage.stage_key == "development"
    assert process.development_stage.work_type is WorkType.DEVELOPMENT

    with pytest.raises(ChangeConflict, match="unregistered change stage"):
        process.stage_for_key("shell")


def test_phase6_coordinator_uses_diagnostics_before_owner_gated_development(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work, processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,))
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = coordinator.start(
        "Investigate unknown routing failure",
        "incident:incident-1",
        "source:" + ("a" * 40),
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
    )

    stages = changes.list_stages(change.change_id)
    assert len(stages) == 1
    diagnostics = stages[0]
    assert diagnostics.stage_key == "diagnostics"
    assert work.require(diagnostics.work_id).work_type is WorkType.DIAGNOSTICS
    assert work.require(diagnostics.work_id).dependencies == ()
    assert changes.require(change.change_id).state is ChangeState.RESEARCHING

    with pytest.raises(ChangeConflict):
        coordinator.submit_stage(change.change_id, "development", 1)

    _complete(work, diagnostics.work_id)
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "diagnosis_digest": "b" * 64,
            "source_revision": "a" * 40,
            "verification_targets": ["tests/test_model_routing_health.py"],
        },
    )
    coordinator.reconcile_for_work(diagnostics.work_id)
    assert changes.require(change.change_id).state is ChangeState.ARCHITECTURE_READY

    gates = GateService(changes, verify_owner=lambda *_: True)
    with pytest.raises(ChangeConflict, match="architecture contract is invalid"):
        gates.present(
            change.change_id,
            GateKind.ARCHITECTURE,
            architecture.artifact_id,
        )

    stages = changes.list_stages(change.change_id)
    assert [stage.stage_key for stage in stages] == ["diagnostics"]


def test_phase6_process_fails_closed_if_handler_is_not_registered_after_restart(
    tmp_path,
) -> None:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(path)
    changes = ChangeStore(work, processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,))
    change = changes.create(
        request="Investigate unknown failure",
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
        source_session_id="incident:1",
        source_turn_id="revision:1",
    )

    restarted = ChangeStore(SQLiteWorkStore(path))
    with pytest.raises(ChangeConflict, match="unsupported change process"):
        restarted.require(change.change_id)
