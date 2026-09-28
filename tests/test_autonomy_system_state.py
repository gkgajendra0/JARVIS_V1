from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.autonomy.sources import (
    CapabilityStateSource,
    EngineeringChangeSource,
    IncidentSource,
    ModelProviderStateSource,
    ProductionObservationSource,
    ResourceStateSource,
    SelfModelHealthSource,
    WorkPortfolioSource,
)
from jarvis.autonomy.store import AutonomyIntegrityError, AutonomyStore
from jarvis.autonomy.system_state import (
    DuplicateSystemStateSourceError,
    SystemStateAggregator,
    SystemStateFactV1,
    SystemStateReadRequestV1,
    SystemStateSnapshotV1,
    SystemStateSourceRegistry,
    SystemStateSourceResultV1,
    SystemStateSourceStatus,
    SystemStateTargetV1,
)
from jarvis.capability_registry.projection import CapabilityRegistryProjection
from jarvis.capability_registry.provider import CapabilityProviderRegistry
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change.store import ChangeStore
from jarvis.incidents.models import IncidentRecord, IncidentSeverity
from jarvis.incidents.store import SqliteIncidentStore
from jarvis.model_routing.registry import ModelAdapterRegistry, ModelTargetRegistry
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.promotion.release import DeploymentMetadataStore, ReleaseRecord
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState
from jarvis.self_model.models import ComponentDescriptor
from jarvis.self_model.registry import SelfModelRegistry
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
RELEASE_SHA = "c" * 40


def _fact(
    *,
    namespace: str = "alpha",
    target_identity: str = "target-1",
    value: dict | None = None,
    observed_at_epoch: float = NOW,
    fresh_until_epoch: float | None = None,
    source_key: str = "static",
) -> SystemStateFactV1:
    return SystemStateFactV1(
        fact_namespace=namespace,
        source_identity=f"{namespace}:{target_identity}",
        source_version_or_digest=DIGEST_A,
        target_namespace="test_target",
        target_identity=target_identity,
        value_json=value or {"state": "ok"},
        observed_at_epoch=observed_at_epoch,
        fresh_until_epoch=fresh_until_epoch,
        evidence_references=(f"evidence:{target_identity}",),
        source_adapter_key=source_key,
        source_adapter_version=1,
    )


class StaticSource:
    source_version = 1

    def __init__(
        self,
        *,
        source_key: str,
        namespace: str,
        fact: SystemStateFactV1,
    ) -> None:
        self.source_key = source_key
        self.namespaces = (namespace,)
        self.fact = fact
        self.calls = 0

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        self.calls += 1
        assert request.requested_namespaces == self.namespaces
        return SystemStateSourceResultV1(
            source_adapter_key=self.source_key,
            source_adapter_version=self.source_version,
            status=SystemStateSourceStatus.COMPLETE,
            facts=(self.fact,),
        )


class ExplodingSource:
    source_key = "exploding"
    source_version = 1
    namespaces = ("delta",)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        del request
        raise RuntimeError("raw provider/store exception must not escape")


def test_system_state_fact_and_snapshot_identity_are_deterministic() -> None:
    first = _fact(value={"b": 2, "a": 1})
    second = _fact(value={"a": 1, "b": 2})

    assert first.digest == second.digest

    snapshot_a = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=("beta", "alpha"),
        facts=(first,),
        source_errors=(),
        incomplete_namespaces=(),
        started_at_epoch=NOW,
        ended_at_epoch=NOW,
    )
    snapshot_b = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=("alpha", "beta"),
        facts=(second,),
        source_errors=(),
        incomplete_namespaces=(),
        started_at_epoch=NOW,
        ended_at_epoch=NOW,
    )

    assert snapshot_a.snapshot_id == snapshot_b.snapshot_id
    assert snapshot_a.snapshot_digest == snapshot_b.snapshot_digest
    assert snapshot_a.fact_digests == (first.digest,)
    assert SystemStateSnapshotV1.from_payload(snapshot_a.to_payload()) == snapshot_a

    with pytest.raises(ValueError, match="digest"):
        SystemStateSnapshotV1(
            snapshot_id=snapshot_a.snapshot_id,
            snapshot_digest=DIGEST_B,
            evaluated_source_namespaces=snapshot_a.evaluated_source_namespaces,
            facts=snapshot_a.facts,
            source_errors=(),
            incomplete_namespaces=(),
            started_at_epoch=NOW,
            ended_at_epoch=NOW,
            producer_version=snapshot_a.producer_version,
        )


