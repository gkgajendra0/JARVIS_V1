from __future__ import annotations

import json
import pathlib
from dataclasses import replace

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_registry.compatibility import CapabilityCompatibilityEvaluator
from jarvis.capability_registry.contracts import (
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityManagementMode,
    CapabilityRegistryProjection,
    CapabilitySelfModelProjection,
    CapabilityTransitionFence,
)
from jarvis.capability_registry.provider import (
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
)
from jarvis.capability_registry.reconciliation import (
    CapabilityHealthBridge,
    CapabilityLifecycleReconciler,
    PeriodicCapabilityReconciler,
    ReconciliationTrigger,
)
from jarvis.capability_registry.source import ReleaseCapabilityPackageSource
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.release import ReleaseRecord
from jarvis.self_model.defaults import build_default_self_model
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState

RELEASE_SHA = "a" * 40
PROMOTION_DIGEST = "b" * 64
CONFIG_DIGEST = "c" * 64
NOW = 1_800_000_000.0


class RecordingAuthority:
    def __init__(self) -> None:
        self.authorize_calls = 0
        self.consume_calls = 0
        self.audit_calls = 0

    def authorize(self, prepared):
        self.authorize_calls += 1
        return object()

    def consume(self, authorized) -> None:
        self.consume_calls += 1

    def audit_result(
        self, *, session_id: str, authorized, result: CapabilityResult
    ) -> None:
        self.audit_calls += 1

    def close(self) -> None:
        return None


class FakeExecutor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.capability_key = descriptor.key
        self.operations = descriptor.operations
        self.prepare_calls = 0
        self.execute_calls = 0

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        self.prepare_calls += 1
        return PreparedCapability(
            request=request,
            target={"kind": "phase8_test"},
            parameters=dict(request.parameters),
            material_summary="Phase 8 deterministic test execution.",
            attributes=ActionAttributes(),
            execution_payload={},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        self.execute_calls += 1
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={"ok": True},
        )


class HealthyProbe:
    probe_id = "health.example.v1"

    def __init__(self) -> None:
        self.calls = 0

    def observe(self, *, component_id: str) -> HealthObservation:
        self.calls += 1
        return HealthObservation.create(
            component_id=component_id,
            source=f"capability_probe:{self.probe_id}",
            state=HealthState.HEALTHY,
            reason_code="probe_healthy",
            summary="Harmless deterministic package probe is healthy.",
            ttl_seconds=60.0,
            observed_at_epoch=NOW,
        )


class StaleProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        return HealthObservation.create(
            component_id=component_id,
            source=f"capability_probe:{self.probe_id}",
            state=HealthState.HEALTHY,
            reason_code="probe_was_healthy",
            summary="Intentionally stale package health evidence.",
            ttl_seconds=1.0,
            observed_at_epoch=NOW - 100.0,
        )


class FailedProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        raise RuntimeError("deterministic test probe failure")


