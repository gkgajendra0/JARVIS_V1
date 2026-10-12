from __future__ import annotations

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.engineering_change.gates import GateKind, GateService
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
    assert architecture.digest in delivery.message
    assert "The architecture is ready for your approval" in delivery.message
    assert change.change_id not in delivery.message


def test_architecture_gate_message_discloses_physical_target_scopes(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Acquire TV control", "session", "turn")
    stage = store.list_stages(change.change_id)[0]
    _complete(work, stage.work_id)
    store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "strategy": "build_custom",
            "allowed_paths": ["src/jarvis/tv.py"],
            "device_scopes": ["Verified living-room television"],
            "network_scopes": ["Approved local TV endpoint only"],
            "discovery_scopes": ["reviewed-discovery-scope"],
            "owner_acceptance_contract_ids": ["real-target-readback"],
        },
    )
    coordinator.reconcile(change.change_id)

    assert reconcile_owner_change_gates(coordinator)
    deliveries = work.list_pending_deliveries(limit=10)
    assert len(deliveries) == 1
    message = deliveries[0].message
    assert "Verified living-room television" in message
    assert "Approved local TV endpoint only" in message
    assert "reviewed-discovery-scope" in message
    assert "real-target-readback" in message


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


def test_revised_architecture_gate_delivery_uses_latest_source_attempt(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())

    change = coordinator.start("Build capability", "session", "turn")
    source1 = store.list_stages(change.change_id)[0]
    _complete(work, source1.work_id)
    architecture1 = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom", "allowed_paths": ["capability_v1.py"]},
    )
    coordinator.reconcile(change.change_id)
    gates = GateService(store, verify_owner=lambda *_: True)
    gate1 = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture1.artifact_id,
    )
    gates.decide(
        gate1.gate_id,
        approved=True,
        artifact_digest=architecture1.digest,
        actor_id="owner",
        source_session_id="session-approval-1",
        source_turn_id="turn-approval-1",
        request_key="request-approval-1",
    )
    coordinator.reconcile(change.change_id)
    development = next(
        stage
        for stage in store.list_stages(change.change_id)
        if stage.stage_key == "development"
    )

    store.request_architecture_revision_for_work(
        development.work_id,
        reason="The first architecture needs a different transport.",
    )
    coordinator.reconcile(change.change_id)
    source2 = [
        stage
        for stage in store.list_stages(change.change_id)
        if stage.stage_key == "research"
    ][-1]
    assert source2.attempt == 2
    _complete(work, source2.work_id)
    architecture2 = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom", "allowed_paths": ["capability_v2.py"]},
    )

    reconciled = coordinator.reconcile(change.change_id)
    assert reconciled.state is ChangeState.ARCHITECTURE_READY
    surfaced = reconcile_owner_change_gates(coordinator)

    assert len(surfaced) == 1
    deliveries = work.list_pending_deliveries(limit=10)
    assert len(deliveries) == 1
    assert deliveries[0].kind is WorkDeliveryKind.CHANGE_GATE
    assert deliveries[0].work_id == source2.work_id
    assert deliveries[0].work_id != source1.work_id
    assert architecture2.digest in deliveries[0].event_key
