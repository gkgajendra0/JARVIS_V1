from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.promotion import (
    CapabilityAcquisitionReleaseBridge,
    CapabilityAcquisitionReleaseBridgeError,
    ensure_capability_release_bridge_current,
)
from jarvis.capability_registry.admission import CapabilityPackageAdmissionService
from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CompatibilityVerdict,
)
from jarvis.capability_registry.contracts import parse_capability_package_v1
from jarvis.capability_registry.provider import (
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
)
from jarvis.capability_registry.projection import CapabilityRegistryProjection
from jarvis.capability_registry.reconciliation import CapabilityLifecycleReconciler
from jarvis.capability_registry.source import ReleaseCapabilityPackageSource
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.candidate import PromotionCandidateVerifier
from jarvis.promotion.models import PromotionAttemptState
from jarvis.promotion.release import DeploymentMetadataStore, ReleaseRecord
from jarvis.promotion.store import PromotionStore
from jarvis.self_model.health import HealthRegistry
from jarvis.work.store import SQLiteWorkStore

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
DIGEST = "a" * 64
DIFF = "b" * 64
PROMOTION_DIGEST = "c" * 64
CONFIG_DIGEST = "d" * 64
PACKAGE_ID = "tv.control.package"
PACKAGE_VERSION = "1.0.0"
CAPABILITY_ID = "tv.control"


class FakeExecutor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.capability_key = descriptor.key
        self.operations = descriptor.operations

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        raise AssertionError("Phase 9F bridge must not execute capability prepare")

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        raise AssertionError("Phase 9F bridge must not execute capability")


def _descriptor() -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id=CAPABILITY_ID,
        source_id="phase9f.test",
        kind=CapabilityKind.NATIVE_API,
        name="TV control",
        description="Deterministic Phase-9 promotion bridge test capability.",
        operations=("power",),
        execution_enabled=True,
    )


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        manifest_id="tv.control.manifest",
        manifest_version=1,
        capability_id=CAPABILITY_ID,
        capability_version=PACKAGE_VERSION,
        purpose="Phase-9 promoted TV capability.",
        adapter_id="tv.adapter.v1",
        executor_id="tv.executor.v1",
        operations=("power",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=(),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=("tv.verify.v1",),
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="tv.disable.v1",
    )


def _manifest_registry(manifest: CapabilityManifest) -> CapabilityManifestRegistry:
    registry = CapabilityManifestRegistry(
        executors=(
            TrustedExecutorRegistration(
                executor_id="tv.executor.v1",
                adapter_ids=("tv.adapter.v1",),
                operations=("power",),
                authority_attribute_floor=(),
                allowed_secret_scopes=(),
                sandbox_profile_ids=(),
            ),
        ),
        adapters=(
            TrustedAdapterRegistration(
                adapter_id="tv.adapter.v1",
                operations=("power",),
            ),
        ),
        references=ManifestReferenceCatalog(
            verification_contract_ids=("tv.verify.v1",),
            disable_rollback_contract_ids=("tv.disable.v1",),
        ),
    )
    registry.register(manifest)
    return registry


def _provider_registry(
    *,
    release_sha: str = MERGE,
) -> CapabilityProviderRegistry:
    descriptor = _descriptor()
    return CapabilityProviderRegistry(
        (
            CapabilityProviderRegistration(
                capability_id=CAPABILITY_ID,
                executor_id="tv.executor.v1",
                adapter_id="tv.adapter.v1",
                descriptor=descriptor,
                executor=FakeExecutor(descriptor),
                release_sha=release_sha,
            ),
        )
    )


def _package(manifest: CapabilityManifest):
    return parse_capability_package_v1(
        {
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
    )


def _write_package(release: ReleaseRecord, package) -> str:
    root = Path(release.release_root) / "capability_packages"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "tv.control.package.json"
    path.write_text(
        json.dumps(package.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    return "capability_packages/tv.control.package.json"


def _change_and_attempt(tmp_path, *, package_digest: str = DIGEST):
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
    candidate = changes.add_artifact(
        change.change_id,
        kind="capability_candidate",
        payload={
            "candidate_id": "capcand_phase9f",
            "digest": DIGEST,
            "development_work_id": "work_phase9f",
            "branch": "feat/tv-control",
            "source_revision": BASE,
            "commit": HEAD,
            "diff_digest": DIFF,
            "changed_paths": [
                "src/jarvis/tv_control.py",
                "capability_packages/tv.control.package.json",
            ],
            "package_path": "capability_packages/tv.control.package.json",
            "package_id": PACKAGE_ID,
            "package_version": PACKAGE_VERSION,
            "package_digest": package_digest,
            "capability_id": CAPABILITY_ID,
            "protected_surface": {
                "policy_id": "repair.protected_surfaces",
                "policy_version": 5,
                "verdict": "clear",
                "protected": [],
                "unknown_paths": [],
                "clear_paths": [
                    "src/jarvis/tv_control.py",
                    "capability_packages/tv.control.package.json",
                ],
            },
        },
    )
    acceptance = changes.add_artifact(
        change.change_id,
        kind="acceptance",
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
        },
    )
    promotions = PromotionStore(changes)
    attempt = promotions.create_or_get(
        change_id=change.change_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id=str(candidate.payload["candidate_id"]),
        candidate_digest=DIGEST,
        base_sha=BASE,
        head_sha=HEAD,
    )
    return changes, promotions, change, candidate, acceptance, attempt


def _set_change_state(changes: ChangeStore, change_id: str, state: ChangeState) -> None:
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (state.value, change_id),
        )


def _set_attempt_observing(
    changes: ChangeStore,
    attempt_id: str,
    *,
    merge_sha: str = MERGE,
) -> None:
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE promotion_attempts SET state=?, merge_sha=?, version=version+1 "
            "WHERE attempt_id=?",
            (PromotionAttemptState.OBSERVING.value, merge_sha, attempt_id),
        )


