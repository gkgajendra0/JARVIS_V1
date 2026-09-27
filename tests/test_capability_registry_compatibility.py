from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capability_registry.admission import CapabilityPackageAdmissionService
from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CompatibilityReason,
    CompatibilityVerdict,
)
from jarvis.capability_registry.contracts import (
    CapabilityPackageV1,
    PackageArtifactDescriptorV1,
    parse_capability_package_v1,
)
from jarvis.capability_registry.models import PackageDisposition
from jarvis.capability_registry.provider import (
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
)
from jarvis.capability_registry.source import (
    CapabilityPackageSourceError,
    ReleaseCapabilityPackageSource,
)
from jarvis.capability_registry.store import (
    CapabilityRegistryStore,
    PackageVersionReuseConflict,
)
from jarvis.engineering_substrate import CapabilityManifest, canonical_digest
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.promotion.release import ReleaseError, ReleaseRecord

CURRENT_SHA = "a" * 40
OLD_SHA = "b" * 40
PROMOTION_DIGEST = "c" * 64
CONFIG_DIGEST = "d" * 64


class FakeExecutor:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.capability_key = descriptor.key
        self.operations = descriptor.operations

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        raise AssertionError("Phase-8 compatibility must not execute provider prepare")

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        raise AssertionError("Phase-8 compatibility must not execute provider execute")


def _release(tmp_path, *, release_sha: str = CURRENT_SHA) -> ReleaseRecord:
    root = tmp_path / f"release-{release_sha[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return ReleaseRecord(
        release_sha=release_sha,
        release_root=str(root),
        promotion_attempt_id="promotion_phase8c_test",
        promotion_evidence_digest=PROMOTION_DIGEST,
        config_digest=CONFIG_DIGEST,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _manifest(
    *,
    capability_id: str = "example.capability",
    capability_version: str = "1.0.0",
    platform_constraints: tuple[str, ...] = ("linux-amd64",),
    health_probe_ids: tuple[str, ...] = ("health.example.v1",),
    operations: tuple[str, ...] = ("ping",),
) -> CapabilityManifest:
    return CapabilityManifest(
        manifest_id="manifest.example.v1",
        manifest_version=1,
        capability_id=capability_id,
        capability_version=capability_version,
        purpose="Deterministic Phase-8 compatibility test capability.",
        adapter_id="example.adapter.v1",
        executor_id="example.executor.v1",
        operations=operations,
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
            platform_constraint_ids=("linux-amd64", "windows-amd64"),
        ),
    )
    registry.register(manifest)
    return registry


def _descriptor(
    *,
    capability_id: str = "example.capability",
    operations: tuple[str, ...] = ("ping",),
) -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id=capability_id,
        source_id="phase8.test",
        kind=CapabilityKind.NATIVE_API,
        name="Phase 8 Test Capability",
        description="Harmless deterministic Phase-8 provider.",
        operations=operations,
        execution_enabled=True,
    )


def _provider_registry(
    *,
    release_sha: str = CURRENT_SHA,
    capability_id: str = "example.capability",
    operations: tuple[str, ...] = ("ping",),
    runtime_versions: tuple[int, ...] = (1,),
    health_probe_ids: tuple[str, ...] = ("health.example.v1",),
) -> CapabilityProviderRegistry:
    descriptor = _descriptor(
        capability_id=capability_id,
        operations=operations,
    )
    return CapabilityProviderRegistry(
        (
            CapabilityProviderRegistration(
                capability_id=capability_id,
                executor_id="example.executor.v1",
                adapter_id="example.adapter.v1",
                descriptor=descriptor,
                executor=FakeExecutor(descriptor),
                release_sha=release_sha,
                supported_runtime_api_versions=runtime_versions,
                health_probe_ids=health_probe_ids,
            ),
        )
    )


