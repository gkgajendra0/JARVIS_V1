from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
)
from jarvis.capabilities.runtime import build_default_capability_runtime
from jarvis.capability_acquisition.activation import (
    CapabilityAcquisitionLifecycleCoordinator,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
)
from jarvis.capability_registry.provider import CapabilityProviderRegistration
from jarvis.capability_registry.runtime_composition import (
    AcquiredCapabilityCompositionError,
    AcquiredCapabilityDefinition,
    build_package_managed_runtime_stack,
)
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.release import DeploymentMetadataStore, ReleaseRecord
from jarvis.self_model.health import HealthRegistry
from jarvis.work.store import SQLiteWorkStore

RELEASE_SHA = "1" * 40
PACKAGE_ID = "tv.control.package"
PACKAGE_VERSION = "1.0.0"
CAPABILITY_ID = "tv.control"
OPERATION = "tv.power.toggle"


class FakeExecutor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.capability_key = descriptor.key
        self.operations = descriptor.operations

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        raise AssertionError("composition test must not execute provider")

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        raise AssertionError("composition test must not execute provider")


def _release(tmp_path) -> ReleaseRecord:
    root = tmp_path / "release"
    root.mkdir()
    return ReleaseRecord(
        release_sha=RELEASE_SHA,
        release_root=str(root),
        promotion_attempt_id="promotion_phase9f_runtime",
        promotion_evidence_digest="2" * 64,
        config_digest="3" * 64,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _definition(*, release_sha: str = RELEASE_SHA) -> AcquiredCapabilityDefinition:
    descriptor = CapabilityDescriptor.create(
        capability_id=CAPABILITY_ID,
        source_id="acquired.tv",
        kind=CapabilityKind.SEMANTIC_CONNECTOR,
        name="Acquired TV control",
        description="Release-owned test provider.",
        operations=(OPERATION,),
        execution_enabled=True,
    )
    executor = FakeExecutor(descriptor)
    manifest = CapabilityManifest(
        manifest_id="tv.control.manifest",
        manifest_version=1,
        capability_id=CAPABILITY_ID,
        capability_version=PACKAGE_VERSION,
        purpose="Control the owner TV.",
        adapter_id="tv.adapter.v1",
        executor_id="tv.executor.v1",
        operations=(OPERATION,),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=("external_side_effect",),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=("tv.verify.v1",),
        hardware_acceptance_contract_ids=("tv.hardware.v1",),
        provenance_ids=(),
        disable_rollback_contract_id="tv.disable.v1",
    )
    return AcquiredCapabilityDefinition(
        provider=CapabilityProviderRegistration(
            capability_id=CAPABILITY_ID,
            executor_id="tv.executor.v1",
            adapter_id="tv.adapter.v1",
            descriptor=descriptor,
            executor=executor,
            release_sha=release_sha,
        ),
        executor_registration=TrustedExecutorRegistration(
            executor_id="tv.executor.v1",
            adapter_ids=("tv.adapter.v1",),
            operations=(OPERATION,),
            authority_attribute_floor=("external_side_effect",),
            allowed_secret_scopes=(),
            sandbox_profile_ids=(),
            physical_effect_operations=(OPERATION,),
        ),
        adapter_registration=TrustedAdapterRegistration(
            adapter_id="tv.adapter.v1",
            operations=(OPERATION,),
        ),
        manifests=(manifest,),
        references=ManifestReferenceCatalog(
            verification_contract_ids=("tv.verify.v1",),
            hardware_acceptance_contract_ids=("tv.hardware.v1",),
            disable_rollback_contract_ids=("tv.disable.v1",),
        ),
    )


def _write_package(
    release: ReleaseRecord, definition: AcquiredCapabilityDefinition
) -> None:
    manifest = definition.manifests[0]
    payload = {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "package_version": PACKAGE_VERSION,
        "capability_id": CAPABILITY_ID,
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
    root = release.runtime_identity().release_root
    package_root = Path(root) / "capability_packages"
    package_root.mkdir()
    (package_root / "tv.control.package.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def test_package_managed_provider_is_disabled_until_lifecycle_enable(tmp_path) -> None:
    release = _release(tmp_path)
    definition = _definition()
    _write_package(release, definition)
    registry = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    stack = build_package_managed_runtime_stack(
        release,
        definitions=(definition,),
        registry_store=registry,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        health_registry=HealthRegistry(),
        start_periodic=False,
    )
    runtime = build_default_capability_runtime(
        extra_executors=stack.executors,
        catalog_projection=stack.projection,
        close_callbacks=(stack.close,),
    )

    state = registry.require_registry(CAPABILITY_ID)
    assert state.desired_state is DesiredActivationState.DISABLED
    assert not state.has_selection
    assert runtime.capability_for_operation(OPERATION) is None

    selected = registry.transition_registry(
        CAPABILITY_ID,
        expected_generation=state.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id=PACKAGE_ID,
        selected_package_version=PACKAGE_VERSION,
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="test_version_selected",
        authority_ref="test:authority",
        evidence_ref="test:compatibility",
    )
    enabled = registry.transition_registry(
        CAPABILITY_ID,
        expected_generation=selected.generation,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id=PACKAGE_ID,
        selected_package_version=PACKAGE_VERSION,
        event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
        reason_code="test_capability_enabled",
        authority_ref="test:authority",
        evidence_ref="test:compatibility",
    )
    stack.reconciler.reconcile()
    runtime.refresh_catalog()

    assert enabled.desired_state is DesiredActivationState.ENABLED
    assert (
        runtime.capability_for_operation(OPERATION)
        == definition.provider.descriptor.key
    )
    runtime.close()


def test_runtime_composition_rejects_provider_from_another_release(tmp_path) -> None:
    release = _release(tmp_path)
    definition = _definition(release_sha="9" * 40)

    with pytest.raises(
        AcquiredCapabilityCompositionError,
        match="release identity",
    ):
        build_package_managed_runtime_stack(
            release,
            definitions=(definition,),
            registry_store=CapabilityRegistryStore(tmp_path / "registry.sqlite3"),
            artifact_store=ArtifactStore(tmp_path / "artifacts"),
            health_registry=HealthRegistry(),
            start_periodic=False,
        )


class FakeLifecycleAuthority:
    def authorize(self, binding, *, authority_session_id: str):
        assert binding.source.source_session_id == authority_session_id
        return SimpleNamespace(authority_ref="authority:test:phase9f")

    def consume(self, authorized) -> None:
        assert authorized.authority_ref == "authority:test:phase9f"


def test_phase9_lifecycle_coordinator_uses_phase8_service(
    monkeypatch,
    tmp_path,
) -> None:
    release = _release(tmp_path)
    definition = _definition()
    _write_package(release, definition)
    registry = CapabilityRegistryStore(tmp_path / "registry-lifecycle.sqlite3")
    stack = build_package_managed_runtime_stack(
        release,
        definitions=(definition,),
        registry_store=registry,
        artifact_store=ArtifactStore(tmp_path / "artifacts-lifecycle"),
        health_registry=HealthRegistry(),
        start_periodic=False,
    )
    stack.lifecycle.authority = FakeLifecycleAuthority()

    changes = ChangeStore(
        SQLiteWorkStore(tmp_path / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = changes.create(
        request="Acquire TV control",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    package = registry.get_package(PACKAGE_ID, PACKAGE_VERSION)
    assert package is not None
    candidate = changes.add_artifact(
        change.change_id,
        kind="capability_candidate",
        payload={
            "candidate_id": "capcand_runtime_composition",
            "digest": "4" * 64,
            "capability_id": CAPABILITY_ID,
            "package_id": PACKAGE_ID,
            "package_version": PACKAGE_VERSION,
            "package_digest": package.package_digest,
        },
    )
    changes.add_artifact(
        change.change_id,
        kind="capability_package_admission",
        payload={
            "attempt_id": "promotion_phase9f_runtime",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
        },
    )
    monkeypatch.setattr(
        "jarvis.capability_acquisition.activation."
        "ensure_capability_release_bridge_current",
        lambda *_args, **_kwargs: None,
    )
    coordinator = CapabilityAcquisitionLifecycleCoordinator(
        changes,
        DeploymentMetadataStore(tmp_path / "deployment-lifecycle"),
        stack.lifecycle,
    )

    activated = coordinator.activate(
        change.change_id,
        authority_session_id="owner-session",
        source_turn_id="activate-turn",
    )

    state = registry.require_registry(CAPABILITY_ID)
    assert state.desired_state is DesiredActivationState.ENABLED
    assert state.selected_package_id == PACKAGE_ID
    assert state.selected_package_version == PACKAGE_VERSION
    effective = activated.enabled.snapshot.state(CAPABILITY_ID)
    assert effective is not None and effective.effective_enabled
    assert activated.artifact.payload["effective_enabled"] is True

    disabled = coordinator.disable(
        change.change_id,
        authority_session_id="owner-session",
        source_turn_id="disable-turn",
    )
    state = registry.require_registry(CAPABILITY_ID)
    assert state.desired_state is DesiredActivationState.DISABLED
    effective = disabled.disabled.snapshot.state(CAPABILITY_ID)
    assert effective is not None and not effective.effective_enabled
    assert disabled.artifact.payload["effective_enabled"] is False
    stack.close()