def _phase8_stack(tmp_path, release: ReleaseRecord, manifest: CapabilityManifest):
    source = ReleaseCapabilityPackageSource(release)
    providers = _provider_registry(release_sha=release.release_sha)
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry(manifest),
        provider_registry=providers,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        package_source=source,
        runtime_release_sha=release.release_sha,
        platform_tags=("windows-amd64",),
    )
    registry = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    admission = CapabilityPackageAdmissionService(
        store=registry,
        package_source=source,
        evaluator=evaluator,
    )
    projection = CapabilityRegistryProjection(provider_registry=providers)
    reconciler = CapabilityLifecycleReconciler(
        store=registry,
        evaluator=evaluator,
        provider_registry=providers,
        health_registry=HealthRegistry(),
        projection=projection,
    )
    return registry, admission, reconciler


def test_phase7_promotion_verifier_uses_phase9_candidate_artifact(tmp_path) -> None:
    changes, promotions, change, candidate, acceptance, _ = _change_and_attempt(
        tmp_path
    )
    _set_change_state(changes, change.change_id, ChangeState.READY_FOR_PROMOTION)

    verified, attempt = PromotionCandidateVerifier(
        changes,
        promotions,
    ).verify_and_create_attempt(
        change.change_id,
        current_main_sha=BASE,
    )

    assert verified.candidate_artifact_id == candidate.artifact_id
    assert verified.acceptance_artifact_id == acceptance.artifact_id
    assert attempt.candidate_id == "capcand_phase9f"