def _package(
    manifest: CapabilityManifest,
    *,
    package_version: str | None = None,
    manifest_digest: str | None = None,
    runtime_api_version: int = 1,
    artifacts: tuple[PackageArtifactDescriptorV1, ...] = (),
) -> CapabilityPackageV1:
    version = package_version or manifest.capability_version
    return parse_capability_package_v1(
        {
            "schema_version": 1,
            "package_id": "example.package",
            "package_version": version,
            "capability_id": manifest.capability_id,
            "package_kind": "extension_source",
            "manifest_id": manifest.manifest_id,
            "manifest_version": manifest.manifest_version,
            "manifest_digest": manifest_digest or canonical_digest(manifest),
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": runtime_api_version,
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _write_package(release: ReleaseRecord, package: CapabilityPackageV1, name: str = "example.json") -> None:
    root = release_root = __import__("pathlib").Path(release.release_root)
    package_root = release_root / "capability_packages"
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / name).write_text(
        json.dumps(package.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )


def _evaluator(
    *,
    manifest: CapabilityManifest,
    package_source: ReleaseCapabilityPackageSource,
    artifact_store: ArtifactStore,
    runtime_release_sha: str = CURRENT_SHA,
    provider_registry: CapabilityProviderRegistry | None = None,
    platform_tags: tuple[str, ...] = ("linux-amd64",),
) -> CapabilityCompatibilityEvaluator:
    return CapabilityCompatibilityEvaluator(
        manifest_registry=_manifest_registry(manifest),
        provider_registry=provider_registry or _provider_registry(
            release_sha=runtime_release_sha
        ),
        artifact_store=artifact_store,
        package_source=package_source,
        runtime_release_sha=runtime_release_sha,
        platform_tags=platform_tags,
    )


def test_release_source_reads_only_fixed_package_directory(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    first = _package(manifest)
    second = parse_capability_package_v1(
        {
            **first.model_dump(mode="json"),
            "package_id": "another.package",
            "package_version": "1.1.0",
        }
    )
    _write_package(release, second, "z.json")
    _write_package(release, first, "a.json")
    package_root = __import__("pathlib").Path(release.release_root) / "capability_packages"
    (package_root / "ignored.txt").write_text("not a package", encoding="utf-8")

    source = ReleaseCapabilityPackageSource(release)
    loaded = source.packages()

    assert [item.relative_path for item in loaded] == [
        "capability_packages/a.json",
        "capability_packages/z.json",
    ]
    assert [item.package.package_id for item in loaded] == [
        "example.package",
        "another.package",
    ]
    assert all(item.release_sha == CURRENT_SHA for item in loaded)


def test_release_source_rejects_duplicate_package_identity(tmp_path) -> None:
    release = _release(tmp_path)
    package = _package(_manifest())
    _write_package(release, package, "a.json")
    _write_package(release, package, "b.json")

    with pytest.raises(CapabilityPackageSourceError, match="duplicate package"):
        ReleaseCapabilityPackageSource(release).packages()


def test_release_source_rejects_json_named_directory(tmp_path) -> None:
    release = _release(tmp_path)
    package_root = __import__("pathlib").Path(release.release_root) / "capability_packages"
    package_root.mkdir()
    (package_root / "escape.json").mkdir()

    with pytest.raises(CapabilityPackageSourceError, match="unsafe"):
        ReleaseCapabilityPackageSource(release).packages()


def test_from_active_release_reuses_phase7_loader(monkeypatch, tmp_path) -> None:
    release = _release(tmp_path)
    monkeypatch.setattr(
        "jarvis.capability_registry.source.load_active_release_for_startup",
        lambda: release,
    )

    source = ReleaseCapabilityPackageSource.from_active_release()

    assert source.release_sha == release.release_sha
    assert source.release_root == __import__("pathlib").Path(release.release_root).resolve()


def test_from_active_release_fails_closed_on_phase7_verification_error(
    monkeypatch,
) -> None:
    def _raise() -> None:
        raise ReleaseError("bad release")

    monkeypatch.setattr(
        "jarvis.capability_registry.source.load_active_release_for_startup",
        _raise,
    )

    with pytest.raises(CapabilityPackageSourceError, match="Phase-7"):
        ReleaseCapabilityPackageSource.from_active_release()


def test_provider_registration_binds_descriptor_and_executor_exactly() -> None:
    descriptor = _descriptor()

    with pytest.raises(ValueError, match="capability_key"):
        CapabilityProviderRegistration(
            capability_id=descriptor.capability_id,
            executor_id="example.executor.v1",
            adapter_id="example.adapter.v1",
            descriptor=descriptor,
            executor=FakeExecutor(
                CapabilityDescriptor.create(
                    capability_id="other.capability",
                    source_id="phase8.test",
                    kind=CapabilityKind.NATIVE_API,
                    name="Other",
                    description="Other",
                    operations=("ping",),
                    execution_enabled=True,
                )
            ),
            release_sha=CURRENT_SHA,
        )


def test_ready_compatibility_report_is_deterministic_and_nonexecuting(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )

    first = evaluator.evaluate_package(package)
    second = evaluator.evaluate_package(package)

    assert first.verdict is CompatibilityVerdict.READY
    assert first.reason_codes == (CompatibilityReason.READY.value,)
    assert first == second
    assert first.digest == second.digest
    assert len(first.digest) == 64


def test_admission_is_disabled_by_default_and_binds_compatibility_digest(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=artifact_store,
    )
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    service = CapabilityPackageAdmissionService(
        store=store,
        package_source=source,
        evaluator=evaluator,
    )

    result = service.admit_all()[0]
    state = store.require_registry(manifest.capability_id)

    assert result.compatibility.verdict is CompatibilityVerdict.READY
    assert result.admitted.evidence_digest == result.compatibility.digest
    assert result.admitted.disposition is PackageDisposition.AVAILABLE
    assert state.desired_state.value == "disabled"
    assert not state.has_selection


def test_manifest_digest_mismatch_is_blocked_and_quarantined(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest, manifest_digest="f" * 64)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )
    service = CapabilityPackageAdmissionService(
        store=CapabilityRegistryStore(tmp_path / "registry.sqlite3"),
        package_source=source,
        evaluator=evaluator,
    )

    result = service.admit_all()[0]

    assert result.quarantined
    assert result.admitted.disposition is PackageDisposition.QUARANTINED
    assert CompatibilityReason.MANIFEST_DIGEST_MISMATCH.value in (
        result.compatibility.reason_codes
    )
    assert result.compatibility.verdict is CompatibilityVerdict.BLOCKED


def test_runtime_release_stale_requires_restart_not_block(tmp_path) -> None:
    release = _release(tmp_path, release_sha=CURRENT_SHA)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        runtime_release_sha=OLD_SHA,
        provider_registry=_provider_registry(release_sha=OLD_SHA),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.RESTART_REQUIRED
    assert report.reason_codes == (CompatibilityReason.RUNTIME_RELEASE_STALE.value,)


def test_missing_provider_blocks_when_runtime_is_current(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_registry=CapabilityProviderRegistry(),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.PROVIDER_MISSING.value in report.reason_codes


def test_runtime_api_mismatch_blocks(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest, runtime_api_version=2)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.RUNTIME_API_UNSUPPORTED.value in report.reason_codes


def test_platform_mismatch_blocks(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest(platform_constraints=("windows-amd64",))
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        platform_tags=("linux-amd64",),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.PLATFORM_UNSUPPORTED.value in report.reason_codes


def test_missing_health_probe_registration_blocks(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_registry=_provider_registry(health_probe_ids=()),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.HEALTH_PROBE_UNREGISTERED.value in report.reason_codes


def test_provider_operation_mismatch_blocks(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest)
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_registry=_provider_registry(operations=("other",)),
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.PROVIDER_OPERATION_MISMATCH.value in report.reason_codes


def test_artifact_integrity_and_provenance_are_verified(tmp_path) -> None:
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    source_file = tmp_path / "payload.bin"
    payload = b"phase8-artifact"
    source_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    artifact_store.admit_file(
        source_file,
        expected_sha256=digest,
        provenance_id="prov.phase8",
    )
    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=len(payload),
        media_type="application/octet-stream",
        provenance_refs=("prov.phase8",),
    )
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest, artifacts=(artifact,))
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=artifact_store,
    )

    report = evaluator.evaluate_package(package)

    assert report.verdict is CompatibilityVerdict.READY
    assert report.artifact_digests == (digest,)


def test_corrupt_artifact_blocks_and_quarantines_package(tmp_path) -> None:
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    source_file = tmp_path / "payload.bin"
    payload = b"phase8-artifact"
    source_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    admitted = artifact_store.admit_file(source_file, expected_sha256=digest)
    admitted.object_path.write_bytes(b"corrupt")

    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=len(payload),
        media_type="application/octet-stream",
    )
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest, artifacts=(artifact,))
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=artifact_store,
    )
    service = CapabilityPackageAdmissionService(
        store=CapabilityRegistryStore(tmp_path / "registry.sqlite3"),
        package_source=source,
        evaluator=evaluator,
    )

    result = service.admit_all()[0]

    assert result.quarantined
    assert CompatibilityReason.ARTIFACT_INTEGRITY_FAILED.value in (
        result.compatibility.reason_codes
    )


