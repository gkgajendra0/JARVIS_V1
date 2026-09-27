"""Deterministic Phase-8 package compatibility evidence."""

from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass
from enum import Enum

from jarvis.capability_registry.contracts import CapabilityPackageV1
from jarvis.capability_registry.models import (
    AdmittedCapabilityPackage,
    PackageDisposition,
)
from jarvis.capability_registry.provider import CapabilityProviderRegistry
from jarvis.capability_registry.source import CapabilityPackageSource
from jarvis.engineering_substrate.artifacts import (
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactStore,
    ArtifactStoreError,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestError,
    CapabilityManifestRegistry,
    RegisteredCapabilityManifest,
)

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class CompatibilityVerdict(str, Enum):
    READY = "ready"
    RESTART_REQUIRED = "restart_required"
    BLOCKED = "blocked"


class CompatibilityReason(str, Enum):
    READY = "ready"
    PACKAGE_NOT_AVAILABLE = "package_not_available"
    DESCRIPTOR_NOT_IN_ACTIVE_RELEASE = "descriptor_not_in_active_release"
    DESCRIPTOR_DIGEST_MISMATCH = "descriptor_digest_mismatch"
    MANIFEST_UNKNOWN_OR_INVALID = "manifest_unknown_or_invalid"
    MANIFEST_DIGEST_MISMATCH = "manifest_digest_mismatch"
    MANIFEST_CAPABILITY_MISMATCH = "manifest_capability_mismatch"
    MANIFEST_VERSION_MISMATCH = "manifest_version_mismatch"
    RUNTIME_API_UNSUPPORTED = "runtime_api_unsupported"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    PROVIDER_MISSING = "provider_missing"
    PROVIDER_RELEASE_MISMATCH = "provider_release_mismatch"
    PROVIDER_DESCRIPTOR_MISMATCH = "provider_descriptor_mismatch"
    PROVIDER_OPERATION_MISMATCH = "provider_operation_mismatch"
    HEALTH_PROBE_UNREGISTERED = "health_probe_unregistered"
    ARTIFACT_UNAVAILABLE = "artifact_unavailable"
    ARTIFACT_INTEGRITY_FAILED = "artifact_integrity_failed"
    ARTIFACT_SIZE_MISMATCH = "artifact_size_mismatch"
    ARTIFACT_PROVENANCE_MISSING = "artifact_provenance_missing"
    RUNTIME_RELEASE_STALE = "runtime_release_stale"


@dataclass(frozen=True, slots=True)
class CapabilityCompatibilityReportV1:
    package_id: str
    package_version: str
    package_digest: str
    current_release_sha: str
    runtime_release_sha: str
    platform_tags: tuple[str, ...]
    verdict: CompatibilityVerdict
    reason_codes: tuple[str, ...]
    manifest_digest: str | None
    provider_descriptor_digest: str | None
    artifact_digests: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_digest": self.package_digest,
            "current_release_sha": self.current_release_sha,
            "runtime_release_sha": self.runtime_release_sha,
            "platform_tags": list(self.platform_tags),
            "verdict": self.verdict.value,
            "reason_codes": list(self.reason_codes),
            "manifest_digest": self.manifest_digest,
            "provider_descriptor_digest": self.provider_descriptor_digest,
            "artifact_digests": list(self.artifact_digests),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.payload())


def current_platform_tags() -> tuple[str, ...]:
    system = platform.system().strip().casefold()
    machine = platform.machine().strip().casefold()
    aliases = {system, f"{system}-{machine}"}
    if machine in {"amd64", "x86_64"}:
        aliases.add(f"{system}-amd64")
        aliases.add(f"{system}-x86_64")
    if machine in {"arm64", "aarch64"}:
        aliases.add(f"{system}-arm64")
        aliases.add(f"{system}-aarch64")
    return tuple(sorted(item for item in aliases if item))