def _release(tmp_path) -> ReleaseRecord:
    root = tmp_path / "release"
    root.mkdir(parents=True, exist_ok=True)
    return ReleaseRecord(
        release_sha=RELEASE_SHA,
        release_root=str(root),
        promotion_attempt_id="promotion_phase8d_test",
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        manifest_id="manifest.example.v1",
        manifest_version=1,
        capability_id="example.capability",
        capability_version="1.0.0",
        purpose="Harmless deterministic Phase-8 runtime projection test.",
        adapter_id="example.adapter.v1",
        executor_id="example.executor.v1",
        operations=("ping",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=(),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=("linux-amd64",),
        resource_requirements=(),
        health_probe_ids=("health.example.v1",),
        verification_contract_ids=("verify.example.v1",),
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="disable.example.v1",
    )


def _manifest_registry(manifest: CapabilityManifest) -> CapabilityManifestRegistry:
    registry = CapabilityManifestRegistry(
        executors=(
            TrustedExecutorRegistration(
                executor_id="example.executor.v1",
                adapter_ids=("example.adapter.v1",),
                operations=("ping",),
                authority_attribute_floor=(),
                allowed_secret_scopes=(),
                sandbox_profile_ids=(),
            ),
        ),
        adapters=(
            TrustedAdapterRegistration(
                adapter_id="example.adapter.v1",
                operations=("ping",),
            ),
        ),
        references=ManifestReferenceCatalog(
            verification_contract_ids=("verify.example.v1",),
            disable_rollback_contract_ids=("disable.example.v1",),
            health_probe_ids=("health.example.v1",),
            platform_constraint_ids=("linux-amd64",),
        ),
    )
    registry.register(manifest)
    return registry


def _package(manifest: CapabilityManifest) -> CapabilityPackageV1:
    return parse_capability_package_v1(
        {
            "schema_version": 1,
            "package_id": "example.package",
            "package_version": "1.0.0",
            "capability_id": manifest.capability_id,
            "package_kind": "extension_source",
            "manifest_id": manifest.manifest_id,
            "manifest_version": manifest.manifest_version,
            "manifest_digest": canonical_digest(manifest),
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": 1,
            "artifacts": [],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _descriptor(
    *,
    capability_id: str = "example.capability",
    source_id: str = "phase8.test",
    operation: str = "ping",
    enabled: bool = True,
) -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id=capability_id,
        source_id=source_id,
        kind=CapabilityKind.NATIVE_API,
        name=f"Test {capability_id}",
        description="Harmless deterministic test descriptor.",
        operations=(operation,),
        execution_enabled=enabled,
    )


def _write_package(release: ReleaseRecord, package: CapabilityPackageV1) -> None:
    root = pathlib.Path(release.release_root) / "capability_packages"
    root.mkdir(parents=True, exist_ok=True)
    (root / "example.json").write_text(
        json.dumps(package.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )


def _environment(tmp_path, *, probe=None):
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    descriptor = _descriptor()
    executor = FakeExecutor(descriptor)
    selected_probe = HealthyProbe() if probe is None else probe
    provider = CapabilityProviderRegistration(
        capability_id=manifest.capability_id,
        executor_id=manifest.executor_id,
        adapter_id=manifest.adapter_id,
        descriptor=descriptor,
        executor=executor,
        release_sha=RELEASE_SHA,
        health_probes=(selected_probe,),
    )
    providers = CapabilityProviderRegistry((provider,))
    source = ReleaseCapabilityPackageSource(release)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry(manifest),
        provider_registry=providers,
        artifact_store=artifacts,
        package_source=source,
        runtime_release_sha=RELEASE_SHA,
        platform_tags=("linux-amd64",),
    )
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    store.admit_package(
        package,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest=evaluator.evaluate_package(package).digest,
    )
    health = HealthRegistry()
    fence = CapabilityTransitionFence()
    projection = CapabilityRegistryProjection(
        provider_registry=providers,
        transition_fence=fence,
    )
    reconciler = CapabilityLifecycleReconciler(
        store=store,
        evaluator=evaluator,
        provider_registry=providers,
        health_registry=health,
        projection=projection,
        health_bridge=CapabilityHealthBridge(
            health,
            clock=lambda: NOW,
            ttl_seconds=60.0,
        ),
        clock=lambda: NOW,
    )
    return {
        "manifest": manifest,
        "package": package,
        "descriptor": descriptor,
        "executor": executor,
        "probe": selected_probe,
        "providers": providers,
        "source": source,
        "evaluator": evaluator,
        "store": store,
        "health": health,
        "fence": fence,
        "projection": projection,
        "reconciler": reconciler,
    }


def _enable(env) -> None:
    state = env["store"].require_registry("example.capability")
    env["store"].transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id="example.package",
        selected_package_version="1.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="phase8d_test_enable",
    )


def _runtime(env, *, include_core: bool = False):
    descriptors = [env["descriptor"]]
    executors = [env["executor"]]
    core_executor = None
    if include_core:
        core_descriptor = _descriptor(
            capability_id="core.capability",
            source_id="core",
            operation="core_ping",
        )
        core_executor = FakeExecutor(core_descriptor)
        descriptors.append(core_descriptor)
        executors.append(core_executor)
    authority = RecordingAuthority()
    runtime = CapabilityRuntime(
        executors=tuple(executors),
        resolver=CapabilityResolver((), builtins=tuple(descriptors)),
        authority=authority,
        catalog_projection=env["projection"],
    )
    return runtime, authority, core_executor


def test_desired_disabled_projects_disabled_health_and_no_routing(tmp_path) -> None:
    env = _environment(tmp_path)

    snapshot = env["reconciler"].reconcile(ReconciliationTrigger.STARTUP)
    state = snapshot.state("example.capability")

    assert state is not None
    assert state.desired_state is DesiredActivationState.DISABLED
    assert state.health_state is HealthState.DISABLED
    assert not state.effective_enabled
    assert not env["projection"].allows(env["descriptor"].key)


def test_enabled_ready_healthy_package_becomes_effectively_routable(tmp_path) -> None:
    env = _environment(tmp_path)
    _enable(env)

    snapshot = env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    state = snapshot.state("example.capability")

    assert state is not None
    assert state.effective_enabled
    assert state.health_state is HealthState.HEALTHY
    assert state.registry_generation == state.applied_generation == 2
    assert env["projection"].allows(env["descriptor"].key)
    assert env["probe"].calls == 1


@pytest.mark.parametrize("probe", [StaleProbe(), FailedProbe()])
def test_missing_or_failed_fresh_health_blocks_effective_execution(
    tmp_path,
    probe,
) -> None:
    env = _environment(tmp_path, probe=probe)
    _enable(env)

    snapshot = env["reconciler"].reconcile(ReconciliationTrigger.HEALTH)
    state = snapshot.state("example.capability")

    assert state is not None
    assert not state.effective_enabled
    assert state.health_state in {HealthState.UNKNOWN, HealthState.FAILED}


def test_transition_fence_blocks_cached_routing_before_durable_mutation(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    _enable(env)
    env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    runtime, authority, _ = _runtime(env)
    assert runtime.refresh_catalog().by_key(env["descriptor"].key).execution_enabled
    assert runtime.capability_for_operation("ping") == env["descriptor"].key

    with env["fence"].hold("example.capability"):
        assert not env["projection"].allows(env["descriptor"].key)
        assert runtime.capability_for_operation("ping") is None
        result = runtime.execute(
            CapabilityRequest(
                session_id="phase8d",
                capability_key=env["descriptor"].key,
                operation="ping",
                parameters={},
            )
        )

    assert result.status is CapabilityStatus.UNAVAILABLE
    assert "lifecycle projection" in (result.reason or "")
    assert authority.authorize_calls == 0
    assert env["executor"].prepare_calls == 0


def test_stale_applied_generation_fails_closed_without_sqlite_read(tmp_path) -> None:
    env = _environment(tmp_path)
    _enable(env)
    snapshot = env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    current = snapshot.state("example.capability")
    assert current is not None
    stale = replace(
        current,
        applied_generation=current.registry_generation - 1,
        effective_enabled=True,
    )
    env["projection"].install(replace(snapshot, states=(stale,)))

    def _unexpected_db_read(*args, **kwargs):
        raise AssertionError("hot routing path must not read SQLite")

    env["store"].get_registry = _unexpected_db_read
    env["store"].list_registry = _unexpected_db_read
    assert not env["projection"].allows(env["descriptor"].key)

    runtime, authority, _ = _runtime(env)
    runtime.refresh_catalog()
    result = runtime.execute(
        CapabilityRequest(
            session_id="phase8d",
            capability_key=env["descriptor"].key,
            operation="ping",
            parameters={},
        )
    )

    assert result.status is CapabilityStatus.UNAVAILABLE
    assert authority.authorize_calls == 0


def test_core_pinned_capability_is_not_filtered_by_package_projection(tmp_path) -> None:
    env = _environment(tmp_path)
    runtime, authority, core = _runtime(env, include_core=True)
    catalog = runtime.refresh_catalog()

    package_descriptor = catalog.by_key(env["descriptor"].key)
    assert package_descriptor is not None
    assert not package_descriptor.execution_enabled

    assert core is not None
    core_descriptor = catalog.by_key(core.descriptor.key)
    assert core_descriptor is not None
    assert core_descriptor.execution_enabled
    result = runtime.execute(
        CapabilityRequest(
            session_id="phase8d",
            capability_key=core.descriptor.key,
            operation="core_ping",
            parameters={},
        )
    )
    assert result.status is CapabilityStatus.SUCCEEDED
    assert authority.authorize_calls == 1


def test_inventory_distinguishes_core_pinned_and_package_managed(tmp_path) -> None:
    env = _environment(tmp_path)
    runtime, _, core = _runtime(env, include_core=True)
    catalog = runtime.refresh_catalog()

    inventory = env["projection"].inventory(catalog)
    modes = {item.capability_key: item.management_mode for item in inventory}

    assert modes[env["descriptor"].key] is CapabilityManagementMode.PACKAGE_MANAGED
    assert core is not None
    assert modes[core.descriptor.key] is CapabilityManagementMode.CORE_PINNED


def test_runtime_executes_ready_package_without_reconsulting_store(tmp_path) -> None:
    env = _environment(tmp_path)
    _enable(env)
    env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    runtime, authority, _ = _runtime(env)
    runtime.refresh_catalog()

    def _unexpected_db_read(*args, **kwargs):
        raise AssertionError("normal invocation must use the in-process projection")

    env["store"].get_registry = _unexpected_db_read
    env["store"].list_registry = _unexpected_db_read
    result = runtime.execute(
        CapabilityRequest(
            session_id="phase8d",
            capability_key=env["descriptor"].key,
            operation="ping",
            parameters={"x": 1},
        )
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert env["executor"].execute_calls == 1
    assert authority.authorize_calls == 1
    assert authority.consume_calls == 1
    assert authority.audit_calls == 1


def test_reconcile_failure_keeps_package_routing_fail_closed(
    tmp_path, monkeypatch
) -> None:
    env = _environment(tmp_path)
    _enable(env)
    env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    assert env["projection"].allows(env["descriptor"].key)

    def _fail(_package):
        raise RuntimeError("synthetic compatibility failure")

    monkeypatch.setattr(env["evaluator"], "evaluate", _fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        env["reconciler"].reconcile(ReconciliationTrigger.PERIODIC)

    assert not env["projection"].allows(env["descriptor"].key)
    state = env["projection"].snapshot.state("example.capability")
    assert state is not None
    assert "reconciliation_failed" in state.reason_codes


def test_restart_reconciliation_restores_durable_enabled_truth(tmp_path) -> None:
    env = _environment(tmp_path)
    _enable(env)
    first = env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)
    assert first.state("example.capability").effective_enabled

    restarted_store = CapabilityRegistryStore(env["store"].path)
    restarted_health = HealthRegistry()
    restarted_projection = CapabilityRegistryProjection(
        provider_registry=env["providers"],
    )
    restarted = CapabilityLifecycleReconciler(
        store=restarted_store,
        evaluator=env["evaluator"],
        provider_registry=env["providers"],
        health_registry=restarted_health,
        projection=restarted_projection,
        health_bridge=CapabilityHealthBridge(
            restarted_health,
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
    )

    recovered = restarted.reconcile(ReconciliationTrigger.STARTUP)

    assert recovered.state("example.capability").effective_enabled
    assert restarted_projection.allows(env["descriptor"].key)


def test_package_state_projects_dynamic_self_model_component(tmp_path) -> None:
    env = _environment(tmp_path)
    _enable(env)
    snapshot = env["reconciler"].reconcile(ReconciliationTrigger.LIFECYCLE)

    projected = CapabilitySelfModelProjection().project(
        build_default_self_model(),
        snapshot,
    )
    state = snapshot.state("example.capability")
    assert state is not None
    component = projected.component(state.component_id)

    assert component is not None
    assert component.parent_component_id == "capability_runtime"
    assert component.health_surface
    assert component.capability_keys == (env["descriptor"].key,)
    assert component.health_probes == ("health.example.v1",)


def test_periodic_reconciler_run_once_and_interval_bounds(tmp_path) -> None:
    env = _environment(tmp_path)
    periodic = PeriodicCapabilityReconciler(
        env["reconciler"],
        interval_seconds=30.0,
    )

    snapshot = periodic.run_once()

    assert snapshot.trigger == ReconciliationTrigger.PERIODIC.value
    assert not periodic.last_run_failed
    with pytest.raises(ValueError, match="5..3600"):
        PeriodicCapabilityReconciler(
            env["reconciler"],
            interval_seconds=1.0,
        )


def test_discovery_only_descriptor_stays_execution_disabled(tmp_path) -> None:
    env = _environment(tmp_path)
    discovery_only = _descriptor(
        capability_id="discovery.only",
        source_id="discovered",
        operation="observe",
        enabled=False,
    )
    resolver = CapabilityResolver((), builtins=(discovery_only,))
    base = resolver.refresh()
    projected = env["projection"].project(base)

    descriptor = projected.by_key(discovery_only.key)
    assert descriptor is not None
    assert not descriptor.execution_enabled
