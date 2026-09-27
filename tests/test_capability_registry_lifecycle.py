from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from jarvis.authority import (
    ApprovalRequirement,
    ApprovalService,
    AuthorityService,
    InMemoryAuditEventStore,
    PermitRegistry,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    RiskClass,
    RiskClassifier,
    StrongVerificationResult,
    StrongVerificationStatus,
    TrustTier,
)
from jarvis.authority.types import ActionOrigin, AuthorityEffect
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capability_registry.admission import CapabilityPackageAdmissionService
from jarvis.capability_registry.authority import (
    CapabilityLifecycleAction,
    CapabilityLifecycleAuthorizationError,
    CapabilityLifecycleAuthorityBridge,
    CapabilityLifecycleAuthoritySource,
)
from jarvis.capability_registry.compatibility import CapabilityCompatibilityEvaluator
from jarvis.capability_registry.contracts import (
    CapabilityPackageV1,
    PackageArtifactDescriptorV1,
    parse_capability_package_v1,
)
from jarvis.capability_registry.lifecycle import (
    CapabilityLifecyclePreconditionError,
    CapabilityLifecycleService,
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
)
from jarvis.capability_registry.retention import CapabilityArtifactRetentionPlanner
from jarvis.capability_registry.source import ReleaseCapabilityPackageSource
from jarvis.capability_registry.store import (
    CapabilityRegistrySelectionError,
    CapabilityRegistryStore,
    StaleRegistryGenerationError,
)
from jarvis.engineering_change.gates import GateChallenge, GateDecision, GateKind
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.release import ReleaseRecord
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState

RELEASE_SHA = "a" * 40
PROMOTION_DIGEST = "b" * 64
CONFIG_DIGEST = "c" * 64
NOW = 1_800_000_000.0
SESSION = "phase8e-session"
TURN = "phase8e-turn"


class LocalPolicy:
    version = "step3-v1"

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        risk = policy_input.risk_class
        if risk is RiskClass.PERSISTENT_OR_EXTERNAL:
            requirements = PolicyRequirements(
                TrustTier.CORROBORATED_OWNER,
                ApprovalRequirement.EXPLICIT,
            )
        elif risk is RiskClass.CRITICAL:
            requirements = PolicyRequirements(
                TrustTier.VERIFIED_OWNER,
                ApprovalRequirement.STRONG,
            )
        else:
            return PolicyDecision.deny(
                "unexpected_lifecycle_risk",
                policy_version=self.version,
            )
        return PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=requirements,
            reason_codes=(),
            policy_version=self.version,
        )


class RecordingStrongVerifier:
    verifier_id = "phase8e-test-verifier"

    def __init__(self) -> None:
        self.calls = 0
        self.last_proposal = None

    def verify(self, *, proposal, session_id: str) -> StrongVerificationResult:
        self.calls += 1
        self.last_proposal = proposal
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id=self.verifier_id,
            verification_id=f"verification-{self.calls}",
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
            reason_codes=("verified",),
        )


class FakeExecutor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.capability_key = descriptor.key
        self.operations = descriptor.operations

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        raise AssertionError("Phase-8 lifecycle tests must not execute capabilities")

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={"unexpected": True},
        )


class HealthyProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        return HealthObservation.create(
            component_id=component_id,
            source=f"capability_probe:{self.probe_id}",
            state=HealthState.HEALTHY,
            reason_code="probe_healthy",
            summary="Deterministic lifecycle test probe is healthy.",
            ttl_seconds=60.0,
            observed_at_epoch=NOW,
        )


class FailedProbe:
    probe_id = "health.example.v1"

    def observe(self, *, component_id: str) -> HealthObservation:
        raise RuntimeError("deterministic lifecycle test failure")


