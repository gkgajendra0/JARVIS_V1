from __future__ import annotations

from jarvis.engineering_change import (
    ChangeState,
    ChangeStore,
    ProcessContract,
    ProcessStageContract,
    ProcessStageRole,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.incident_repair import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.models import WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id, *, priority):
        del priority
        self.submitted.append(work_id)
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


def test_default_engineering_change_stage_contract_is_unchanged(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    change = ChangeCoordinator(changes, Backend()).start(
        "Research adapter",
        "owner",
        "turn",
    )
    stage = changes.list_stages(change.change_id)[0]
    assert stage.stage_key == "research"
    assert work.require(stage.work_id).work_type is WorkType.RESEARCH


def test_incident_repair_process_starts_with_diagnostics_and_reuses_dev_gate(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work, processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,))
    backend = Backend()
    coordinator = ChangeCoordinator(changes, backend)

    change = coordinator.start(
        "Investigate incident incident-1 at revision " + "a" * 40,
        "incident:incident-1",
        "revision:" + "a" * 40,
        process_key="unknown_incident_repair",
        process_version=1,
    )
    diagnostic = changes.list_stages(change.change_id)[0]
    diagnostic_work = work.require(diagnostic.work_id)
    assert diagnostic.stage_key == "diagnostics"
    assert diagnostic_work.work_type is WorkType.DIAGNOSTICS
    assert diagnostic_work.dependencies == ()

    _complete(work, diagnostic.work_id)
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "diagnosis_id": "diagnosis-1",
            "source_revision": "a" * 40,
            "verification_targets": ["tests/test_fault.py"],
        },
    )
    coordinator.reconcile_for_work(diagnostic.work_id)
    assert changes.require(change.change_id).state is ChangeState.ARCHITECTURE_READY

    gates = GateService(changes, verify_owner=lambda *_: True)
    gate = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="approve",
        request_key="owner:approve:phase6",
    )

    coordinator.reconcile(change.change_id)
    development = changes.list_stages(change.change_id)[1]
    development_work = work.require(development.work_id)
    assert development.stage_key == "development"
    assert development_work.work_type is WorkType.DEVELOPMENT
    assert development_work.dependencies == (diagnostic.work_id,)
    assert development.plan_artifact_id == architecture.artifact_id
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING


def test_process_stage_contract_fails_closed_on_invalid_shape() -> None:
    ProcessContract(
        "diagnostic.demo",
        1,
        stages=(
            ProcessStageContract(
                "diagnostics",
                WorkType.DIAGNOSTICS,
                ProcessStageRole.ARCHITECTURE_SOURCE,
            ),
            ProcessStageContract(
                "development",
                WorkType.DEVELOPMENT,
                ProcessStageRole.DEVELOPMENT,
            ),
        ),
    )

    try:
        ProcessContract(
            "bad.process",
            1,
            stages=(
                ProcessStageContract(
                    "diagnostics",
                    WorkType.DIAGNOSTICS,
                    ProcessStageRole.ARCHITECTURE_SOURCE,
                ),
                ProcessStageContract(
                    "diagnostics",
                    WorkType.DEVELOPMENT,
                    ProcessStageRole.DEVELOPMENT,
                ),
            ),
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate process stage keys must fail closed")