def test_source_registry_rejects_canonical_namespace_overlap() -> None:
    first = StaticSource(
        source_key="first",
        namespace="alpha",
        fact=_fact(source_key="first"),
    )
    second = StaticSource(
        source_key="second",
        namespace="alpha",
        fact=_fact(source_key="second"),
    )
    registry = SystemStateSourceRegistry((first,))

    with pytest.raises(DuplicateSystemStateSourceError, match="namespace"):
        registry.register(second)


def test_aggregator_preserves_missing_stale_and_error_semantics() -> None:
    healthy = StaticSource(
        source_key="healthy",
        namespace="alpha",
        fact=_fact(
            namespace="alpha",
            source_key="healthy",
            fresh_until_epoch=NOW + 60,
        ),
    )
    stale = StaticSource(
        source_key="stale",
        namespace="beta",
        fact=_fact(
            namespace="beta",
            source_key="stale",
            observed_at_epoch=NOW - 30,
            fresh_until_epoch=NOW - 1,
        ),
    )
    aggregator = SystemStateAggregator(
        SystemStateSourceRegistry((healthy, stale, ExplodingSource())),
        clock=lambda: NOW,
    )

    snapshot = aggregator.snapshot(
        requested_namespaces=("alpha", "beta", "gamma", "delta")
    )

    assert healthy.calls == 1
    assert stale.calls == 1
    assert snapshot.evaluated_source_namespaces == (
        "alpha",
        "beta",
        "delta",
        "gamma",
    )
    assert snapshot.incomplete_namespaces == ("beta", "delta", "gamma")
    reasons = {
        (item.source_namespace, item.reason_code)
        for item in snapshot.source_errors
    }
    assert ("beta", "stale_fact") in reasons
    assert ("gamma", "source_not_registered") in reasons
    assert ("delta", "source_read_failed") in reasons
    assert {item.fact_namespace for item in snapshot.facts} == {"alpha", "beta"}


def test_self_model_health_source_is_read_only_and_marks_unknown_health() -> None:
    model = SelfModelRegistry(
        components=(
            ComponentDescriptor(
                component_id="runtime.test",
                purpose="Deterministic Phase 10A test component.",
                source_paths=("src/jarvis/runtime_test",),
                health_surface=True,
            ),
        ),
    )
    health = HealthRegistry()
    source = SelfModelHealthSource(model, health)
    request = SystemStateReadRequestV1(
        requested_namespaces=("self_model", "health_registry"),
        targets=(
            SystemStateTargetV1(
                target_namespace="component",
                target_identity="runtime.test",
            ),
        ),
        now_epoch=NOW,
    )

    before = health.observations("runtime.test", now_epoch=NOW)
    result = source.read(request)
    after = health.observations("runtime.test", now_epoch=NOW)

    assert before == after == ()
    assert result.status is SystemStateSourceStatus.INCOMPLETE
    assert result.incomplete_namespaces == ("health_registry",)
    assert {item.fact_namespace for item in result.facts} == {
        "health_registry",
        "self_model",
    }
    health_fact = next(
        item for item in result.facts if item.fact_namespace == "health_registry"
    )
    assert health_fact.value_json["state"] == "unknown"