def _release(tmp_path) -> ReleaseRecord:
    root = tmp_path / "release"
    root.mkdir(parents=True, exist_ok=True)
    return ReleaseRecord(
        release_sha=RELEASE_SHA,
        release_root=str(root),
        promotion_attempt_id="promotion_phase8e_test",
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _manifest(
    version: str,
    *,
    authority_attributes: tuple[str, ...] = (),
) -> CapabilityManifest:
    token = version.replace(".", "_").replace("-", "_")
    return CapabilityManifest(
        manifest_id=f"manifest.example.{token}",
        manifest_version=1,
        capability_id="example.capability",
        capability_version=version,
        purpose=f"Harmless deterministic Phase-8E capability {version}.",
        adapter_id="example.adapter.v1",
        executor_id="example.executor.v1",
        operations=("ping",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=authority_attributes,
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


def _manifest_registry(
    manifests: tuple[CapabilityManifest, ...],
    *,
    authority_floor: tuple[str, ...] = (),
) -> CapabilityManifestRegistry:
    registry = CapabilityManifestRegistry(
        executors=(
            TrustedExecutorRegistration(
                executor_id="example.executor.v1",
                adapter_ids=("example.adapter.v1",),
                operations=("ping",),
                authority_attribute_floor=authority_floor,
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
    for manifest in manifests:
        registry.register(manifest)
    return registry


def _descriptor() -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id="example.capability",
        source_id="phase8e.test",
        kind=CapabilityKind.NATIVE_API,
        name="Phase 8E Test Capability",
        description="Harmless deterministic lifecycle test provider.",
        operations=("ping",),
        execution_enabled=True,
    )


def _package(
    manifest: CapabilityManifest,
    *,
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
            "manifest_version": manifest.manifest_version,
            "manifest_digest": canonical_digest(manifest),
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": 1,
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _write_package(
    release: ReleaseRecord,
    package: CapabilityPackageV1,
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
    tmp_path,
    *,
    versions: tuple[str, ...] = ("1.0.0", "2.0.0"),
    authority_attributes: tuple[str, ...] = (),
    authority_floor: tuple[str, ...] = (),
    probe=None,
    with_artifact: bool = False,
    gate_reader=None,
):
    release = _release(tmp_path)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_result = None
    artifact_descriptor: PackageArtifactDescriptorV1 | None = None
    if with_artifact:
        payload = b"phase8e-artifact"
        source_file = tmp_path / "payload.bin"
        source_file.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        artifact_result = artifact_store.admit_file(
            source_file,
            expected_sha256=digest,
            provenance_id="prov.phase8e",
        )
        artifact_descriptor = PackageArtifactDescriptorV1(
            role="payload",
            sha256=digest,
            size_bytes=len(payload),
            media_type="application/octet-stream",
            provenance_refs=("prov.phase8e",),
        )

    manifests = tuple(
        _manifest(version, authority_attributes=authority_attributes)
        for version in versions
    )
    packages = {
        manifest.capability_version: _package(
            manifest,
            artifacts=(() if artifact_descriptor is None else (artifact_descriptor,)),
        )
        for manifest in manifests
    }
    package_paths = {
        version: _write_package(release, package)
        for version, package in packages.items()
    }

    manifest_registry = _manifest_registry(
        manifests,
        authority_floor=authority_floor,
    )
    descriptor = _descriptor()
    executor = FakeExecutor(descriptor)
    selected_probe = HealthyProbe() if probe is None else probe
    provider = CapabilityProviderRegistration(
        capability_id="example.capability",
        executor_id="example.executor.v1",
        adapter_id="example.adapter.v1",
        descriptor=descriptor,
        executor=executor,
        release_sha=RELEASE_SHA,
        health_probes=(selected_probe,),
    )
    providers = CapabilityProviderRegistry((provider,))
    source = ReleaseCapabilityPackageSource(release)
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=manifest_registry,
        provider_registry=providers,
        artifact_store=artifact_store,
        package_source=source,
        runtime_release_sha=RELEASE_SHA,
        platform_tags=("linux-amd64",),
    )
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    for package in packages.values():
        report = evaluator.evaluate_package(package)
        store.admit_package(
            package,
            admitted_release_sha=RELEASE_SHA,
            evidence_digest=report.digest,
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

    approvals = ApprovalService()
    authority_service = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(),
    )
    verifier = RecordingStrongVerifier()
    authority = CapabilityLifecycleAuthorityBridge(
        approvals=approvals,
        authority=authority_service,
        verifier=verifier,
        gate_reader=gate_reader,
    )
    lifecycle = CapabilityLifecycleService(
        store=store,
        reconciler=reconciler,
        authority=authority,
    )
    return {
        "release": release,
        "artifact_store": artifact_store,
        "artifact_result": artifact_result,
        "manifests": manifests,
        "packages": packages,
        "package_paths": package_paths,
        "source": source,
        "evaluator": evaluator,
        "store": store,
        "health": health,
        "projection": projection,
        "reconciler": reconciler,
        "verifier": verifier,
        "authority": authority,
        "lifecycle": lifecycle,
    }


def _owner_source() -> CapabilityLifecycleAuthoritySource:
    return CapabilityLifecycleAuthoritySource.owner_turn(
        session_id=SESSION,
        turn_id=TURN,
    )


def _select(env, version: str, generation: int):
    return env["lifecycle"].select_version(
        "example.capability",
        package_id="example.package",
        package_version=version,
        expected_generation=generation,
        authority_session_id=SESSION,
        source=_owner_source(),
    )


def _enable(env, generation: int):
    return env["lifecycle"].enable(
        "example.capability",
        expected_generation=generation,
        authority_session_id=SESSION,
        source=_owner_source(),
    )


def test_select_enable_and_rollback_are_exact_authority_bound(tmp_path) -> None:
    env = _environment(tmp_path)

    selected = _select(env, "2.0.0", 1)
    assert selected.changed
    assert selected.current_state.generation == 2
    assert not selected.snapshot.state("example.capability").effective_enabled

    enabled = _enable(env, 2)
    assert enabled.current_state.generation == 3
    assert enabled.snapshot.state("example.capability").effective_enabled

    rolled_back = env["lifecycle"].rollback_version(
        "example.capability",
        package_version="1.0.0",
        expected_generation=3,
        authority_session_id=SESSION,
        source=_owner_source(),
    )

    assert rolled_back.action is CapabilityLifecycleAction.ROLLBACK_VERSION
    assert rolled_back.current_state.generation == 4
    assert rolled_back.current_state.selected_package_version == "1.0.0"
    assert rolled_back.snapshot.state("example.capability").effective_enabled
    assert env["verifier"].calls == 0

    events = env["store"].list_events("example.capability")
    transition_events = [
        event
        for event in events
        if event.reason_code
        in {
            "version_selected",
            "capability_enabled",
            "version_rollback",
        }
    ]
    assert len(transition_events) == 3
    assert all(event.authority_ref for event in transition_events)
    assert all(event.evidence_ref for event in transition_events)


def test_disable_preserves_selection_but_stops_effective_routing(tmp_path) -> None:
    env = _environment(tmp_path, versions=("1.0.0",))
    _select(env, "1.0.0", 1)
    _enable(env, 2)

    disabled = env["lifecycle"].disable(
        "example.capability",
        expected_generation=3,
        authority_session_id=SESSION,
        source=_owner_source(),
    )

    assert disabled.current_state.generation == 4
    assert disabled.current_state.selected_package_version == "1.0.0"
    assert disabled.current_state.desired_state.value == "disabled"
    state = disabled.snapshot.state("example.capability")
    assert state is not None
    assert not state.effective_enabled
    assert state.health_state is HealthState.DISABLED


def test_stale_generation_is_rejected_before_authority(tmp_path) -> None:
    env = _environment(tmp_path, versions=("1.0.0",))

    with pytest.raises(StaleRegistryGenerationError):
        _select(env, "1.0.0", 99)

    assert env["verifier"].calls == 0
    assert env["store"].require_registry("example.capability").generation == 1


def test_enable_fails_before_durable_mutation_when_health_is_bad(tmp_path) -> None:
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        probe=FailedProbe(),
    )
    _select(env, "1.0.0", 1)

    with pytest.raises(
        CapabilityLifecyclePreconditionError,
        match="health is not acceptable",
    ):
        _enable(env, 2)

    state = env["store"].require_registry("example.capability")
    assert state.generation == 2
    assert state.desired_state.value == "disabled"


def test_critical_manifest_floor_requires_strong_owner_verification(tmp_path) -> None:
    critical = ("secret_or_credential_access",)
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        authority_attributes=critical,
        authority_floor=critical,
    )

    selected = _select(env, "1.0.0", 1)

    assert selected.changed
    assert env["verifier"].calls == 1
    assert env["verifier"].last_proposal is not None
    assert env["verifier"].last_proposal.attributes.secret_or_credential_access is True


def test_approved_engineering_gate_source_is_reverified_and_bound(tmp_path) -> None:
    challenge = GateChallenge(
        gate_id="gate-phase8e",
        change_id="change-phase8e",
        kind=GateKind.ARCHITECTURE,
        artifact_id="artifact-phase8e",
        artifact_digest="d" * 64,
        created_at="2026-09-27T00:00:00Z",
    )
    decision = GateDecision(
        challenge=challenge,
        approved=True,
        actor_id="owner",
        source_session_id="prior-session",
        source_turn_id="prior-turn",
        request_key="phase8e-gate-decision",
        decided_at="2026-09-27T00:01:00Z",
    )
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        gate_reader=lambda gate_id: decision if gate_id == challenge.gate_id else None,
    )
    source = CapabilityLifecycleAuthoritySource.engineering_gate(
        authority_session_id=SESSION,
        gate_id=challenge.gate_id,
    )

    result = env["lifecycle"].select_version(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
        expected_generation=1,
        authority_session_id=SESSION,
        source=source,
    )

    assert result.changed
    assert env["verifier"].calls == 1
    proposal = env["verifier"].last_proposal
    assert proposal is not None
    assert proposal.origin is ActionOrigin.SYSTEM
    assert proposal.parameters()["source"]["artifact_digest"] == "d" * 64
    assert proposal.parameters()["source"]["change_id"] == "change-phase8e"


def test_unapproved_engineering_gate_cannot_authorize_lifecycle(tmp_path) -> None:
    challenge = GateChallenge(
        gate_id="gate-phase8e",
        change_id="change-phase8e",
        kind=GateKind.ARCHITECTURE,
        artifact_id="artifact-phase8e",
        artifact_digest="d" * 64,
        created_at="2026-09-27T00:00:00Z",
    )
    decision = GateDecision(
        challenge=challenge,
        approved=False,
        actor_id="owner",
        source_session_id="prior-session",
        source_turn_id="prior-turn",
        request_key="phase8e-gate-rejected",
        decided_at="2026-09-27T00:01:00Z",
    )
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        gate_reader=lambda _gate_id: decision,
    )
    source = CapabilityLifecycleAuthoritySource.engineering_gate(
        authority_session_id=SESSION,
        gate_id=challenge.gate_id,
    )

    with pytest.raises(
        CapabilityLifecycleAuthorizationError,
        match="not approved",
    ):
        env["lifecycle"].select_version(
            "example.capability",
            package_id="example.package",
            package_version="1.0.0",
            expected_generation=1,
            authority_session_id=SESSION,
            source=source,
        )

    assert env["store"].require_registry("example.capability").generation == 1


def test_rollback_is_blocked_when_old_descriptor_is_not_in_active_release(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    _select(env, "2.0.0", 1)
    env["package_paths"]["1.0.0"].unlink()

    with pytest.raises(
        CapabilityLifecyclePreconditionError,
        match="not READY",
    ):
        env["lifecycle"].rollback_version(
            "example.capability",
            package_version="1.0.0",
            expected_generation=2,
            authority_session_id=SESSION,
            source=_owner_source(),
        )

    state = env["store"].require_registry("example.capability")
    assert state.generation == 2
    assert state.selected_package_version == "2.0.0"


def test_rollback_rejects_same_or_higher_semver(tmp_path) -> None:
    env = _environment(tmp_path)
    _select(env, "1.0.0", 1)

    with pytest.raises(
        CapabilityLifecyclePreconditionError,
        match="lower SemVer",
    ):
        env["lifecycle"].rollback_version(
            "example.capability",
            package_version="2.0.0",
            expected_generation=2,
            authority_session_id=SESSION,
            source=_owner_source(),
        )


def test_retiring_selected_package_keeps_intent_but_blocks_execution(tmp_path) -> None:
    env = _environment(tmp_path, versions=("1.0.0",))
    _select(env, "1.0.0", 1)
    _enable(env, 2)

    retired = env["lifecycle"].retire_package(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
        expected_generation=3,
        authority_session_id=SESSION,
        source=_owner_source(),
    )

    package = env["store"].get_package("example.package", "1.0.0")
    assert package is not None
    assert package.disposition is PackageDisposition.RETIRED
    assert retired.current_state.generation == 3
    assert retired.current_state.desired_state.value == "enabled"
    assert not retired.snapshot.state("example.capability").effective_enabled
    event = env["store"].list_events("example.capability")[-1]
    assert event.reason_code == "package_retired"
    assert event.authority_ref is not None


def test_integrity_failure_can_auto_quarantine_without_granting_authority(
    tmp_path,
) -> None:
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        with_artifact=True,
    )
    _select(env, "1.0.0", 1)
    _enable(env, 2)
    artifact_result = env["artifact_result"]
    assert artifact_result is not None
    artifact_result.object_path.write_bytes(b"tampered")

    quarantined = env["lifecycle"].quarantine_package_if_unsafe(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
    )

    package = env["store"].get_package("example.package", "1.0.0")
    assert package is not None
    assert package.disposition is PackageDisposition.QUARANTINED
    assert quarantined.action is CapabilityLifecycleAction.QUARANTINE_PACKAGE
    assert quarantined.current_state.desired_state.value == "enabled"
    assert not quarantined.snapshot.state("example.capability").effective_enabled
    event = env["store"].list_events("example.capability")[-1]
    assert event.reason_code == "automatic_safety_quarantine"
    assert event.authority_ref is None
    assert event.evidence_ref == quarantined.compatibility.digest


def test_quarantined_package_cannot_be_restored_or_retired(tmp_path) -> None:
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        with_artifact=True,
    )
    artifact_result = env["artifact_result"]
    assert artifact_result is not None
    artifact_result.object_path.write_bytes(b"tampered")
    env["lifecycle"].quarantine_package_if_unsafe(
        "example.capability",
        package_id="example.package",
        package_version="1.0.0",
    )

    with pytest.raises(
        CapabilityRegistrySelectionError,
        match="terminal",
    ):
        env["store"].set_package_disposition(
            "example.package",
            "1.0.0",
            disposition=PackageDisposition.RETIRED,
            reason_code="should_not_work",
        )


