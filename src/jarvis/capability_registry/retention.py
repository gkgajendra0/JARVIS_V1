"""Deterministic ArtifactStore retention references for Phase-8 packages."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    PackageDisposition,
)
from jarvis.capability_registry.source import CapabilityPackageSource
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_substrate.artifacts import ArtifactRetentionReferences


class CapabilityArtifactRetentionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityArtifactRetentionPlanner:
    store: CapabilityRegistryStore
    package_source: CapabilityPackageSource
    rollback_depth: int = 2

    def __post_init__(self) -> None:
        if type(self.rollback_depth) is not int or not 0 <= self.rollback_depth <= 20:
            raise ValueError("rollback_depth must be an integer from 0 through 20")

    @staticmethod
    def _artifact_digests(package) -> set[str]:
        return {item.sha256 for item in package.package.artifacts}

    def references(
        self,
        *,
        unresolved_artifact_sha256: tuple[str, ...] = (),
    ) -> ArtifactRetentionReferences:
        retained = set(unresolved_artifact_sha256)
        admitted = {
            (item.package.package_id, item.package.package_version): item
            for item in self.store.list_packages()
        }
        sourced = {
            (item.package.package_id, item.package.package_version): item
            for item in self.package_source.packages()
        }

        for identity, sourced_package in sourced.items():
            record = admitted.get(identity)
            if record is None or record.disposition is not PackageDisposition.AVAILABLE:
                continue
            if record.package_digest != sourced_package.package_digest:
                raise CapabilityArtifactRetentionError(
                    "active-release package descriptor conflicts with admitted identity"
                )
            retained.update(self._artifact_digests(record))

        for state in self.store.list_registry():
            if state.has_selection:
                selected_identity = (
                    state.selected_package_id or "",
                    state.selected_package_version or "",
                )
                selected = admitted.get(selected_identity)
                if selected is None:
                    raise CapabilityArtifactRetentionError(
                        "selected package is missing from admitted retention truth"
                    )
                retained.update(self._artifact_digests(selected))

            if self.rollback_depth <= 0:
                continue
            seen: set[tuple[str, str]] = set()
            selected_identity = (
                (state.selected_package_id or "", state.selected_package_version or "")
                if state.has_selection
                else None
            )
            for event in reversed(self.store.list_events(state.capability_id)):
                if event.event_kind is not CapabilityLifecycleEventKind.VERSION_SELECTED:
                    continue
                if event.package_id is None or event.package_version is None:
                    continue
                identity = (event.package_id, event.package_version)
                if identity == selected_identity or identity in seen:
                    continue
                seen.add(identity)
                prior = admitted.get(identity)
                if prior is not None:
                    retained.update(self._artifact_digests(prior))
                if len(seen) >= self.rollback_depth:
                    break

        return ArtifactRetentionReferences(tuple(sorted(retained)))