class CapabilityCompatibilityEvaluator:
    """Evaluate trusted evidence only; never enable or execute a capability."""

    def __init__(
        self,
        *,
        manifest_registry: CapabilityManifestRegistry,
        provider_registry: CapabilityProviderRegistry,
        artifact_store: ArtifactStore,
        package_source: CapabilityPackageSource,
        runtime_release_sha: str,
        platform_tags: tuple[str, ...] | None = None,
    ) -> None:
        self.manifest_registry = manifest_registry
        self.provider_registry = provider_registry
        self.artifact_store = artifact_store
        self.package_source = package_source
        self.runtime_release_sha = self._release_sha(runtime_release_sha)
        self.platform_tags = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in (platform_tags or current_platform_tags())
                    if str(item).strip()
                }
            )
        )
        if not self.platform_tags:
            raise ValueError("platform_tags must not be empty")

    @staticmethod
    def _release_sha(value: object) -> str:
        normalized = str(value).strip().casefold()
        if _GIT_SHA.fullmatch(normalized) is None:
            raise ValueError("runtime release SHA must be an exact lowercase Git SHA")
        return normalized

    def _manifest(
        self,
        descriptor: CapabilityPackageV1,
        reasons: set[CompatibilityReason],
    ) -> RegisteredCapabilityManifest | None:
        try:
            registered = self.manifest_registry.require(
                descriptor.manifest_id,
                descriptor.manifest_version,
            )
            validated = self.manifest_registry.validate_for_activation(
                registered.manifest
            )
        except CapabilityManifestError:
            reasons.add(CompatibilityReason.MANIFEST_UNKNOWN_OR_INVALID)
            return None
        if validated.manifest_digest != descriptor.manifest_digest:
            reasons.add(CompatibilityReason.MANIFEST_DIGEST_MISMATCH)
        if validated.manifest.capability_id != descriptor.capability_id:
            reasons.add(CompatibilityReason.MANIFEST_CAPABILITY_MISMATCH)
        if validated.manifest.capability_version != descriptor.package_version:
            reasons.add(CompatibilityReason.MANIFEST_VERSION_MISMATCH)
        return validated

    def _verify_artifacts(
        self,
        package: CapabilityPackageV1,
        reasons: set[CompatibilityReason],
    ) -> tuple[str, ...]:
        verified: list[str] = []
        for descriptor in package.artifacts:
            try:
                path = self.artifact_store.verify(descriptor.sha256)
            except ArtifactIntegrityError:
                reasons.add(CompatibilityReason.ARTIFACT_INTEGRITY_FAILED)
                continue
            except (ArtifactPathError, ArtifactStoreError, ValueError):
                reasons.add(CompatibilityReason.ARTIFACT_UNAVAILABLE)
                continue
            if path.stat().st_size != descriptor.size_bytes:
                reasons.add(CompatibilityReason.ARTIFACT_SIZE_MISMATCH)
                continue
            if descriptor.provenance_refs:
                observed: set[str] = set()
                try:
                    records = self.artifact_store.list_admission_records(
                        descriptor.sha256
                    )
                    for record_path in records:
                        payload = json.loads(record_path.read_text(encoding="utf-8"))
                        if not isinstance(payload, dict):
                            raise ValueError(
                                "artifact admission metadata is not an object"
                            )
                        provenance_id = (
                            str(payload.get("provenance_id") or "").strip().casefold()
                        )
                        if provenance_id:
                            observed.add(provenance_id)
                except (
                    OSError,
                    ValueError,
                    json.JSONDecodeError,
                    ArtifactStoreError,
                ):
                    reasons.add(CompatibilityReason.ARTIFACT_PROVENANCE_MISSING)
                    continue
                required = {item.casefold() for item in descriptor.provenance_refs}
                if not required.issubset(observed):
                    reasons.add(CompatibilityReason.ARTIFACT_PROVENANCE_MISSING)
                    continue
            verified.append(descriptor.sha256)
        return tuple(sorted(verified))

    def evaluate_package(
        self,
        descriptor: CapabilityPackageV1,
        *,
        disposition: PackageDisposition = PackageDisposition.AVAILABLE,
    ) -> CapabilityCompatibilityReportV1:
        if not isinstance(descriptor, CapabilityPackageV1):
            raise TypeError("descriptor must be CapabilityPackageV1")
        if not isinstance(disposition, PackageDisposition):
            raise TypeError("disposition must be PackageDisposition")
        reasons: set[CompatibilityReason] = set()
        current_release_sha = self._release_sha(self.package_source.release_sha)

        if disposition is not PackageDisposition.AVAILABLE:
            reasons.add(CompatibilityReason.PACKAGE_NOT_AVAILABLE)

        sourced = None
        for candidate in self.package_source.packages():
            if (
                candidate.package.package_id == descriptor.package_id
                and candidate.package.package_version == descriptor.package_version
            ):
                sourced = candidate
                break
        if sourced is None:
            reasons.add(CompatibilityReason.DESCRIPTOR_NOT_IN_ACTIVE_RELEASE)
        elif sourced.package_digest != descriptor.digest:
            reasons.add(CompatibilityReason.DESCRIPTOR_DIGEST_MISMATCH)

        manifest = self._manifest(descriptor, reasons)
        provider_descriptor_digest: str | None = None
        provider = None
        if manifest is not None:
            if manifest.manifest.platform_constraints:
                if not set(manifest.manifest.platform_constraints).intersection(
                    self.platform_tags
                ):
                    reasons.add(CompatibilityReason.PLATFORM_UNSUPPORTED)
            provider = self.provider_registry.get(
                descriptor.capability_id,
                manifest.manifest.executor_id,
                manifest.manifest.adapter_id,
            )
            if provider is None:
                if self.runtime_release_sha == current_release_sha:
                    reasons.add(CompatibilityReason.PROVIDER_MISSING)
            else:
                provider_descriptor_digest = provider.descriptor_digest
                if provider.release_sha != self.runtime_release_sha:
                    reasons.add(CompatibilityReason.PROVIDER_RELEASE_MISMATCH)
                if provider.runtime_api_id != descriptor.runtime_api_id or (
                    descriptor.runtime_api_version
                    not in provider.supported_runtime_api_versions
                ):
                    reasons.add(CompatibilityReason.RUNTIME_API_UNSUPPORTED)
                if provider.descriptor.capability_id != descriptor.capability_id:
                    reasons.add(CompatibilityReason.PROVIDER_DESCRIPTOR_MISMATCH)
                if set(provider.descriptor.operations) != set(
                    manifest.manifest.operations
                ):
                    reasons.add(CompatibilityReason.PROVIDER_OPERATION_MISMATCH)
                if not set(manifest.manifest.health_probe_ids).issubset(
                    set(provider.health_probe_ids)
                ):
                    reasons.add(CompatibilityReason.HEALTH_PROBE_UNREGISTERED)

        artifact_digests = self._verify_artifacts(descriptor, reasons)

        restart_required = self.runtime_release_sha != current_release_sha
        if restart_required:
            reasons.add(CompatibilityReason.RUNTIME_RELEASE_STALE)

        blocking = {
            reason
            for reason in reasons
            if reason is not CompatibilityReason.RUNTIME_RELEASE_STALE
        }
        if blocking:
            verdict = CompatibilityVerdict.BLOCKED
        elif restart_required:
            verdict = CompatibilityVerdict.RESTART_REQUIRED
        else:
            verdict = CompatibilityVerdict.READY
            reasons.add(CompatibilityReason.READY)

        return CapabilityCompatibilityReportV1(
            package_id=descriptor.package_id,
            package_version=descriptor.package_version,
            package_digest=descriptor.digest,
            current_release_sha=current_release_sha,
            runtime_release_sha=self.runtime_release_sha,
            platform_tags=self.platform_tags,
            verdict=verdict,
            reason_codes=tuple(sorted(reason.value for reason in reasons)),
            manifest_digest=None if manifest is None else manifest.manifest_digest,
            provider_descriptor_digest=provider_descriptor_digest,
            artifact_digests=artifact_digests,
        )

    def evaluate(
        self,
        package: AdmittedCapabilityPackage,
    ) -> CapabilityCompatibilityReportV1:
        if not isinstance(package, AdmittedCapabilityPackage):
            raise TypeError("package must be AdmittedCapabilityPackage")
        return self.evaluate_package(
            package.package,
            disposition=package.disposition,
        )