def test_readmission_tightens_existing_package_to_quarantine(tmp_path) -> None:
    env = _environment(
        tmp_path,
        versions=("1.0.0",),
        with_artifact=True,
    )
    artifact_result = env["artifact_result"]
    assert artifact_result is not None
    artifact_result.object_path.write_bytes(b"tampered")
    admission = CapabilityPackageAdmissionService(
        store=env["store"],
        package_source=env["source"],
        evaluator=env["evaluator"],
    )
    sourced = env["source"].packages()[0]

    result = admission.admit(sourced)

    assert result.admitted.disposition is PackageDisposition.QUARANTINED
    package = env["store"].get_package("example.package", "1.0.0")
    assert package is not None
    assert package.disposition is PackageDisposition.QUARANTINED
    event = env["store"].list_events("example.capability")[-1]
    assert event.reason_code == "automatic_admission_quarantine"


def test_retirement_store_rejects_stale_authorized_generation(tmp_path) -> None:
    env = _environment(tmp_path, versions=("1.0.0", "2.0.0"))
    _select(env, "2.0.0", 1)
    _enable(env, 2)
    approved_generation = env["store"].require_registry(
        "example.capability"
    ).generation

    env["lifecycle"].disable(
        "example.capability",
        expected_generation=approved_generation,
        authority_session_id=SESSION,
        source=_owner_source(),
    )

    with pytest.raises(StaleRegistryGenerationError, match="stale registry generation"):
        env["store"].set_package_disposition(
            "example.package",
            "1.0.0",
            disposition=PackageDisposition.RETIRED,
            reason_code="stale_authorized_retirement",
            expected_generation=approved_generation,
            authority_ref="authority:stale:test",
        )

    package = env["store"].get_package("example.package", "1.0.0")
    assert package is not None
    assert package.disposition is PackageDisposition.AVAILABLE


