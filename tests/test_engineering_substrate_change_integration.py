from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.authority import RiskClass
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_change.models import ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate import (
    CapabilityManifest,
    DependencyResolution,
    EngineeringSubstrateChangeService,
    RegisteredCapabilityManifest,
    SecretLease,
    SecretMaterializationMode,
    canonical_digest,
)
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.resources import (
    ResourceLeaseManager,
    engineering_resource_capacities,
)
from jarvis.work.store import SQLiteWorkStore


def _approved_change(tmp_path: Path) -> tuple[ChangeStore, str]:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    change = store.create(
        request="phase5i integration test",
        process_key=ChangeStore.DEFAULT_PROCESS.key,
        process_version=ChangeStore.DEFAULT_PROCESS.version,
        source_session_id="phase5i-session",
        source_turn_id="phase5i-turn",
    )
    change = store.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )
    architecture = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"design": "phase5i-v1"},
    )
    change = store.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )
    gates = GateService(store, verify_owner=lambda *_: True)
    challenge = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        challenge.gate_id,
        approved=True,
        artifact_digest=challenge.artifact_digest,
        actor_id="owner",
        source_session_id="phase5i-session",
        source_turn_id="phase5i-approval",
        request_key="phase5i-architecture-approval",
    )
    assert store.require(change.change_id).state is ChangeState.APPROVED_FOR_BUILD
    return store, change.change_id


def _resolution(
    change_id: str,
    *,
    resolution_id: str = "resolution-demo",
    lock_digest: str = "a" * 64,
) -> DependencyResolution:
    return DependencyResolution(
        resolution_id=resolution_id,
        requirement_id="requirement-demo",
        resolver_id="uv.v1",
        resolver_version="0.12.18",
        resolver_digest="b" * 64,
        resolved_packages=("demo==1.0.0",),
        artifact_ids=("artifact-demo",),
        dependency_graph_digest="c" * 64,
        lock_format="pylock.toml",
        lock_version="1.0",
        lock_digest=lock_digest,
        platform_constraints=("windows-x86_64",),
        change_id=change_id,
    )


def _registered_manifest(
    *,
    dependency: DependencyResolution | None = None,
    secret_scopes: tuple[str, ...] = (),
    suffix: str = "v1",
) -> RegisteredCapabilityManifest:
    resolution_ids = () if dependency is None else (dependency.resolution_id,)
    resolution_digests = () if dependency is None else (canonical_digest(dependency),)
    manifest = CapabilityManifest(
        manifest_id=f"manifest.phase5i.{suffix}",
        manifest_version=1,
        capability_id="capability.phase5i.demo",
        capability_version="1.0.0",
        purpose="Phase 5I lifecycle integration test",
        adapter_id="adapter.phase5i.demo",
        executor_id="executor.phase5i.demo",
        operations=("run",),
        dependency_resolution_ids=resolution_ids,
        secret_scope_requirements=secret_scopes,
        authority_attributes=(),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=("verification.phase5i.v1",),
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="rollback.phase5i.v1",
        dependency_resolution_digests=resolution_digests,
        sandbox_profile_digests=(),
        discovery_scope_digests=(),
        provenance_digests=(),
    )
    return RegisteredCapabilityManifest(
        manifest=manifest,
        manifest_digest=canonical_digest(manifest),
        authority_risk_floor=RiskClass.ROUTINE,
    )


def _lease(
    change_id: str,
    *,
    scopes: tuple[str, ...] = ("repository.read",),
) -> SecretLease:
    return SecretLease(
        lease_id="lease-phase5i-1",
        secret_id="secret-phase5i",
        secret_version=1,
        consumer_id="dependency.private-index.v1",
        scopes=scopes,
        materialization_mode=SecretMaterializationMode.CHILD_ENV,
        issued_at_epoch=1_000.0,
        expires_at_epoch=1_060.0,
        use_budget=1,
        policy_digest="d" * 64,
        change_id=change_id,
        work_id="work-phase5i",
    )