def test_self_model_health_source_reads_fresh_canonical_health_without_mutation() -> None:
    model = SelfModelRegistry(
        components=(
            ComponentDescriptor(
                component_id="runtime.test",
                purpose="Deterministic Phase 10A test component.",
                source_paths=("src/jarvis/runtime_test",),
                health_surface=True,
            ),
        ),
    )
    health = HealthRegistry()
    health.record(
        HealthObservation.create(
            component_id="runtime.test",
            source="phase10a.test",
            state=HealthState.HEALTHY,
            reason_code="test_healthy",
            summary="Deterministic health evidence.",
            ttl_seconds=60.0,
            observed_at_epoch=NOW,
        )
    )
    source = SelfModelHealthSource(model, health)
    request = SystemStateReadRequestV1(
        requested_namespaces=("self_model", "health_registry"),
        targets=(
            SystemStateTargetV1(
                target_namespace="component",
                target_identity="runtime.test",
            ),
        ),
        now_epoch=NOW,
    )

    before = health.observations("runtime.test", now_epoch=NOW)
    result = source.read(request)
    after = health.observations("runtime.test", now_epoch=NOW)

    assert before == after
    assert result.status is SystemStateSourceStatus.COMPLETE
    health_fact = next(
        item for item in result.facts if item.fact_namespace == "health_registry"
    )
    assert health_fact.value_json["state"] == "healthy"
    assert health_fact.fresh_until_epoch == NOW + 60.0


