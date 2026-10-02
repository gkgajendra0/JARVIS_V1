from __future__ import annotations

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.work.models import WorkDeliveryKind, WorkState
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id, *, priority):
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


def test_architecture_ready_is_surfaced_as_exact_owner_gate(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())

    change = coordinator.start("Build capability", "session", "turn")
    stage = store.list_stages(change.change_id)[0]
    _complete(work, stage.work_id)
    architecture = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "adapt_sdk", "allowed_paths": ["adapter.py"]},
    )
    coordinator.reconcile(change.change_id)

    assert store.require(change.change_id).state is ChangeState.ARCHITECTURE_READY

    surfaced = reconcile_owner_change_gates(coordinator)

    assert len(surfaced) == 1
    gate_id = surfaced[0]
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL

    deliveries = work.list_pending_deliveries(limit=10)
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.kind is WorkDeliveryKind.CHANGE_GATE
    assert delivery.work_id == stage.work_id
    assert gate_id in delivery.event_key
    assert architecture.digest in delivery.event_key
    assert f"approve {gate_id}" in delivery.message
    assert f"reject {gate_id}" in delivery.message


def test_gate_reconciliation_is_idempotent_across_restart_style_rechecks(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())

    change = coordinator.start("Build capability", "session", "turn")
    stage = store.list_stages(change.change_id)[0]
    _complete(work, stage.work_id)
    store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom", "allowed_paths": ["capability.py"]},
    )
    coordinator.reconcile(change.change_id)

    first = reconcile_owner_change_gates(coordinator)
    second = reconcile_owner_change_gates(coordinator)

    assert first == second
    deliveries = work.list_pending_deliveries(limit=10)
    assert len(deliveries) == 1
    assert deliveries[0].kind is WorkDeliveryKind.CHANGE_GATE