def test_promoted_package_is_admitted_without_auto_activation(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = _manifest()
    package = _package(manifest)
    changes, promotions, change, _, _, attempt = _change_and_attempt(
        tmp_path,
        package_digest=package.digest,
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = ReleaseRecord(
        release_sha=MERGE,
        release_root=str(release_root),
        promotion_attempt_id=attempt.attempt_id,
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )
    _write_package(release, package)
    _set_change_state(changes, change.change_id, ChangeState.OBSERVING)
    _set_attempt_observing(changes, attempt.attempt_id)

    deployment = DeploymentMetadataStore(tmp_path / "deployment")
    deployment.set_active(release)
    registry, admission, reconciler = _phase8_stack(tmp_path, release, manifest)
    monkeypatch.setattr(
        "jarvis.capability_acquisition.promotion."
        "ensure_capability_candidate_acceptance_current",
        lambda *_args, **_kwargs: None,
    )

    result = CapabilityAcquisitionReleaseBridge(
        changes,
        promotions,
        deployment,
        admission=admission,
        reconciler=reconciler,
    ).reconcile(
        change.change_id,
        attempt_id=attempt.attempt_id,
    )

    state = registry.require_registry(CAPABILITY_ID)
    assert result.admission.compatibility.verdict is CompatibilityVerdict.READY
    assert state.desired_state.value == "disabled"
    assert not state.has_selection
    assert result.admission_artifact.payload["auto_activated"] is False
    assert (
        result.admission_artifact.payload["effective_enabled_after_admission"] is False
    )
    assert result.lifecycle_proposal.proposed_actions == (
        "select_version",
        "enable",
    )
    assert result.lifecycle_proposal.authority_required is True
    current = ensure_capability_release_bridge_current(
        changes,
        deployment,
        change.change_id,
        attempt_id=attempt.attempt_id,
    )
    assert current.artifact_id == result.admission_artifact.artifact_id


def test_bridge_rejects_active_release_that_does_not_match_promotion(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = _manifest()
    package = _package(manifest)
    changes, promotions, change, _, _, attempt = _change_and_attempt(
        tmp_path,
        package_digest=package.digest,
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = ReleaseRecord(
        release_sha="4" * 40,
        release_root=str(release_root),
        promotion_attempt_id=attempt.attempt_id,
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )
    _write_package(release, package)
    _set_change_state(changes, change.change_id, ChangeState.OBSERVING)
    _set_attempt_observing(changes, attempt.attempt_id, merge_sha=MERGE)
    deployment = DeploymentMetadataStore(tmp_path / "deployment")
    deployment.set_active(release)
    _, admission, reconciler = _phase8_stack(tmp_path, release, manifest)
    monkeypatch.setattr(
        "jarvis.capability_acquisition.promotion."
        "ensure_capability_candidate_acceptance_current",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        CapabilityAcquisitionReleaseBridgeError,
        match="active release",
    ):
        CapabilityAcquisitionReleaseBridge(
            changes,
            promotions,
            deployment,
            admission=admission,
            reconciler=reconciler,
        ).reconcile(change.change_id, attempt_id=attempt.attempt_id)


def test_bridge_rejects_candidate_package_digest_drift(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = _manifest()
    package = _package(manifest)
    changes, promotions, change, _, _, attempt = _change_and_attempt(
        tmp_path,
        package_digest=DIGEST,
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = ReleaseRecord(
        release_sha=MERGE,
        release_root=str(release_root),
        promotion_attempt_id=attempt.attempt_id,
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )
    _write_package(release, package)
    _set_change_state(changes, change.change_id, ChangeState.OBSERVING)
    _set_attempt_observing(changes, attempt.attempt_id)
    deployment = DeploymentMetadataStore(tmp_path / "deployment")
    deployment.set_active(release)
    _, admission, reconciler = _phase8_stack(tmp_path, release, manifest)
    monkeypatch.setattr(
        "jarvis.capability_acquisition.promotion."
        "ensure_capability_candidate_acceptance_current",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        CapabilityAcquisitionReleaseBridgeError,
        match="differs from verified",
    ):
        CapabilityAcquisitionReleaseBridge(
            changes,
            promotions,
            deployment,
            admission=admission,
            reconciler=reconciler,
        ).reconcile(change.change_id, attempt_id=attempt.attempt_id)


def test_bridge_blocks_package_when_phase8_provider_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = _manifest()
    package = _package(manifest)
    changes, promotions, change, _, _, attempt = _change_and_attempt(
        tmp_path,
        package_digest=package.digest,
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = ReleaseRecord(
        release_sha=MERGE,
        release_root=str(release_root),
        promotion_attempt_id=attempt.attempt_id,
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )
    _write_package(release, package)
    _set_change_state(changes, change.change_id, ChangeState.OBSERVING)
    _set_attempt_observing(changes, attempt.attempt_id)
    deployment = DeploymentMetadataStore(tmp_path / "deployment")
    deployment.set_active(release)

    source = ReleaseCapabilityPackageSource(release)
    providers = CapabilityProviderRegistry()
    evaluator = CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry(manifest),
        provider_registry=providers,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        package_source=source,
        runtime_release_sha=MERGE,
        platform_tags=("windows-amd64",),
    )
    registry = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    admission = CapabilityPackageAdmissionService(
        store=registry,
        package_source=source,
        evaluator=evaluator,
    )
    projection = CapabilityRegistryProjection(provider_registry=providers)
    reconciler = CapabilityLifecycleReconciler(
        store=registry,
        evaluator=evaluator,
        provider_registry=providers,
        health_registry=HealthRegistry(),
        projection=projection,
    )
    monkeypatch.setattr(
        "jarvis.capability_acquisition.promotion."
        "ensure_capability_candidate_acceptance_current",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        CapabilityAcquisitionReleaseBridgeError,
        match="did not pass Phase-8 compatibility",
    ):
        CapabilityAcquisitionReleaseBridge(
            changes,
            promotions,
            deployment,
            admission=admission,
            reconciler=reconciler,
        ).reconcile(change.change_id, attempt_id=attempt.attempt_id)



def test_release_bridge_current_rejects_candidate_supersession(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = _manifest()
    package = _package(manifest)
    changes, promotions, change, candidate, _, attempt = _change_and_attempt(
        tmp_path,
        package_digest=package.digest,
    )
    release_root = tmp_path / "release-superseded"
    release_root.mkdir()
    release = ReleaseRecord(
        release_sha=MERGE,
        release_root=str(release_root),
        promotion_attempt_id=attempt.attempt_id,
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )
    _write_package(release, package)
    _set_change_state(changes, change.change_id, ChangeState.OBSERVING)
    _set_attempt_observing(changes, attempt.attempt_id)
    deployment = DeploymentMetadataStore(tmp_path / "deployment-superseded")
    deployment.set_active(release)
    _, admission, reconciler = _phase8_stack(
        tmp_path / "phase8-superseded",
        release,
        manifest,
    )
    monkeypatch.setattr(
        "jarvis.capability_acquisition.promotion."
        "ensure_capability_candidate_acceptance_current",
        lambda *_args, **_kwargs: None,
    )
    CapabilityAcquisitionReleaseBridge(
        changes,
        promotions,
        deployment,
        admission=admission,
        reconciler=reconciler,
    ).reconcile(change.change_id, attempt_id=attempt.attempt_id)

    changes.add_artifact(
        change.change_id,
        kind="capability_candidate",
        payload={**candidate.payload, "candidate_id": "capcand_superseded"},
    )

    with pytest.raises(
        CapabilityAcquisitionReleaseBridgeError,
        match="stale or unsafe",
    ):
        ensure_capability_release_bridge_current(
            changes,
            deployment,
            change.change_id,
            attempt_id=attempt.attempt_id,
        )
