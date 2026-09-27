"""Production composition for release-owned package-managed capabilities."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import SqliteAuditEventStore
from jarvis.authority.local_opa import ManagedOpaServer
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import OpaPolicyEngine
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityService
from jarvis.authority.verifier import WindowsHelloVerifier
from jarvis.capability_registry.admission import CapabilityPackageAdmissionService
from jarvis.capability_registry.authority import CapabilityLifecycleAuthorityBridge
from jarvis.capability_registry.compatibility import CapabilityCompatibilityEvaluator
from jarvis.capability_registry.lifecycle import CapabilityLifecycleService
from jarvis.capability_registry.projection import CapabilityRegistryProjection
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
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    DependencyResolutionRegistration,
    DigestRegistration,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.release import ReleaseRecord
from jarvis.self_model.health import HealthRegistry


class AcquiredCapabilityCompositionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AcquiredCapabilityDefinition:
    """Source-owned provider/manifest bundle; package metadata cannot create this."""

    provider: CapabilityProviderRegistration
    executor_registration: TrustedExecutorRegistration
    adapter_registration: TrustedAdapterRegistration
    manifests: tuple[CapabilityManifest, ...]
    references: ManifestReferenceCatalog

    def __post_init__(self) -> None:
        if not self.manifests:
            raise ValueError("acquired capability definition requires a manifest")
        if self.provider.executor_id != self.executor_registration.executor_id:
            raise ValueError("provider/executor registration identity mismatch")
        if self.provider.adapter_id != self.adapter_registration.adapter_id:
            raise ValueError("provider/adapter registration identity mismatch")
        for manifest in self.manifests:
            if manifest.capability_id != self.provider.capability_id:
                raise ValueError("manifest/provider capability identity mismatch")
            if manifest.executor_id != self.provider.executor_id:
                raise ValueError("manifest/provider executor identity mismatch")
            if manifest.adapter_id != self.provider.adapter_id:
                raise ValueError("manifest/provider adapter identity mismatch")


def _merge_unique_objects(
    values,
    *,
    key: Callable[[object], str],
    kind: str,
) -> tuple:
    merged: dict[str, object] = {}
    for value in values:
        identity = key(value)
        current = merged.get(identity)
        if current is not None and current != value:
            raise AcquiredCapabilityCompositionError(
                f"conflicting acquired capability {kind}: {identity}"
            )
        merged[identity] = value
    return tuple(merged[item] for item in sorted(merged))


def _merge_references(
    definitions: tuple[AcquiredCapabilityDefinition, ...],
) -> ManifestReferenceCatalog:
    references = tuple(item.references for item in definitions)
    dependencies = _merge_unique_objects(
        (
            item
            for reference in references
            for item in reference.dependency_resolutions
        ),
        key=lambda item: item.resolution_id,
        kind="dependency resolution",
    )
    provenance = _merge_unique_objects(
        (item for reference in references for item in reference.provenance),
        key=lambda item: item.reference_id,
        kind="provenance reference",
    )
    sandboxes = _merge_unique_objects(
        (item for reference in references for item in reference.sandbox_profiles),
        key=lambda item: item.reference_id,
        kind="sandbox profile",
    )
    discovery = _merge_unique_objects(
        (item for reference in references for item in reference.discovery_scopes),
        key=lambda item: item.reference_id,
        kind="discovery scope",
    )

    def tokens(field: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    value
                    for reference in references
                    for value in getattr(reference, field)
                }
            )
        )

    return ManifestReferenceCatalog(
        dependency_resolutions=tuple(
            item for item in dependencies if isinstance(item, DependencyResolutionRegistration)
        ),
        provenance=tuple(
            item for item in provenance if isinstance(item, DigestRegistration)
        ),
        sandbox_profiles=tuple(
            item for item in sandboxes if isinstance(item, DigestRegistration)
        ),
        discovery_scopes=tuple(
            item for item in discovery if isinstance(item, DigestRegistration)
        ),
        verification_contract_ids=tokens("verification_contract_ids"),
        hardware_acceptance_contract_ids=tokens(
            "hardware_acceptance_contract_ids"
        ),
        disable_rollback_contract_ids=tokens("disable_rollback_contract_ids"),
        health_probe_ids=tokens("health_probe_ids"),
        resource_requirement_ids=tokens("resource_requirement_ids"),
        platform_constraint_ids=tokens("platform_constraint_ids"),
    )


def _authority_audit_path() -> pathlib.Path:
    configured = os.getenv("JARVIS_AUTHORITY_AUDIT_DB", "").strip()
    if configured:
        base = pathlib.Path(configured).expanduser()
        return base.with_name(f"{base.stem}.capability_lifecycle{base.suffix or '.sqlite3'}")
    return (
        pathlib.Path.home()
        / ".jarvis"
        / "authority"
        / "capability_lifecycle_audit.sqlite3"
    )


class LazyCapabilityLifecycleAuthority:
    """Build existing Authority/OPA/Windows-Hello machinery only on mutation."""

    def __init__(self, *, gate_reader=None) -> None:
        self._gate_reader = gate_reader
        self._bridge: CapabilityLifecycleAuthorityBridge | None = None
        self._opa: ManagedOpaServer | None = None
        self._audit: SqliteAuditEventStore | None = None

    def _ensure(self) -> CapabilityLifecycleAuthorityBridge:
        if self._bridge is not None:
            return self._bridge
        audit_path = _authority_audit_path()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit = SqliteAuditEventStore(audit_path)
        opa = ManagedOpaServer()
        try:
            opa.start()
            approvals = ApprovalService()
            authority = AuthorityService(
                risk_classifier=RiskClassifier(),
                policy_engine=OpaPolicyEngine(endpoint=opa.endpoint),
                approvals=approvals,
                audit_store=audit,
                permits=PermitRegistry(),
            )
            bridge = CapabilityLifecycleAuthorityBridge(
                approvals=approvals,
                authority=authority,
                verifier=WindowsHelloVerifier(),
                gate_reader=self._gate_reader,
            )
        except Exception:
            opa.close()
            audit.close()
            raise
        self._opa = opa
        self._audit = audit
        self._bridge = bridge
        return bridge

    def authorize(self, binding, *, authority_session_id: str):
        return self._ensure().authorize(
            binding,
            authority_session_id=authority_session_id,
        )

    def consume(self, authorized) -> None:
        self._ensure().consume(authorized)

    def close(self) -> None:
        self._bridge = None
        if self._opa is not None:
            self._opa.close()
        if self._audit is not None:
            self._audit.close()
        self._opa = None
        self._audit = None


@dataclass(slots=True)
class PackageManagedRuntimeStack:
    release: ReleaseRecord
    definitions: tuple[AcquiredCapabilityDefinition, ...]
    provider_registry: CapabilityProviderRegistry
    manifest_registry: CapabilityManifestRegistry
    package_source: ReleaseCapabilityPackageSource
    registry_store: CapabilityRegistryStore
    projection: CapabilityRegistryProjection
    reconciler: CapabilityLifecycleReconciler
    admission: CapabilityPackageAdmissionService
    lifecycle: CapabilityLifecycleService
    periodic: PeriodicCapabilityReconciler
    lifecycle_authority: LazyCapabilityLifecycleAuthority

    @property
    def executors(self) -> tuple:
        return tuple(
            registration.executor
            for registration in self.provider_registry.registrations()
        )

    def close(self) -> None:
        self.periodic.stop()
        self.lifecycle_authority.close()


def build_package_managed_runtime_stack(
    release: ReleaseRecord,
    *,
    definitions: tuple[AcquiredCapabilityDefinition, ...] | None = None,
    registry_store: CapabilityRegistryStore | None = None,
    artifact_store: ArtifactStore | None = None,
    health_registry: HealthRegistry | None = None,
    gate_reader=None,
    start_periodic: bool = True,
) -> PackageManagedRuntimeStack:
    if not isinstance(release, ReleaseRecord):
        raise TypeError("release must be ReleaseRecord")
    if definitions is None:
        from jarvis.acquired_capabilities.registry import (
            build_acquired_capability_definitions,
        )

        definitions = build_acquired_capability_definitions(release.release_sha)
    if any(not isinstance(item, AcquiredCapabilityDefinition) for item in definitions):
        raise TypeError("definitions must contain AcquiredCapabilityDefinition values")
    if any(item.provider.release_sha != release.release_sha for item in definitions):
        raise AcquiredCapabilityCompositionError(
            "acquired provider release identity differs from active release"
        )

    executors = _merge_unique_objects(
        (item.executor_registration for item in definitions),
        key=lambda item: item.executor_id,
        kind="executor registration",
    )
    adapters = _merge_unique_objects(
        (item.adapter_registration for item in definitions),
        key=lambda item: item.adapter_id,
        kind="adapter registration",
    )
    references = _merge_references(definitions)
    manifests = CapabilityManifestRegistry(
        executors=executors,
        adapters=adapters,
        references=references,
    )
    for definition in definitions:
        for manifest in definition.manifests:
            manifests.register(manifest)

    providers = CapabilityProviderRegistry(
        tuple(item.provider for item in definitions)
    )
    source = ReleaseCapabilityPackageSource(release)
    artifacts = artifact_store or ArtifactStore()
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=manifests,
        provider_registry=providers,
        artifact_store=artifacts,
        package_source=source,
        runtime_release_sha=release.release_sha,
    )
    store = registry_store or CapabilityRegistryStore()
    projection = CapabilityRegistryProjection(provider_registry=providers)
    health = health_registry or HealthRegistry()
    reconciler = CapabilityLifecycleReconciler(
        store=store,
        evaluator=evaluator,
        provider_registry=providers,
        health_registry=health,
        projection=projection,
        health_bridge=CapabilityHealthBridge(health),
    )
    admission = CapabilityPackageAdmissionService(
        store=store,
        package_source=source,
        evaluator=evaluator,
    )
    admission.admit_all()
    reconciler.reconcile(ReconciliationTrigger.STARTUP)

    lifecycle_authority = LazyCapabilityLifecycleAuthority(gate_reader=gate_reader)
    lifecycle = CapabilityLifecycleService(
        store=store,
        reconciler=reconciler,
        authority=lifecycle_authority,
    )
    periodic = PeriodicCapabilityReconciler(reconciler)
    if start_periodic:
        periodic.start()
    return PackageManagedRuntimeStack(
        release=release,
        definitions=definitions,
        provider_registry=providers,
        manifest_registry=manifests,
        package_source=source,
        registry_store=store,
        projection=projection,
        reconciler=reconciler,
        admission=admission,
        lifecycle=lifecycle,
        periodic=periodic,
        lifecycle_authority=lifecycle_authority,
    )
