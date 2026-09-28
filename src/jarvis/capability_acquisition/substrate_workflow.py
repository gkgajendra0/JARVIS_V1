"""Phase-9 DEVELOPMENT actions for governed dependency and manifest evidence."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.capability_acquisition.architecture import (
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.models import ChangeArtifact
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    DEPENDENCY_RESOLUTION_KIND,
    MANIFEST_KIND,
    VERIFICATION_KIND,
    EngineeringSubstrateChangeService,
)
from jarvis.engineering_substrate.contracts import (
    CapabilityManifest,
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.engineering_substrate.dependency import DependencyBroker
from jarvis.engineering_substrate.dependency.runtime import (
    current_python_resolution_environment,
    dependency_work_root,
)
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    DependencyResolutionRegistration,
    DigestRegistration,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.engineering_substrate.sandbox import default_sandbox_registry
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType


class CapabilitySubstrateProtocolError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityDevelopmentContext:
    change_id: str
    work_id: str
    architecture: ChangeArtifact


class CapabilityDevelopmentContextResolver:
    def __init__(self, store: ChangeStore) -> None:
        self._store = store

    @property
    def store(self) -> ChangeStore:
        return self._store

    def context_for(self, work_id: str) -> CapabilityDevelopmentContext:
        stage = self._store.stage_for_work(str(work_id).strip())
        if stage is None:
            raise CapabilitySubstrateProtocolError(
                "Phase-9 substrate action requires a linked DEVELOPMENT WorkItem"
            )
        change = self._store.require(stage.change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
            or stage.stage_key
            != OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
        ):
            raise CapabilitySubstrateProtocolError(
                "Phase-9 substrate action is unavailable outside acquisition DEVELOPMENT"
            )
        architecture = ensure_capability_acquisition_architecture_current(
            self._store,
            change.change_id,
            artifact_id=stage.plan_artifact_id,
        )
        return CapabilityDevelopmentContext(
            change_id=change.change_id,
            work_id=str(work_id).strip(),
            architecture=architecture,
        )


def _current_resolution_artifacts(
    store: ChangeStore,
    context: CapabilityDevelopmentContext,
) -> tuple[ChangeArtifact, ...]:
    latest: dict[str, ChangeArtifact] = {}
    for artifact in store.list_artifacts(
        context.change_id,
        kind=DEPENDENCY_RESOLUTION_KIND,
    ):
        if (
            artifact.payload.get("architecture_artifact_id")
            != context.architecture.artifact_id
            or artifact.payload.get("architecture_digest")
            != context.architecture.digest
        ):
            continue
        resolution_id = str(artifact.payload.get("resolution_id") or "").strip()
        if resolution_id:
            latest[resolution_id] = artifact
    return tuple(latest[key] for key in sorted(latest))


class CapabilityDependencyResolveExecutor:
    descriptor = BrainAction(
        name="dev_resolve_python_dependency",
        description=(
            "Resolve and acquire one exact owner-approved Python dependency through "
            "the Phase-5 trusted uv broker. Only an exact == version is accepted; "
            "package-manager flags, URLs, VCS sources and source builds are unavailable."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "package_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                },
                "version": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                },
                "purpose": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "required": ["package_name", "version", "purpose"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(
        self,
        resolver: CapabilityDevelopmentContextResolver,
        *,
        broker_factory: Callable[[], DependencyBroker],
    ) -> None:
        self._resolver = resolver
        self._broker_factory = broker_factory

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("network", "resolver", "artifact")

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        package = str(parameters.get("package_name") or "").strip().casefold()
        version = str(parameters.get("version") or "").strip()
        purpose = str(parameters.get("purpose") or "").strip()
        if not package or not version or not purpose:
            raise CapabilitySubstrateProtocolError(
                "dependency package, version and purpose are required"
            )
        if version.startswith("=="):
            version = version[2:].strip()
        if not version or any(token in version for token in ("<", ">", "~", "*", ",")):
            raise CapabilitySubstrateProtocolError(
                "Phase-9 runtime dependencies require one exact package version"
            )

        approved = tuple(
            str(item).strip().casefold()
            for item in context.architecture.payload.get("dependency_refs", ())
            if str(item).strip()
        )
        pypi_refs = tuple(
            reference for reference in approved if reference.startswith("pypi:")
        )
        matching = (
            tuple(
                reference
                for reference in pypi_refs
                if reference.startswith(f"pypi:{package}==")
            )
            if pypi_refs
            else tuple(reference for reference in approved if package in reference)
        )
        if not matching:
            raise CapabilitySubstrateProtocolError(
                "requested dependency is absent from the owner-approved architecture"
            )
        expected_lock: str | None = None
        if pypi_refs:
            exact_prefix = f"pypi:{package}=={version}#lock-sha256="
            exact = tuple(
                reference for reference in matching if reference.startswith(exact_prefix)
            )
            if len(exact) != 1:
                raise CapabilitySubstrateProtocolError(
                    "requested dependency version differs from verified architecture"
                )
            expected_lock = exact[0][len(exact_prefix) :]
            if len(expected_lock) != 64 or any(
                character not in "0123456789abcdef" for character in expected_lock
            ):
                raise CapabilitySubstrateProtocolError(
                    "verified architecture dependency lock digest is malformed"
                )

        requirement_id = (
            "phase9:req:"
            + canonical_digest(
                {
                    "architecture_digest": context.architecture.digest,
                    "package_name": package,
                    "version": version,
                }
            )[:24]
        )
        for artifact in _current_resolution_artifacts(self._resolver.store, context):
            if artifact.payload.get("requirement_id") == requirement_id:
                return {
                    "resolved": True,
                    "reused": True,
                    "requirement_id": requirement_id,
                    "resolution_id": artifact.payload.get("resolution_id"),
                    "resolution_digest": artifact.payload.get("resolution_digest"),
                    "lock_digest": artifact.payload.get("lock_digest"),
                    "lock_artifact_id": artifact.payload.get("lock_artifact_id"),
                    "artifact_ids": list(artifact.payload.get("artifact_ids") or ()),
                }

        requirement = DependencyRequirement(
            requirement_id=requirement_id,
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=package,
            version_constraint="==" + version,
            purpose=purpose,
            registered_source_ids=("pypi.public.v1",),
            change_id=context.change_id,
            work_id=context.work_id,
        )
        workspace = dependency_work_root(context.work_id)
        broker = self._broker_factory()
        resolved = await asyncio.to_thread(
            broker.resolve_python,
            requirement,
            workspace=workspace,
            environment=current_python_resolution_environment(),
        )
        if (
            expected_lock is not None
            and resolved.resolution.lock_digest != expected_lock
        ):
            raise CapabilitySubstrateProtocolError(
                "dependency graph changed after owner-approved SDK verification"
            )
        staging = workspace / "wheels"
        artifacts = await asyncio.to_thread(
            broker.acquire_locked_wheels,
            resolved,
            staging_dir=staging,
        )
        lock = await asyncio.to_thread(broker.admit_lock, resolved)
        if tuple(item.sha256 for item in artifacts) != resolved.resolution.artifact_ids:
            raise CapabilitySubstrateProtocolError(
                "admitted dependency wheel set differs from canonical resolution"
            )
        bound = EngineeringSubstrateChangeService(
            self._resolver.store
        ).bind_dependency_resolution(
            context.change_id,
            resolved.resolution,
            lock_artifact_id=lock.artifact_sha256,
        )
        return {
            "resolved": True,
            "reused": False,
            "requirement_id": requirement.requirement_id,
            "resolution_id": resolved.resolution.resolution_id,
            "resolution_digest": canonical_digest(resolved.resolution),
            "resolution_artifact_id": bound.artifact_id,
            "lock_digest": resolved.resolution.lock_digest,
            "lock_artifact_id": lock.artifact_sha256,
            "artifact_ids": list(resolved.resolution.artifact_ids),
            "resolved_packages": list(resolved.resolution.resolved_packages),
        }


def _research_discovery_digests(
    store: ChangeStore,
    change_id: str,
) -> dict[str, str]:
    process = OWNER_CAPABILITY_ACQUISITION_PROCESS
    source_stage = next(
        (
            item
            for item in store.list_stages(change_id)
            if item.stage_key == process.architecture_source_stage.stage_key
        ),
        None,
    )
    if source_stage is None:
        return {}
    output: dict[str, str] = {}
    for step in store.work.list_steps(source_stage.work_id):
        if step.kind != "acq_discover_local" or step.state.value != "completed":
            continue
        scope_id = str(step.observation.get("scope_id") or "").strip().casefold()
        digest = str(step.observation.get("scope_digest") or "").strip().casefold()
        if scope_id and len(digest) == 64:
            output[scope_id] = digest
    return output


class CapabilityManifestBindExecutor:
    descriptor = BrainAction(
        name="dev_bind_capability_manifest",
        description=(
            "Bind the current Phase-5 capability manifest deterministically from the "
            "owner-approved Phase-9 architecture and already acquired dependency evidence."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, resolver: CapabilityDevelopmentContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("artifact",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        architecture = context.architecture.payload
        operations = tuple(
            str(item).strip().casefold()
            for item in architecture.get("requested_operations", ())
            if str(item).strip()
        )
        if not operations:
            raise CapabilitySubstrateProtocolError(
                "approved capability architecture has no operations"
            )
        dependency_refs = tuple(
            str(item).strip()
            for item in architecture.get("dependency_refs", ())
            if str(item).strip()
        )
        resolutions = _current_resolution_artifacts(self._resolver.store, context)
        if dependency_refs and not resolutions:
            raise CapabilitySubstrateProtocolError(
                "approved dependency requirements have no acquired resolution evidence"
            )
        registrations = tuple(
            DependencyResolutionRegistration(
                resolution_id=str(item.payload["resolution_id"]),
                digest=str(item.payload["resolution_digest"]),
                provenance_ids=(),
            )
            for item in resolutions
        )

        sandbox_registry = default_sandbox_registry()
        sandbox_ids = tuple(
            str(item).strip().casefold()
            for item in architecture.get("sandbox_profile_ids", ())
            if str(item).strip()
        )
        sandbox_refs = tuple(
            DigestRegistration(
                reference_id=profile_id,
                digest=canonical_digest(
                    sandbox_registry.require(profile_id, 1).profile
                ),
            )
            for profile_id in sandbox_ids
        )

        discovery_digests = _research_discovery_digests(
            self._resolver.store,
            context.change_id,
        )
        discovery_ids = tuple(
            str(item).strip().casefold()
            for item in architecture.get("discovery_scopes", ())
            if str(item).strip()
        )
        missing_discovery = tuple(
            item for item in discovery_ids if item not in discovery_digests
        )
        if missing_discovery:
            raise CapabilitySubstrateProtocolError(
                "approved discovery scope lacks exact Phase-9 discovery evidence: "
                + ", ".join(missing_discovery)
            )
        discovery_refs = tuple(
            DigestRegistration(
                reference_id=scope_id,
                digest=discovery_digests[scope_id],
            )
            for scope_id in discovery_ids
        )

        verification_ids = tuple(
            str(item).strip().casefold()
            for item in architecture.get("verification_contract_ids", ())
            if str(item).strip()
        )
        if not verification_ids:
            raise CapabilitySubstrateProtocolError(
                "approved architecture has no verification contract"
            )
        rollback_id = "phase9.disable-rollback.v1"
        capability_id = (
            str(architecture.get("proposed_capability_id") or "").strip().casefold()
        )
        if not capability_id:
            raise CapabilitySubstrateProtocolError(
                "approved architecture has no capability identity"
            )
        adapter_id = "phase9.adapter." + capability_id
        executor_id = "phase9.executor." + capability_id
        secret_scopes = tuple(
            str(item).strip().casefold()
            for item in architecture.get("secret_scopes", ())
            if str(item).strip()
        )
        external = bool(
            tuple(architecture.get("device_scopes", ()))
            or tuple(architecture.get("network_scopes", ()))
        )
        authority_attributes = ("external_side_effect",) if external else ()

        references = ManifestReferenceCatalog(
            dependency_resolutions=registrations,
            sandbox_profiles=sandbox_refs,
            discovery_scopes=discovery_refs,
            verification_contract_ids=verification_ids,
            disable_rollback_contract_ids=(rollback_id,),
        )
        executor = TrustedExecutorRegistration(
            executor_id=executor_id,
            adapter_ids=(adapter_id,),
            operations=operations,
            authority_attribute_floor=authority_attributes,
            allowed_secret_scopes=secret_scopes,
            sandbox_profile_ids=sandbox_ids,
            physical_effect_operations=(),
        )
        adapter = TrustedAdapterRegistration(
            adapter_id=adapter_id,
            operations=operations,
            discovery_scope_ids=discovery_ids,
        )
        registry = CapabilityManifestRegistry(
            executors=(executor,),
            adapters=(adapter,),
            references=references,
        )
        manifest = CapabilityManifest(
            manifest_id="phase9.manifest." + capability_id,
            manifest_version=1,
            capability_id=capability_id,
            capability_version=str(
                architecture.get("proposed_package_version") or "1"
            ).strip(),
            purpose="Owner-approved Phase-9 acquired capability",
            adapter_id=adapter_id,
            executor_id=executor_id,
            operations=operations,
            dependency_resolution_ids=tuple(
                item.resolution_id for item in registrations
            ),
            secret_scope_requirements=secret_scopes,
            authority_attributes=authority_attributes,
            sandbox_profile_ids=sandbox_ids,
            discovery_scope_ids=discovery_ids,
            platform_constraints=(),
            resource_requirements=(),
            health_probe_ids=(),
            verification_contract_ids=verification_ids,
            hardware_acceptance_contract_ids=(),
            provenance_ids=(),
            disable_rollback_contract_id=rollback_id,
            dependency_resolution_digests=tuple(item.digest for item in registrations),
            sandbox_profile_digests=tuple(item.digest for item in sandbox_refs),
            discovery_scope_digests=tuple(item.digest for item in discovery_refs),
            provenance_digests=(),
        )
        registered = registry.register(manifest)
        latest = self._resolver.store.latest_artifact(
            context.change_id,
            MANIFEST_KIND,
        )
        if (
            latest is not None
            and latest.payload.get("architecture_artifact_id")
            == context.architecture.artifact_id
            and latest.payload.get("architecture_digest") == context.architecture.digest
            and latest.payload.get("manifest_digest") == registered.manifest_digest
        ):
            bound = latest
        else:
            bound = EngineeringSubstrateChangeService(
                self._resolver.store
            ).bind_manifest(context.change_id, registered)
        return {
            "manifest_bound": True,
            "manifest_id": manifest.manifest_id,
            "manifest_digest": registered.manifest_digest,
            "manifest_artifact_id": bound.artifact_id,
            "dependency_resolution_ids": list(manifest.dependency_resolution_ids),
        }


class CapabilitySubstrateVerifyExecutor:
    descriptor = BrainAction(
        name="dev_verify_capability_substrate",
        description=(
            "Record current Phase-5 substrate verification only after a passing "
            "sandboxed DEVELOPMENT test exists for this exact WorkItem."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, resolver: CapabilityDevelopmentContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("artifact_store",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        service = EngineeringSubstrateChangeService(self._resolver.store)
        if service.verification_current(context.change_id):
            existing = self._resolver.store.latest_artifact(
                context.change_id,
                VERIFICATION_KIND,
            )
            return {
                "verified": True,
                "reused": True,
                "verification_artifact_id": (
                    None if existing is None else existing.artifact_id
                ),
            }
        if (
            self._resolver.store.latest_artifact(
                context.change_id,
                MANIFEST_KIND,
            )
            is None
        ):
            raise CapabilitySubstrateProtocolError(
                "Phase-5 manifest must be bound before substrate verification"
            )
        passing = next(
            (
                step
                for step in reversed(
                    self._resolver.store.work.list_steps(context.work_id)
                )
                if step.kind == "dev_run_tests"
                and step.state.value == "completed"
                and step.observation.get("passed") is True
                and step.observation.get("sandbox") == "docker"
                and step.observation.get("network") == "disabled"
            ),
            None,
        )
        if passing is None:
            raise CapabilitySubstrateProtocolError(
                "substrate verification requires passing network-disabled sandbox tests"
            )
        artifact = service.record_verification(
            context.change_id,
            software_security_passed=True,
            automated_evidence={
                "development_sandbox_tests": True,
            },
        )
        if artifact.payload.get("satisfied") is not True:
            raise CapabilitySubstrateProtocolError(
                "Phase-5 substrate verification remains unsatisfied"
            )
        return {
            "verified": True,
            "reused": False,
            "verification_artifact_id": artifact.artifact_id,
            "verification_artifact_digest": artifact.digest,
        }


def build_capability_substrate_executors(
    store: ChangeStore,
    *,
    broker_factory: Callable[[], DependencyBroker],
) -> tuple[object, ...]:
    resolver = CapabilityDevelopmentContextResolver(store)
    return (
        CapabilityDependencyResolveExecutor(
            resolver,
            broker_factory=broker_factory,
        ),
        CapabilityManifestBindExecutor(resolver),
        CapabilitySubstrateVerifyExecutor(resolver),
    )