def test_missing_artifact_blocks_without_security_quarantine(tmp_path) -> None:
    digest = "9" * 64
    artifact = PackageArtifactDescriptorV1(
        role="payload",
        sha256=digest,
        size_bytes=10,
        media_type="application/octet-stream",
    )
    release = _release(tmp_path)
    manifest = _manifest()
    package = _package(manifest, artifacts=(artifact,))
    _write_package(release, package)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )
    service = CapabilityPackageAdmissionService(
        store=CapabilityRegistryStore(tmp_path / "registry.sqlite3"),
        package_source=source,
        evaluator=evaluator,
    )

    result = service.admit_all()[0]

    assert not result.quarantined
    assert result.admitted.disposition is PackageDisposition.AVAILABLE
    assert result.compatibility.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.ARTIFACT_UNAVAILABLE.value in (
        result.compatibility.reason_codes
    )


def test_version_reuse_conflict_survives_admission_layer(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    original = _package(manifest)
    changed = _package(manifest, manifest_digest="f" * 64)
    _write_package(release, changed)
    source = ReleaseCapabilityPackageSource(release)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=artifact_store,
    )
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    store.admit_package(
        original,
        admitted_release_sha=CURRENT_SHA,
        evidence_digest="1" * 64,
    )
    service = CapabilityPackageAdmissionService(
        store=store,
        package_source=source,
        evaluator=evaluator,
    )

    with pytest.raises(PackageVersionReuseConflict):
        service.admit_all()


def test_descriptor_digest_drift_against_admitted_history_blocks(tmp_path) -> None:
    release = _release(tmp_path)
    manifest = _manifest()
    original = _package(manifest)
    changed = _package(manifest, manifest_digest="f" * 64)
    _write_package(release, changed)
    source = ReleaseCapabilityPackageSource(release)
    evaluator = _evaluator(
        manifest=manifest,
        package_source=source,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )
    admitted = CapabilityRegistryStore(tmp_path / "registry.sqlite3").admit_package(
        original,
        admitted_release_sha=CURRENT_SHA,
        evidence_digest="1" * 64,
    )

    report = evaluator.evaluate(admitted)

    assert report.verdict is CompatibilityVerdict.BLOCKED
    assert CompatibilityReason.DESCRIPTOR_DIGEST_MISMATCH.value in report.reason_codes