def test_retention_keeps_selected_and_retired_rollback_artifacts(tmp_path) -> None:
    release = _release(tmp_path)
    artifact_store = ArtifactStore(tmp_path / "retention-artifacts")
    manifests = (_manifest("1.0.0"), _manifest("2.0.0"))
    packages: dict[str, CapabilityPackageV1] = {}
    digests: dict[str, str] = {}

    for manifest in manifests:
        payload = f"phase8e-retention-{manifest.capability_version}".encode()
        source_file = tmp_path / f"payload-{manifest.capability_version}.bin"
        source_file.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        artifact_store.admit_file(source_file, expected_sha256=digest)
        artifact = PackageArtifactDescriptorV1(
            role="payload",
            sha256=digest,
            size_bytes=len(payload),
            media_type="application/octet-stream",
        )
        package = _package(manifest, artifacts=(artifact,))
        packages[manifest.capability_version] = package
        digests[manifest.capability_version] = digest
        _write_package(release, package)

    source = ReleaseCapabilityPackageSource(release)
    store = CapabilityRegistryStore(tmp_path / "retention-registry.sqlite3")
    for package in packages.values():
        store.admit_package(
            package,
            admitted_release_sha=RELEASE_SHA,
            evidence_digest=package.digest,
        )

    store.transition_registry(
        "example.capability",
        expected_generation=1,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="1.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="retention_select_v1",
    )
    store.transition_registry(
        "example.capability",
        expected_generation=2,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="2.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="retention_select_v2",
    )
    store.set_package_disposition(
        "example.package",
        "1.0.0",
        disposition=PackageDisposition.RETIRED,
        reason_code="retention_retire_v1",
        expected_generation=3,
    )

    refs = CapabilityArtifactRetentionPlanner(
        store=store,
        package_source=source,
        rollback_depth=1,
    ).references()

    assert set(refs.referenced_sha256) == {
        digests["1.0.0"],
        digests["2.0.0"],
    }


def test_owner_turn_source_must_match_authority_session(tmp_path) -> None:
    env = _environment(tmp_path, versions=("1.0.0",))
    mismatched = CapabilityLifecycleAuthoritySource.owner_turn(
        session_id="other-session",
        turn_id=TURN,
    )

    with pytest.raises(
        CapabilityLifecycleAuthorizationError,
        match="does not match",
    ):
        env["lifecycle"].select_version(
            "example.capability",
            package_id="example.package",
            package_version="1.0.0",
            expected_generation=1,
            authority_session_id=SESSION,
            source=mismatched,
        )