def test_work_change_and_incident_sources_do_not_copy_sensitive_requests(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    work = WorkItem(
        request="sensitive owner request must stay canonical",
        work_type=WorkType.RESEARCH,
        source_session_id="phase10a-test",
        source_turn_id="work-source",
    )
    work_store.create(work)
    work_before = work_store.require(work.work_id)

    work_result = WorkPortfolioSource(work_store).read(
        SystemStateReadRequestV1(
            requested_namespaces=("work",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="work",
                    target_identity=work.work_id,
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert work_store.require(work.work_id) == work_before
    assert len(work_result.facts) == 1
    assert "request" not in work_result.facts[0].value_json

    changes = ChangeStore(work_store)
    change = changes.create(
        request="sensitive engineering request",
        process_key=ChangeStore.DEFAULT_PROCESS.key,
        process_version=ChangeStore.DEFAULT_PROCESS.version,
        source_session_id="phase10a-test",
        source_turn_id="change-source",
    )
    change_before = changes.require(change.change_id)
    change_result = EngineeringChangeSource(changes).read(
        SystemStateReadRequestV1(
            requested_namespaces=("engineering_change",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="engineering_change",
                    target_identity=change.change_id,
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert changes.require(change.change_id) == change_before
    assert len(change_result.facts) == 1
    assert "request" not in change_result.facts[0].value_json

    incidents = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incident = IncidentRecord.create(
        title="sensitive incident title",
        symptom="sensitive incident symptom",
        affected_components=("runtime.test",),
        severity=IncidentSeverity.ERROR,
        now_epoch=NOW,
    )
    incidents.upsert(incident)
    incident_before = incidents.get(incident.incident_id)
    incident_result = IncidentSource(incidents).read(
        SystemStateReadRequestV1(
            requested_namespaces=("incident",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="incident",
                    target_identity=incident.incident_id,
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert incidents.get(incident.incident_id) == incident_before
    assert len(incident_result.facts) == 1
    assert "title" not in incident_result.facts[0].value_json
    assert "symptom" not in incident_result.facts[0].value_json


def test_capability_model_resource_and_production_sources_are_read_only(
    tmp_path: Path,
) -> None:
    capability_store = CapabilityRegistryStore(tmp_path / "capabilities.sqlite3")
    projection = CapabilityRegistryProjection(
        provider_registry=CapabilityProviderRegistry()
    )
    capability_before = capability_store.list_registry()
    capability_result = CapabilityStateSource(
        capability_store,
        projection,
    ).read(
        SystemStateReadRequestV1(
            requested_namespaces=("capability_registry",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="capability",
                    target_identity="missing.capability",
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert capability_store.list_registry() == capability_before
    assert capability_result.status is SystemStateSourceStatus.INCOMPLETE
    assert capability_result.incomplete_namespaces == ("capability_registry",)

    work_store = SQLiteWorkStore(tmp_path / "routing-work.sqlite3")
    routing_store = ModelRoutingStore(work_store)
    target_registry = ModelTargetRegistry(ModelAdapterRegistry())
    targets_before = target_registry.all()
    model_result = ModelProviderStateSource(
        target_registry,
        routing_store,
    ).read(
        SystemStateReadRequestV1(
            requested_namespaces=("model_routing",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="model_target",
                    target_identity="missing.target",
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert target_registry.all() == targets_before
    assert routing_store.get_health("missing.target") is None
    assert model_result.status is SystemStateSourceStatus.INCOMPLETE

    resources = ResourceLeaseManager({"cpu": 2})
    resource_before = resources.snapshot()
    resource_result = ResourceStateSource(resources).read(
        SystemStateReadRequestV1(
            requested_namespaces=("resource",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="resource",
                    target_identity="cpu",
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert resources.snapshot() == resource_before
    assert resource_result.status is SystemStateSourceStatus.COMPLETE
    assert resource_result.facts[0].value_json == {
        "capacity": 2,
        "available": 2,
        "in_use": 0,
    }

    deployment = DeploymentMetadataStore(tmp_path / "deployment")
    release = ReleaseRecord(
        release_sha=RELEASE_SHA,
        release_root=str(tmp_path / "release"),
        promotion_attempt_id="promotion_phase10a_test",
        promotion_evidence_digest=DIGEST_A,
        config_digest=DIGEST_B,
        schema_versions=(("autonomy", 1),),
        accepted_at_epoch=NOW - 100,
    )
    deployment.set_active(release)
    active_before = deployment.active()
    production_result = ProductionObservationSource(deployment).read(
        SystemStateReadRequestV1(
            requested_namespaces=("production",),
            targets=(
                SystemStateTargetV1(
                    target_namespace="production_release",
                    target_identity="active",
                ),
            ),
            now_epoch=NOW,
        )
    )
    assert deployment.active() == active_before
    assert production_result.status is SystemStateSourceStatus.COMPLETE
    assert production_result.facts[0].value_json["release_sha"] == RELEASE_SHA


def test_system_state_snapshot_persistence_uses_workstore_payload_protection(
    tmp_path: Path,
) -> None:
    codec = ProtectedWorkPayloadCodec(b"s" * 32)
    work_store = SQLiteWorkStore(
        tmp_path / "work.sqlite3",
        payload_codec=codec,
    )
    autonomy = AutonomyStore(work_store)
    fact = _fact(value={"marker": "sensitive-system-state-marker"})
    snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=("alpha",),
        facts=(fact,),
        source_errors=(),
        incomplete_namespaces=(),
        started_at_epoch=NOW,
        ended_at_epoch=NOW,
    )

    assert autonomy.record_system_snapshot(snapshot) == snapshot
    assert autonomy.record_system_snapshot(snapshot) == snapshot
    assert autonomy.require_system_snapshot(snapshot.snapshot_id) == snapshot

    with sqlite3.connect(work_store.path) as db:
        row = db.execute(
            """
            SELECT snapshot_digest, payload
            FROM autonomy_system_snapshots
            WHERE snapshot_id=?
            """,
            (snapshot.snapshot_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == snapshot.snapshot_digest
        assert row[1].startswith("enc:v1:")
        assert "sensitive-system-state-marker" not in row[1]

        db.execute(
            """
            UPDATE autonomy_system_snapshots
            SET snapshot_digest=?
            WHERE snapshot_id=?
            """,
            ("0" * 64, snapshot.snapshot_id),
        )
        db.commit()

    with pytest.raises(AutonomyIntegrityError, match="digest column"):
        autonomy.require_system_snapshot(snapshot.snapshot_id)
