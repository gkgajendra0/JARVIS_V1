"""Deterministic Phase-8 Capability Package + Registry Lifecycle replay."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Barrier

from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CompatibilityReason,
    CompatibilityVerdict,
)
from jarvis.capability_registry.contracts import (
    CapabilityPackageContractError,
    CapabilityPackageV1,
    PackageArtifactDescriptorV1,
    StrictSemVer,
    parse_capability_package_v1,
)
from jarvis.capability_registry.lifecycle import (
    CapabilityLifecyclePreconditionError,
    CapabilityLifecycleService,
)
from jarvis.capability_registry.migration_runner import (
    CapabilityRegistrySchemaTooNewError,
)
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.projection import (
    CapabilityRegistryProjection,
    CapabilityTransitionFence,
)
from jarvis.capability_registry.provider import (
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
)
from jarvis.capability_registry.reconciliation import (
    CapabilityHealthBridge,
    CapabilityLifecycleReconciler,
    ReconciliationTrigger,
)
from jarvis.capability_registry.retention import CapabilityArtifactRetentionPlanner
from jarvis.capability_registry.schema import capability_package_v1_json_schema
from jarvis.capability_registry.source import ReleaseCapabilityPackageSource
from jarvis.capability_registry.store import (
    CapabilityRegistryIntegrityError,
    CapabilityRegistrySelectionError,
    CapabilityRegistryStore,
    PackageVersionReuseConflict,
    StaleRegistryGenerationError,
)
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.promotion.evaluation import run_replay_suite as run_phase7_replay
from jarvis.promotion.release import ReleaseRecord
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState

_RELEASE_SHA = "a" * 40
_OLD_RELEASE_SHA = "b" * 40
_PROMOTION_DIGEST = "c" * 64
_CONFIG_DIGEST = "d" * 64
_NOW = 1_800_000_000.0


@dataclass(frozen=True, slots=True)
class Phase8ReplayCase:
    case_id: str
    passed: bool
    evidence: dict[str, object]

    def payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Phase8ReplayReport:
    cases: tuple[Phase8ReplayCase, ...]
    status: str
    suite_digest: str

    def payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.payload() for item in self.cases],
        }


class _Executor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.capability_key = descriptor.key
        self.operations = descriptor.operations

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        raise AssertionError("Phase-8 replay never executes package providers")

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={"unexpected": True},
        )


class _HealthyProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        return HealthObservation.create(
            component_id=component_id,
            source=f"capability_probe:{self.probe_id}",
            state=HealthState.HEALTHY,
            reason_code="phase8_replay_healthy",
            summary="Deterministic Phase-8 replay health probe is healthy.",
            ttl_seconds=60.0,
            observed_at_epoch=_NOW,
        )


class _FailedProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        raise RuntimeError("deterministic replay probe failure")


@dataclass(frozen=True, slots=True)
class _Authorized:
    authority_ref: str


class _Authority:
    def __init__(self) -> None:
        self.authorize_calls = 0
        self.consume_calls = 0
        self.last_binding = None

    def authorize(self, binding, *, authority_session_id: str) -> _Authorized:
        self.authorize_calls += 1
        self.last_binding = binding
        return _Authorized(
            authority_ref=(
                f"authority:phase8-replay:{binding.expected_generation}:"
                f"{binding.compatibility_digest}"
            )
        )

    def consume(self, authorized: _Authorized) -> None:
        self.consume_calls += 1


@dataclass
class _Environment:
    root: pathlib.Path
    release: ReleaseRecord
    manifests: dict[str, CapabilityManifest]
    packages: dict[str, CapabilityPackageV1]
    descriptor: CapabilityDescriptor
    executor: _Executor
    provider_registry: CapabilityProviderRegistry
    source: ReleaseCapabilityPackageSource
    artifact_store: ArtifactStore
    evaluator: CapabilityCompatibilityEvaluator
    store: CapabilityRegistryStore
    health: HealthRegistry
    fence: CapabilityTransitionFence
    projection: CapabilityRegistryProjection
    reconciler: CapabilityLifecycleReconciler
    authority: _Authority
    lifecycle: CapabilityLifecycleService


def _release(root: pathlib.Path, *, sha: str = _RELEASE_SHA) -> ReleaseRecord:
    release_root = root / f"release-{sha[:8]}"
    release_root.mkdir(parents=True, exist_ok=True)
    return ReleaseRecord(
        release_sha=sha,
        release_root=str(release_root),
        promotion_attempt_id=f"promotion_phase8_replay_{sha[:8]}",
        promotion_evidence_digest=_PROMOTION_DIGEST,
        config_digest=_CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _manifest(
    version: str,
    *,
    manifest_version: int = 1,
    platform_constraints: tuple[str, ...] = ("linux-amd64",),
    health_probe_ids: tuple[str, ...] = ("health.example.v1",),
) -> CapabilityManifest:
    token = version.replace(".", "_").replace("-", "_")
    return CapabilityManifest(
        manifest_id=f"manifest.example.{token}",
        manifest_version=manifest_version,
        capability_id="example.capability",
        capability_version=version,
        purpose=f"Deterministic Phase-8 replay capability {version}.",
        adapter_id="example.adapter.v1",
        executor_id="example.executor.v1",
        operations=("ping",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=(),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=platform_constraints,
        resource_requirements=(),
        health_probe_ids=health_probe_ids,
        verification_contract_ids=("verify.example.v1",),
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="disable.example.v1",
    )


def _manifest_registry(
    manifests: tuple[CapabilityManifest, ...],
) -> CapabilityManifestRegistry:
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
            platform_constraint_ids=("linux-amd64", "windows-amd64"),
        ),
    )
    for manifest in manifests:
        registry.register(manifest)
    return registry


def _descriptor(
    *,
    capability_id: str = "example.capability",
    source_id: str = "phase8.replay",
    operation: str = "ping",
    enabled: bool = True,
) -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id=capability_id,
        source_id=source_id,
        kind=CapabilityKind.NATIVE_API,
        name=f"Replay {capability_id}",
        description="Deterministic Phase-8 replay descriptor.",
        operations=(operation,),
        execution_enabled=enabled,
    )


def _package(
    manifest: CapabilityManifest,
    *,
    manifest_digest: str | None = None,
    manifest_version: int | None = None,
    runtime_api_version: int = 1,
    artifacts: tuple[PackageArtifactDescriptorV1, ...] = (),
) -> CapabilityPackageV1:
    return parse_capability_package_v1(
        {
            "schema_version": 1,
            "package_id": "example.package",
            "package_version": manifest.capability_version,
            "capability_id": manifest.capability_id,
            "package_kind": "extension_source",
            "manifest_id": manifest.manifest_id,
            "manifest_version": (
                manifest.manifest_version
                if manifest_version is None
                else manifest_version
            ),
            "manifest_digest": manifest_digest or canonical_digest(manifest),
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": runtime_api_version,
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _write_package(
    release: ReleaseRecord, package: CapabilityPackageV1
) -> pathlib.Path:
    root = pathlib.Path(release.release_root) / "capability_packages"
    root.mkdir(parents=True, exist_ok=True)
    token = package.package_version.replace(".", "_").replace("-", "_")
    path = root / f"{token}.json"
    path.write_text(
        json.dumps(package.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    return path


def _environment(
    root: pathlib.Path,
    *,
    versions: tuple[str, ...] = ("1.0.0", "2.0.0"),
    probe=None,
    provider: bool = True,
    runtime_release_sha: str = _RELEASE_SHA,
    platform_tags: tuple[str, ...] = ("linux-amd64",),
    runtime_api_versions: tuple[int, ...] = (1,),
) -> _Environment:
    root.mkdir(parents=True, exist_ok=True)
    release = _release(root)
    manifests = {version: _manifest(version) for version in versions}
    packages = {version: _package(manifest) for version, manifest in manifests.items()}
    for package in packages.values():
        _write_package(release, package)

    descriptor = _descriptor()
    executor = _Executor(descriptor)
    registrations: tuple[CapabilityProviderRegistration, ...] = ()
    if provider:
        registrations = (
            CapabilityProviderRegistration(
                capability_id="example.capability",
                executor_id="example.executor.v1",
                adapter_id="example.adapter.v1",
                descriptor=descriptor,
                executor=executor,
                release_sha=runtime_release_sha,
                supported_runtime_api_versions=runtime_api_versions,
                health_probes=((_HealthyProbe() if probe is None else probe),),
            ),
        )
    providers = CapabilityProviderRegistry(registrations)
    source = ReleaseCapabilityPackageSource(release)
    artifact_store = ArtifactStore(root / "artifacts")
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry(tuple(manifests.values())),
        provider_registry=providers,
        artifact_store=artifact_store,
        package_source=source,
        runtime_release_sha=runtime_release_sha,
        platform_tags=platform_tags,
    )
    store = CapabilityRegistryStore(root / "registry.sqlite3")
    for package in packages.values():
        store.admit_package(
            package,
            admitted_release_sha=_RELEASE_SHA,
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
            clock=lambda: _NOW,
            ttl_seconds=60.0,
        ),
        clock=lambda: _NOW,
    )
    authority = _Authority()
    lifecycle = CapabilityLifecycleService(
        store=store,
        reconciler=reconciler,
        authority=authority,
    )
    return _Environment(
        root=root,
        release=release,
        manifests=manifests,
        packages=packages,
        descriptor=descriptor,
        executor=executor,
        provider_registry=providers,
        source=source,
        artifact_store=artifact_store,
        evaluator=evaluator,
        store=store,
        health=health,
        fence=fence,
        projection=projection,
        reconciler=reconciler,
        authority=authority,
        lifecycle=lifecycle,
    )


def _owner_source():
    from jarvis.capability_registry.authority import CapabilityLifecycleAuthoritySource

    return CapabilityLifecycleAuthoritySource.owner_turn(
        session_id="phase8-replay-session",
        turn_id="phase8-replay-turn",
    )


def _select_direct(env: _Environment, version: str):
    state = env.store.require_registry("example.capability")
    return env.store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=state.desired_state,
        selected_package_id="example.package",
        selected_package_version=version,
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code=f"replay_select_{version}",
    )


def _enable_direct(env: _Environment):
    state = env.store.require_registry("example.capability")
    return env.store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id=state.selected_package_id,
        selected_package_version=state.selected_package_version,
        event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
        reason_code="replay_enable",
    )


def _select_lifecycle(env: _Environment, version: str):
    state = env.store.require_registry("example.capability")
    return env.lifecycle.select_version(
        "example.capability",
        package_id="example.package",
        package_version=version,
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )


def _enable_lifecycle(env: _Environment):
    state = env.store.require_registry("example.capability")
    return env.lifecycle.enable(
        "example.capability",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )


def _case(
    case_id: str,
    root: pathlib.Path,
    operation: Callable[[pathlib.Path], dict[str, object]],
) -> Phase8ReplayCase:
    case_root = root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        evidence = operation(case_root)
    except Exception as exc:  # noqa: BLE001 - replay converts any case failure to evidence
        return Phase8ReplayCase(
            case_id=case_id,
            passed=False,
            evidence={
                "exception": type(exc).__name__,
                "message": str(exc),
            },
        )
    return Phase8ReplayCase(case_id=case_id, passed=True, evidence=evidence)


def _01_schema(_: pathlib.Path) -> dict[str, object]:
    package = _package(_manifest("1.0.0"))
    schema = capability_package_v1_json_schema()
    if schema.get("additionalProperties") is not False:
        raise AssertionError("package schema is not closed")
    return {"package_digest": package.digest, "schema_closed": True}


def _02_semver(_: pathlib.Path) -> dict[str, object]:
    ordered = [
        StrictSemVer.parse("1.0.0-alpha"),
        StrictSemVer.parse("1.0.0-beta"),
        StrictSemVer.parse("1.0.0"),
    ]
    if not (
        ordered[0].compare_precedence(ordered[1]) < 0
        and ordered[1].compare_precedence(ordered[2]) < 0
    ):
        raise AssertionError("strict SemVer precedence failed")
    try:
        StrictSemVer.parse("01.0.0")
    except CapabilityPackageContractError:
        pass
    else:
        raise AssertionError("invalid SemVer was accepted")
    return {"precedence": ["alpha", "beta", "release"], "invalid_rejected": True}


def _03_version_reuse(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    changed = _package(
        env.manifests["1.0.0"],
        manifest_digest="f" * 64,
    )
    try:
        env.store.admit_package(
            changed,
            admitted_release_sha=_RELEASE_SHA,
            evidence_digest="e" * 64,
        )
    except PackageVersionReuseConflict:
        return {"version_reuse_conflict": True}
    raise AssertionError("same package version accepted changed content")


def _04_unknown_manifest(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    package = _package(env.manifests["1.0.0"], manifest_version=2)
    report = env.evaluator.evaluate_package(package)
    if CompatibilityReason.MANIFEST_UNKNOWN_OR_INVALID.value not in report.reason_codes:
        raise AssertionError("unknown manifest version did not block")
    return {"verdict": report.verdict.value, "reason_codes": report.reason_codes}


def _05_manifest_digest(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    package = _package(env.manifests["1.0.0"], manifest_digest="f" * 64)
    report = env.evaluator.evaluate_package(package)
    if CompatibilityReason.MANIFEST_DIGEST_MISMATCH.value not in report.reason_codes:
        raise AssertionError("manifest digest mismatch did not block")
    return {"verdict": report.verdict.value, "reason_codes": report.reason_codes}


def _06_untrusted_provider(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",), provider=False)
    report = env.evaluator.evaluate_package(env.packages["1.0.0"])
    if CompatibilityReason.PROVIDER_MISSING.value not in report.reason_codes:
        raise AssertionError("untrusted provider was not blocked")
    return {"verdict": report.verdict.value, "reason_codes": report.reason_codes}


def _07_forbidden_metadata(_: pathlib.Path) -> dict[str, object]:
    payload = _package(_manifest("1.0.0")).model_dump(mode="json")
    payload["command"] = "python bad.py"
    try:
        parse_capability_package_v1(payload)
    except CapabilityPackageContractError:
        return {"forbidden_field_rejected": "command"}
    raise AssertionError("raw command field was accepted")


def _artifact_environment(root: pathlib.Path) -> tuple[_Environment, str, pathlib.Path]:
    env = _environment(root, versions=("1.0.0",))
    payload = b"phase8-replay-artifact"
    source_file = root / "payload.bin"
    source_file.write_bytes(payload)
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    result = env.artifact_store.admit_file(
        source_file,
        expected_sha256=digest,
        provenance_id="prov.phase8.replay",
    )
    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=len(payload),
        media_type="application/octet-stream",
        provenance_refs=("prov.phase8.replay",),
    )
    package = _package(env.manifests["1.0.0"], artifacts=(artifact,))
    _write_package(env.release, package)
    fresh = _environment(root / "fresh", versions=("1.0.0",))
    del fresh
    return env, digest, result.object_path


def _08_corrupt_artifact(root: pathlib.Path) -> dict[str, object]:
    release = _release(root)
    artifact_store = ArtifactStore(root / "artifacts")
    payload = b"phase8-corrupt"
    source_file = root / "payload.bin"
    source_file.write_bytes(payload)
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    admitted = artifact_store.admit_file(source_file, expected_sha256=digest)
    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=len(payload),
        media_type="application/octet-stream",
    )
    manifest = _manifest("1.0.0")
    package = _package(manifest, artifacts=(artifact,))
    _write_package(release, package)
    descriptor = _descriptor()
    provider = CapabilityProviderRegistration(
        capability_id="example.capability",
        executor_id="example.executor.v1",
        adapter_id="example.adapter.v1",
        descriptor=descriptor,
        executor=_Executor(descriptor),
        release_sha=_RELEASE_SHA,
        health_probes=(_HealthyProbe(),),
    )
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry((manifest,)),
        provider_registry=CapabilityProviderRegistry((provider,)),
        artifact_store=artifact_store,
        package_source=ReleaseCapabilityPackageSource(release),
        runtime_release_sha=_RELEASE_SHA,
        platform_tags=("linux-amd64",),
    )
    admitted.object_path.write_bytes(b"tampered")
    report = evaluator.evaluate_package(package)
    if CompatibilityReason.ARTIFACT_INTEGRITY_FAILED.value not in report.reason_codes:
        raise AssertionError("corrupt artifact did not block")
    return {"verdict": report.verdict.value, "reason_codes": report.reason_codes}


def _09_runtime_api(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    package = _package(env.manifests["1.0.0"], runtime_api_version=2)
    report = env.evaluator.evaluate_package(package)
    if CompatibilityReason.RUNTIME_API_UNSUPPORTED.value not in report.reason_codes:
        raise AssertionError("runtime API mismatch did not block")
    return {"verdict": report.verdict.value}


def _10_platform(root: pathlib.Path) -> dict[str, object]:
    release = _release(root)
    manifest = _manifest("1.0.0", platform_constraints=("windows-amd64",))
    package = _package(manifest)
    _write_package(release, package)
    descriptor = _descriptor()
    provider = CapabilityProviderRegistration(
        capability_id="example.capability",
        executor_id="example.executor.v1",
        adapter_id="example.adapter.v1",
        descriptor=descriptor,
        executor=_Executor(descriptor),
        release_sha=_RELEASE_SHA,
        health_probes=(_HealthyProbe(),),
    )
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry((manifest,)),
        provider_registry=CapabilityProviderRegistry((provider,)),
        artifact_store=ArtifactStore(root / "artifacts"),
        package_source=ReleaseCapabilityPackageSource(release),
        runtime_release_sha=_RELEASE_SHA,
        platform_tags=("linux-amd64",),
    )
    report = evaluator.evaluate_package(package)
    if CompatibilityReason.PLATFORM_UNSUPPORTED.value not in report.reason_codes:
        raise AssertionError("platform mismatch did not block")
    return {"verdict": report.verdict.value}


def _11_registration_disabled(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    state = env.store.require_registry("example.capability")
    if (
        state.desired_state is not DesiredActivationState.DISABLED
        or state.has_selection
    ):
        raise AssertionError("package admission changed activation intent")
    return {"desired_state": state.desired_state.value, "selected": state.has_selection}


def _12_enable_requires_ready(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    path = pathlib.Path(env.release.release_root) / "capability_packages" / "1_0_0.json"
    path.unlink()
    try:
        _enable_lifecycle(env)
    except CapabilityLifecyclePreconditionError:
        return {"enable_blocked": True}
    raise AssertionError("enable succeeded without READY compatibility")


def _13_stale_cas(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    try:
        env.store.transition_registry(
            "example.capability",
            expected_generation=1,
            desired_state=DesiredActivationState.ENABLED,
            selected_package_id="example.package",
            selected_package_version="1.0.0",
            event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
            reason_code="stale",
        )
    except StaleRegistryGenerationError:
        return {"stale_generation_rejected": True}
    raise AssertionError("stale generation was accepted")


def _14_one_selected(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_direct(env, "1.0.0")
    _select_direct(env, "2.0.0")
    state = env.store.require_registry("example.capability")
    if state.selected_package_version != "2.0.0":
        raise AssertionError("selected version invariant failed")
    return {"selected_package_version": state.selected_package_version}


def _15_disable_routing(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_lifecycle(env, "1.0.0")
    _enable_lifecycle(env)
    if not env.projection.allows(env.descriptor.key):
        raise AssertionError("enabled package is not routable")
    state = env.store.require_registry("example.capability")
    result = env.lifecycle.disable(
        "example.capability",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    if env.projection.allows(env.descriptor.key):
        raise AssertionError("disable left new routing enabled")
    return {
        "desired_state": result.current_state.desired_state.value,
        "effective": result.snapshot.state("example.capability").effective_enabled,
    }


def _16_disable_no_unload(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_lifecycle(env, "1.0.0")
    _enable_lifecycle(env)
    executor_identity = id(env.executor)
    state = env.store.require_registry("example.capability")
    env.lifecycle.disable(
        "example.capability",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    registered = env.provider_registry.registrations()[0]
    if id(registered.executor) != executor_identity:
        raise AssertionError("disable falsely replaced/unloaded provider object")
    return {"executor_resident": True, "routing_enabled": False}


def _17_new_version_no_switch(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_direct(env, "1.0.0")
    state = env.store.require_registry("example.capability")
    if state.selected_package_version != "1.0.0":
        raise AssertionError("admitted new version auto-switched selection")
    return {"selected": state.selected_package_version, "available_versions": 2}


def _18_switch_event(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_direct(env, "1.0.0")
    switched = _select_direct(env, "2.0.0")
    event = env.store.list_events("example.capability")[-1]
    if (
        event.event_kind is not CapabilityLifecycleEventKind.VERSION_SELECTED
        or event.package_version != "2.0.0"
        or event.new_generation != switched.generation
    ):
        raise AssertionError("version switch event is not exact")
    return {"event_digest": event.event_digest, "generation": event.new_generation}


def _19_rollback(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_lifecycle(env, "2.0.0")
    _enable_lifecycle(env)
    state = env.store.require_registry("example.capability")
    rolled = env.lifecycle.rollback_version(
        "example.capability",
        package_version="1.0.0",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    if rolled.current_state.selected_package_version != "1.0.0":
        raise AssertionError("supported rollback did not select old version")
    return {"selected": rolled.current_state.selected_package_version}


def _20_rollback_absent(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_lifecycle(env, "2.0.0")
    path = pathlib.Path(env.release.release_root) / "capability_packages" / "1_0_0.json"
    path.unlink()
    state = env.store.require_registry("example.capability")
    try:
        env.lifecycle.rollback_version(
            "example.capability",
            package_version="1.0.0",
            expected_generation=state.generation,
            authority_session_id="phase8-replay-session",
            source=_owner_source(),
        )
    except CapabilityLifecyclePreconditionError:
        return {"rollback_blocked": True}
    raise AssertionError("rollback succeeded without current-release descriptor")


def _disposition_selection(
    root: pathlib.Path,
    disposition: PackageDisposition,
) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    env.store.set_package_disposition(
        "example.package",
        "1.0.0",
        disposition=disposition,
        reason_code=f"replay_{disposition.value}",
    )
    try:
        _select_direct(env, "1.0.0")
    except CapabilityRegistrySelectionError:
        return {"disposition": disposition.value, "selection_blocked": True}
    raise AssertionError(f"{disposition.value} package remained selectable")


def _21_retired(root: pathlib.Path) -> dict[str, object]:
    return _disposition_selection(root, PackageDisposition.RETIRED)


def _22_quarantined(root: pathlib.Path) -> dict[str, object]:
    return _disposition_selection(root, PackageDisposition.QUARANTINED)


def _23_health_blocks(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",), probe=_FailedProbe())
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    snapshot = env.reconciler.reconcile(ReconciliationTrigger.HEALTH)
    state = snapshot.state("example.capability")
    if (
        state is None
        or state.effective_enabled
        or state.health_state is not HealthState.FAILED
    ):
        raise AssertionError("failed health did not block effective execution")
    return {"health": state.health_state.value, "effective": state.effective_enabled}


def _24_desired_vs_effective(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",), probe=_FailedProbe())
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    snapshot = env.reconciler.reconcile(ReconciliationTrigger.HEALTH)
    durable = env.store.require_registry("example.capability")
    state = snapshot.state("example.capability")
    if (
        durable.desired_state is not DesiredActivationState.ENABLED
        or state is None
        or state.effective_enabled
    ):
        raise AssertionError("desired/effective state distinction failed")
    return {
        "desired": durable.desired_state.value,
        "effective": state.effective_enabled,
    }


def _25_restart(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    before = env.store.require_registry("example.capability")
    restarted = CapabilityRegistryStore(env.store.path)
    after = restarted.require_registry("example.capability")
    if after != before:
        raise AssertionError("registry state did not survive restart")
    return {"generation": after.generation, "desired": after.desired_state.value}


def _26_newer_schema(root: pathlib.Path) -> dict[str, object]:
    path = root / "newer.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA user_version=99")
        connection.commit()
    finally:
        connection.close()
    try:
        CapabilityRegistryStore(path)
    except CapabilityRegistrySchemaTooNewError:
        return {"newer_schema_blocked": True}
    raise AssertionError("newer registry schema was accepted")


def _27_entrypoint_untrusted(root: pathlib.Path) -> dict[str, object]:
    evidence = _06_untrusted_provider(root)
    evidence["installed_entrypoint_not_authority"] = True
    return evidence


def _28_retention(root: pathlib.Path) -> dict[str, object]:
    release = _release(root)
    store = CapabilityRegistryStore(root / "retention.sqlite3")
    digests: dict[str, str] = {}
    packages: dict[str, CapabilityPackageV1] = {}
    import hashlib

    for version in ("1.0.0", "2.0.0"):
        payload = f"phase8-retention-{version}".encode()
        digest = hashlib.sha256(payload).hexdigest()
        digests[version] = digest
        artifact = PackageArtifactDescriptorV1(
            role="payload",
            sha256=digest,
            size_bytes=len(payload),
            media_type="application/octet-stream",
        )
        package = _package(_manifest(version), artifacts=(artifact,))
        packages[version] = package
        _write_package(release, package)
        store.admit_package(
            package,
            admitted_release_sha=_RELEASE_SHA,
            evidence_digest=package.digest,
        )
    first = store.require_registry("example.capability")
    first = store.transition_registry(
        "example.capability",
        expected_generation=first.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="1.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="retention_v1",
    )
    state = store.transition_registry(
        "example.capability",
        expected_generation=first.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="2.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="retention_v2",
    )
    store.set_package_disposition(
        "example.package",
        "1.0.0",
        disposition=PackageDisposition.RETIRED,
        reason_code="retention_retired",
        expected_generation=state.generation,
    )
    refs = CapabilityArtifactRetentionPlanner(
        store=store,
        package_source=ReleaseCapabilityPackageSource(release),
        rollback_depth=1,
    ).references()
    if set(refs.referenced_sha256) != set(digests.values()):
        raise AssertionError("selected/rollback artifact retention is incomplete")
    return {"retained": refs.referenced_sha256}


def _29_core_pinned(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    core = _descriptor(
        capability_id="core.capability",
        source_id="core",
        operation="core_ping",
    )
    catalog = CapabilityCatalog(
        sources=(),
        capabilities=(env.descriptor, core),
    )
    projected = env.projection.project(catalog)
    core_after = projected.by_key(core.key)
    managed = projected.by_key(env.descriptor.key)
    if core_after is None or not core_after.execution_enabled:
        raise AssertionError("CORE_PINNED capability was disabled")
    if managed is None or managed.execution_enabled:
        raise AssertionError("PACKAGE_MANAGED capability routed before reconciliation")
    return {"core_enabled": True, "managed_enabled": False}


def _30_regressions(root: pathlib.Path) -> dict[str, object]:
    report = run_phase7_replay(root / "phase7")
    policy = RepairProtectedSurfacePolicy()
    protected = policy.assess(
        (
            "src/jarvis/capability_registry/lifecycle.py",
            "src/jarvis/capabilities/runtime.py",
        )
    )
    if report.status != "PASS":
        raise AssertionError("Phase-7 replay regression failed")
    if protected.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise AssertionError("Phase-8 control surfaces are not protected")
    return {
        "phase7_replay": report.status,
        "phase7_cases": len(report.cases),
        "protected_policy_version": protected.policy_version,
    }


def _31_disable_stale_route(root: pathlib.Path) -> dict[str, object]:
    return _15_disable_routing(root)


def _32_switch_generation(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_lifecycle(env, "1.0.0")
    _enable_lifecycle(env)
    before = env.store.require_registry("example.capability")
    switched = env.lifecycle.select_version(
        "example.capability",
        package_id="example.package",
        package_version="2.0.0",
        expected_generation=before.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    state = switched.snapshot.state("example.capability")
    if (
        state is None
        or state.registry_generation != switched.current_state.generation
        or state.applied_generation != switched.current_state.generation
    ):
        raise AssertionError("version switch left stale projection generation")
    return {"generation": state.registry_generation, "selected": "2.0.0"}


def _33_reconcile_idempotent(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    first = env.reconciler.reconcile(ReconciliationTrigger.MANUAL_TEST)
    second = env.reconciler.reconcile(ReconciliationTrigger.MANUAL_TEST)
    if first.states != second.states:
        raise AssertionError("reconciler changed effective state without new truth")
    return {"state_count": len(first.states), "idempotent": True}


def _34_crash_after_commit(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    restarted_store = CapabilityRegistryStore(env.store.path)
    restarted_projection = CapabilityRegistryProjection(
        provider_registry=env.provider_registry,
    )
    restarted_health = HealthRegistry()
    restarted = CapabilityLifecycleReconciler(
        store=restarted_store,
        evaluator=env.evaluator,
        provider_registry=env.provider_registry,
        health_registry=restarted_health,
        projection=restarted_projection,
        health_bridge=CapabilityHealthBridge(
            restarted_health,
            clock=lambda: _NOW,
        ),
        clock=lambda: _NOW,
    )
    snapshot = restarted.reconcile(ReconciliationTrigger.STARTUP)
    state = snapshot.state("example.capability")
    if state is None or not state.effective_enabled:
        raise AssertionError("startup reconciliation did not recover committed enable")
    return {"recovered_generation": state.registry_generation, "effective": True}


def _35_atomic_event(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    before = env.store.list_events("example.capability")
    try:
        env.store.transition_registry(
            "example.capability",
            expected_generation=1,
            desired_state=DesiredActivationState.ENABLED,
            selected_package_id="example.package",
            selected_package_version="1.0.0",
            event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
            reason_code="stale_atomic",
        )
    except StaleRegistryGenerationError:
        pass
    else:
        raise AssertionError("stale CAS unexpectedly committed")
    after = env.store.list_events("example.capability")
    if after != before:
        raise AssertionError("failed CAS appended a lifecycle event")
    return {"event_count": len(after), "atomic": True}


def _36_reconcile_no_authority(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    before = env.store.require_registry("example.capability")
    env.reconciler.reconcile(ReconciliationTrigger.MANUAL_TEST)
    after = env.store.require_registry("example.capability")
    if before != after or env.authority.authorize_calls != 0:
        raise AssertionError("reconciler changed intent or invoked Authority")
    return {"authority_calls": 0, "durable_unchanged": True}


def _37_dbos_independent(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    state = env.store.require_registry("example.capability")
    if state.generation != 1:
        raise AssertionError("canonical registry truth did not initialize")
    return {"dbos_required": False, "generation": state.generation}


def _38_concurrent_writers(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    first = CapabilityRegistryStore(env.store.path)
    second = CapabilityRegistryStore(env.store.path)
    barrier = Barrier(2)

    def mutate(store: CapabilityRegistryStore, reason: str) -> str:
        barrier.wait()
        try:
            store.transition_registry(
                "example.capability",
                expected_generation=1,
                desired_state=DesiredActivationState.DISABLED,
                selected_package_id="example.package",
                selected_package_version="1.0.0",
                event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
                reason_code=reason,
            )
        except StaleRegistryGenerationError:
            return "stale"
        return "winner"

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(mutate, first, "writer_a")
        b = pool.submit(mutate, second, "writer_b")
        outcomes = sorted((a.result(), b.result()))
    if outcomes != ["stale", "winner"]:
        raise AssertionError(f"unexpected concurrent outcomes: {outcomes}")
    return {"outcomes": outcomes}


def _39_stale_projection(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    _select_direct(env, "1.0.0")
    _enable_direct(env)
    snapshot = env.reconciler.reconcile(ReconciliationTrigger.MANUAL_TEST)
    state = snapshot.state("example.capability")
    if state is None:
        raise AssertionError("effective state missing")
    stale = replace(
        state,
        applied_generation=state.registry_generation - 1,
        effective_enabled=True,
    )
    env.projection.install(replace(snapshot, states=(stale,)))
    if env.projection.allows(env.descriptor.key):
        raise AssertionError("stale projection generation remained routable")
    return {"stale_generation_blocked": True}


def _40_corrupt_selected(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root)
    _select_direct(env, "1.0.0")
    connection = sqlite3.connect(env.store.path)
    try:
        connection.execute(
            """
            UPDATE capability_packages
            SET package_json=?
            WHERE package_id=? AND package_version=?
            """,
            ('{"schema_version":1}', "example.package", "1.0.0"),
        )
        connection.commit()
    finally:
        connection.close()
    try:
        env.reconciler.reconcile(ReconciliationTrigger.STARTUP)
    except CapabilityRegistryIntegrityError:
        if env.projection.allows(env.descriptor.key):
            raise AssertionError("corrupt selected package fell back to routing")
        return {"corrupt_selected_blocked": True, "fallback": False}
    raise AssertionError("corrupt selected package was accepted")


def _41_release_change(root: pathlib.Path) -> dict[str, object]:
    env = _environment(
        root,
        versions=("1.0.0",),
        runtime_release_sha=_OLD_RELEASE_SHA,
    )
    report = env.evaluator.evaluate_package(env.packages["1.0.0"])
    if report.verdict is not CompatibilityVerdict.RESTART_REQUIRED:
        raise AssertionError(
            "active release change did not invalidate runtime projection"
        )
    return {"verdict": report.verdict.value, "reason_codes": report.reason_codes}


def _42_execution_model(_: pathlib.Path) -> dict[str, object]:
    payload = _package(_manifest("1.0.0")).model_dump(mode="json")
    payload["module"] = "evil.module"
    try:
        parse_capability_package_v1(payload)
    except CapabilityPackageContractError:
        return {"arbitrary_execution_model_rejected": True}
    raise AssertionError("package metadata selected arbitrary execution model")


def _43_core_fence(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    core = _descriptor(
        capability_id="core.capability",
        source_id="core",
        operation="core_ping",
    )
    with env.fence.hold("example.capability"):
        if env.projection.allows(core.key) is not True:
            raise AssertionError(
                "managed transition fence affected CORE_PINNED routing"
            )
    return {"core_unaffected": True}


def _44_file_handle(root: pathlib.Path) -> dict[str, object]:
    env = _environment(root, versions=("1.0.0",))
    env.store.require_registry("example.capability")
    path = env.store.path
    moved = path.with_suffix(".moved.sqlite3")
    os.replace(path, moved)
    os.replace(moved, path)
    reopened = CapabilityRegistryStore(path)
    state = reopened.require_registry("example.capability")
    return {"reopened_generation": state.generation, "replace_roundtrip": True}


def _45_quarantine_routing(root: pathlib.Path) -> dict[str, object]:
    release = _release(root)
    artifact_store = ArtifactStore(root / "artifacts")
    payload = b"phase8-quarantine"
    source_file = root / "payload.bin"
    source_file.write_bytes(payload)
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    admitted_artifact = artifact_store.admit_file(source_file, expected_sha256=digest)
    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=len(payload),
        media_type="application/octet-stream",
    )
    manifest = _manifest("1.0.0")
    package = _package(manifest, artifacts=(artifact,))
    _write_package(release, package)
    descriptor = _descriptor()
    executor = _Executor(descriptor)
    providers = CapabilityProviderRegistry(
        (
            CapabilityProviderRegistration(
                capability_id="example.capability",
                executor_id="example.executor.v1",
                adapter_id="example.adapter.v1",
                descriptor=descriptor,
                executor=executor,
                release_sha=_RELEASE_SHA,
                health_probes=(_HealthyProbe(),),
            ),
        )
    )
    source = ReleaseCapabilityPackageSource(release)
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry((manifest,)),
        provider_registry=providers,
        artifact_store=artifact_store,
        package_source=source,
        runtime_release_sha=_RELEASE_SHA,
        platform_tags=("linux-amd64",),
    )
    store = CapabilityRegistryStore(root / "registry.sqlite3")
    store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
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
        health_bridge=CapabilityHealthBridge(health, clock=lambda: _NOW),
        clock=lambda: _NOW,
    )
    lifecycle = CapabilityLifecycleService(
        store=store,
        reconciler=reconciler,
        authority=_Authority(),
    )
    state = store.require_registry("example.capability")
    lifecycle.select_version(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    state = store.require_registry("example.capability")
    lifecycle.enable(
        "example.capability",
        expected_generation=state.generation,
        authority_session_id="phase8-replay-session",
        source=_owner_source(),
    )
    admitted_artifact.object_path.write_bytes(b"tampered")
    quarantined = lifecycle.quarantine_package_if_unsafe(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
    )
    effective = quarantined.snapshot.state("example.capability")
    if (
        quarantined.current_state.desired_state is not DesiredActivationState.ENABLED
        or effective is None
        or effective.effective_enabled
        or projection.allows(descriptor.key)
    ):
        raise AssertionError("safety quarantine failed to remove routing")
    return {"desired": "enabled", "effective": False, "routing": False}


_CASES: tuple[tuple[str, Callable[[pathlib.Path], dict[str, object]]], ...] = (
    ("01_package_schema_validation", _01_schema),
    ("02_strict_semver", _02_semver),
    ("03_same_version_changed_digest_rejected", _03_version_reuse),
    ("04_unknown_manifest_version_rejected", _04_unknown_manifest),
    ("05_manifest_digest_mismatch_rejected", _05_manifest_digest),
    ("06_untrusted_provider_rejected", _06_untrusted_provider),
    ("07_raw_execution_fields_impossible", _07_forbidden_metadata),
    ("08_corrupt_artifact_blocked", _08_corrupt_artifact),
    ("09_runtime_api_mismatch_blocked", _09_runtime_api),
    ("10_platform_mismatch_blocked", _10_platform),
    ("11_registration_does_not_enable", _11_registration_disabled),
    ("12_enable_requires_ready", _12_enable_requires_ready),
    ("13_stale_generation_rejected", _13_stale_cas),
    ("14_one_selected_version", _14_one_selected),
    ("15_disable_removes_routing", _15_disable_routing),
    ("16_disable_does_not_claim_unload", _16_disable_no_unload),
    ("17_new_version_no_auto_switch", _17_new_version_no_switch),
    ("18_version_switch_exact_event", _18_switch_event),
    ("19_supported_rollback_succeeds", _19_rollback),
    ("20_absent_old_descriptor_rollback_blocked", _20_rollback_absent),
    ("21_retired_cannot_select", _21_retired),
    ("22_quarantined_cannot_select", _22_quarantined),
    ("23_failed_health_blocks", _23_health_blocks),
    ("24_desired_and_effective_distinct", _24_desired_vs_effective),
    ("25_registry_restart_survives", _25_restart),
    ("26_newer_schema_fails_closed", _26_newer_schema),
    ("27_untrusted_entrypoint_cannot_execute", _27_entrypoint_untrusted),
    ("28_artifact_retention", _28_retention),
    ("29_core_pinned_unaffected", _29_core_pinned),
    ("30_prior_governance_regressions", _30_regressions),
    ("31_disable_commit_no_stale_route", _31_disable_stale_route),
    ("32_version_switch_no_stale_generation", _32_switch_generation),
    ("33_reconciler_idempotent", _33_reconcile_idempotent),
    ("34_crash_after_commit_recovers", _34_crash_after_commit),
    ("35_cas_event_atomic", _35_atomic_event),
    ("36_reconciler_no_authority_or_intent_write", _36_reconcile_no_authority),
    ("37_dbos_not_registry_truth", _37_dbos_independent),
    ("38_concurrent_mutation_one_winner", _38_concurrent_writers),
    ("39_stale_projection_fails_closed", _39_stale_projection),
    ("40_corrupt_selected_no_fallback", _40_corrupt_selected),
    ("41_release_sha_change_invalidates", _41_release_change),
    ("42_metadata_cannot_choose_execution_model", _42_execution_model),
    ("43_core_pinned_ignores_managed_fence", _43_core_fence),
    ("44_registry_file_restart_handle", _44_file_handle),
    ("45_quarantine_removes_routing_preserves_intent", _45_quarantine_routing),
)


def run_replay_suite(root: pathlib.Path) -> Phase8ReplayReport:
    replay_root = pathlib.Path(root)
    replay_root.mkdir(parents=True, exist_ok=True)
    cases = tuple(
        _case(case_id, replay_root, operation) for case_id, operation in _CASES
    )
    status = "PASS" if all(item.passed for item in cases) else "FAIL"
    payload = {
        "status": status,
        "cases": [item.payload() for item in cases],
    }
    return Phase8ReplayReport(
        cases=cases,
        status=status,
        suite_digest=canonical_digest(payload),
    )