def test_dependency_resolution_swap_invalidates_bound_manifest(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    first = _resolution(change_id)
    service.bind_dependency_resolution(change_id, first)
    service.bind_manifest(
        change_id,
        _registered_manifest(dependency=first),
    )

    assert service.binding_snapshot(change_id).dependency_artifact_ids

    service.bind_dependency_resolution(
        change_id,
        _resolution(change_id, lock_digest="e" * 64),
    )

    with pytest.raises(ChangeConflict, match="lineage is stale"):
        service.binding_snapshot(change_id)


def test_manifest_revision_invalidates_previous_verification(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(change_id, _registered_manifest(suffix="one"))
    verified = service.record_verification(
        change_id,
        software_security_passed=True,
        automated_evidence={"software-security": True},
    )

    assert verified.payload["satisfied"] is True
    assert service.verification_current(change_id) is True

    service.bind_manifest(change_id, _registered_manifest(suffix="two"))

    assert service.verification_current(change_id) is False


def test_secret_scope_revision_invalidates_old_lease_evidence(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(
        change_id,
        _registered_manifest(secret_scopes=("repository.read",), suffix="read"),
    )
    lease = _lease(change_id)
    service.bind_secret_lease(change_id, lease)

    assert service.secret_lease_binding_current(change_id, lease.lease_id) is True
    verification = service.record_verification(
        change_id,
        software_security_passed=True,
        automated_evidence={"software-security": True},
    )
    assert verification.payload["satisfied"] is True

    service.bind_manifest(
        change_id,
        _registered_manifest(secret_scopes=("repository.write",), suffix="write"),
    )

    assert service.secret_lease_binding_current(change_id, lease.lease_id) is False
    assert service.verification_current(change_id) is False


def test_missing_secret_scope_prevents_satisfied_verification(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(
        change_id,
        _registered_manifest(secret_scopes=("repository.read",)),
    )

    verification = service.record_verification(
        change_id,
        software_security_passed=True,
        automated_evidence={"software-security": True},
    )

    assert verification.payload["satisfied"] is False
    assert verification.payload["missing_secret_scopes"] == ["repository.read"]
    assert service.verification_current(change_id) is False


def test_software_failure_cannot_become_current_substrate_verification(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(change_id, _registered_manifest())

    verification = service.record_verification(
        change_id,
        software_security_passed=False,
        automated_evidence={"software-security": True},
    )

    assert verification.payload["satisfied"] is False
    assert service.verification_current(change_id) is False


def _verified_development(
    store: ChangeStore,
    change_id: str,
) -> tuple[WorkItem, object]:
    item = WorkItem(
        request="verified phase5i development",
        work_type=WorkType.DEVELOPMENT,
        source_session_id=f"change:{change_id}",
        source_turn_id="development:1",
        state=WorkState.COMPLETED,
        result={
            "branch": "feat/phase5i-test",
            "commit": "f" * 40,
            "verification": {"passed": True, "sandbox": "test.offline.v1"},
        },
    )
    stage = store.link_work(change_id, "development", 1, item)
    change = store.require(change_id)
    change = store.transition(
        change_id,
        ChangeState.DEVELOPING,
        expected_version=change.version,
    )
    store.transition(
        change_id,
        ChangeState.VERIFYING,
        expected_version=change.version,
    )
    return item, stage


def test_canonical_acceptance_gate_rejects_missing_phase5_verification(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(change_id, _registered_manifest())
    item, _ = _verified_development(store, change_id)
    acceptance = store.add_artifact(
        change_id,
        kind="acceptance",
        payload={"work_id": item.work_id, "result": item.result},
    )

    gates = GateService(store, verify_owner=lambda *_: True)
    with pytest.raises(ChangeConflict, match="Phase-5 substrate verification"):
        gates.present(change_id, GateKind.ACCEPTANCE, acceptance.artifact_id)

    service.record_verification(
        change_id,
        software_security_passed=True,
        automated_evidence={"software-security": True},
    )
    challenge = gates.present(
        change_id,
        GateKind.ACCEPTANCE,
        acceptance.artifact_id,
    )

    assert challenge.kind is GateKind.ACCEPTANCE


def test_non_phase5_acceptance_gate_keeps_existing_behavior(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    item, _ = _verified_development(store, change_id)
    acceptance = store.add_artifact(
        change_id,
        kind="acceptance",
        payload={"work_id": item.work_id, "result": item.result},
    )

    challenge = GateService(store, verify_owner=lambda *_: True).present(
        change_id,
        GateKind.ACCEPTANCE,
        acceptance.artifact_id,
    )

    assert challenge.kind is GateKind.ACCEPTANCE


def test_blocker_delivery_deduplicates_by_stable_reason(
    tmp_path: Path,
) -> None:
    store, _ = _approved_change(tmp_path)
    item = WorkItem(
        request="resource blocked work",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="direct-session",
        source_turn_id="direct-turn",
        state=WorkState.RUNNING,
    )
    store.work.create(item)
    service = EngineeringSubstrateChangeService(store)

    first = service.block_work_resource(
        item.work_id,
        component="resolver",
        reason_code="trusted-source-unavailable",
        message="Registered package source is temporarily unavailable.",
    )
    second = service.block_work_resource(
        item.work_id,
        component="resolver",
        reason_code="trusted-source-unavailable",
        message="Registered package source remains temporarily unavailable.",
    )

    assert first is not None
    assert second is not None
    assert first.delivery_id == second.delivery_id
    pending = store.work.list_pending_deliveries(limit=50)
    matching = tuple(
        delivery
        for delivery in pending
        if delivery.event_key == first.event_key
    )
    assert len(matching) == 1
    assert store.work.require(item.work_id).state is WorkState.WAITING_RESOURCE


def test_operational_events_contain_only_bounded_id_digest_metadata(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    manifest = service.bind_manifest(change_id, _registered_manifest())

    events = [
        event
        for event in store.list_events(change_id)
        if event["kind"] == "substrate_operational"
    ]
    assert events
    payload = events[-1]["detail"]
    assert set(payload) == {"component", "status", "reference_id", "digest"}
    assert payload["reference_id"] == manifest.artifact_id
    assert payload["digest"] == manifest.digest


def test_binding_and_verification_survive_service_restart(
    tmp_path: Path,
) -> None:
    store, change_id = _approved_change(tmp_path)
    service = EngineeringSubstrateChangeService(store)
    service.bind_manifest(change_id, _registered_manifest())
    service.record_verification(
        change_id,
        software_security_passed=True,
        automated_evidence={"software-security": True},
    )

    restarted = EngineeringSubstrateChangeService(store)

    assert restarted.verification_current(change_id) is True


def test_phase5_resource_keys_are_registered_and_independent() -> None:
    capacities = engineering_resource_capacities()
    assert set(capacities) == {
        "resolver",
        "artifact",
        "secret",
        "discovery",
        "docker",
        "device_acceptance",
    }
    manager = ResourceLeaseManager(capacities)
    assert manager.normalize(tuple(capacities)) == tuple(sorted(capacities))

    async def run() -> tuple[tuple[str, ...], tuple[str, ...]]:
        entered = asyncio.Event()

        async def resolver():
            async with manager.lease(("resolver",)) as lease:
                entered.set()
                await asyncio.sleep(0)
                return lease

        async def discovery():
            await entered.wait()
            async with manager.lease(("discovery",)) as lease:
                return lease

        return tuple(await asyncio.gather(resolver(), discovery()))  # type: ignore[return-value]

    resolver_lease, discovery_lease = asyncio.run(run())
    assert resolver_lease == ("resolver",)
    assert discovery_lease == ("discovery",)
