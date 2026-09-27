"""Non-executing Phase-8 package admission bound to compatibility evidence."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CapabilityCompatibilityReportV1,
    CompatibilityReason,
)
from jarvis.capability_registry.models import (
    AdmittedCapabilityPackage,
    PackageDisposition,
)
from jarvis.capability_registry.source import (
    CapabilityPackageSource,
    SourcedCapabilityPackage,
)
from jarvis.capability_registry.store import CapabilityRegistryStore

_QUARANTINE_REASONS = frozenset(
    {
        CompatibilityReason.DESCRIPTOR_DIGEST_MISMATCH.value,
        CompatibilityReason.MANIFEST_DIGEST_MISMATCH.value,
        CompatibilityReason.MANIFEST_CAPABILITY_MISMATCH.value,
        CompatibilityReason.MANIFEST_VERSION_MISMATCH.value,
        CompatibilityReason.ARTIFACT_INTEGRITY_FAILED.value,
        CompatibilityReason.ARTIFACT_SIZE_MISMATCH.value,
        CompatibilityReason.ARTIFACT_PROVENANCE_MISSING.value,
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityPackageAdmissionResult:
    admitted: AdmittedCapabilityPackage
    compatibility: CapabilityCompatibilityReportV1

    @property
    def quarantined(self) -> bool:
        return self.admitted.disposition is PackageDisposition.QUARANTINED


class CapabilityPackageAdmissionService:
    """Admit release descriptors as evidence only; never authorize activation."""

    def __init__(
        self,
        *,
        store: CapabilityRegistryStore,
        package_source: CapabilityPackageSource,
        evaluator: CapabilityCompatibilityEvaluator,
    ) -> None:
        self.store = store
        self.package_source = package_source
        self.evaluator = evaluator
        if evaluator.package_source is not package_source:
            raise ValueError(
                "evaluator and admission service must use the same package source"
            )

    @staticmethod
    def _disposition(
        report: CapabilityCompatibilityReportV1,
    ) -> PackageDisposition:
        if set(report.reason_codes).intersection(_QUARANTINE_REASONS):
            return PackageDisposition.QUARANTINED
        return PackageDisposition.AVAILABLE

    def admit(
        self,
        sourced: SourcedCapabilityPackage,
    ) -> CapabilityPackageAdmissionResult:
        if not isinstance(sourced, SourcedCapabilityPackage):
            raise TypeError("sourced must be SourcedCapabilityPackage")
        if sourced.release_sha != self.package_source.release_sha:
            raise ValueError(
                "sourced package release does not match active package source"
            )
        report = self.evaluator.evaluate_package(sourced.package)
        disposition = self._disposition(report)
        admitted = self.store.admit_package(
            sourced.package,
            admitted_release_sha=sourced.release_sha,
            evidence_digest=report.digest,
            disposition=disposition,
        )
        return CapabilityPackageAdmissionResult(
            admitted=admitted,
            compatibility=self.evaluator.evaluate(admitted),
        )

    def admit_all(self) -> tuple[CapabilityPackageAdmissionResult, ...]:
        return tuple(self.admit(item) for item in self.package_source.packages())
