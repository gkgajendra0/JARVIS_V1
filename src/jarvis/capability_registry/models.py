"""Durable Phase-8 capability-registry state models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.capability_registry.contracts import CapabilityPackageV1


class PackageDisposition(str, Enum):
    AVAILABLE = "available"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


class DesiredActivationState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class CapabilityLifecycleEventKind(str, Enum):
    PACKAGE_ADMITTED = "package_admitted"
    DESIRED_STATE_CHANGED = "desired_state_changed"
    VERSION_SELECTED = "version_selected"
    PACKAGE_RETIRED = "package_retired"
    PACKAGE_QUARANTINED = "package_quarantined"


@dataclass(frozen=True, slots=True)
class AdmittedCapabilityPackage:
    package: CapabilityPackageV1
    package_digest: str
    admitted_release_sha: str
    disposition: PackageDisposition
    admitted_at: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class CapabilityRegistryState:
    capability_id: str
    selected_package_id: str | None
    selected_package_version: str | None
    selected_package_digest: str | None
    desired_state: DesiredActivationState
    generation: int
    updated_at: str

    @property
    def has_selection(self) -> bool:
        return self.selected_package_id is not None


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleEvent:
    event_id: str
    capability_id: str
    package_id: str | None
    package_version: str | None
    package_digest: str | None
    event_kind: CapabilityLifecycleEventKind
    previous_generation: int
    new_generation: int
    reason_code: str
    authority_ref: str | None
    evidence_ref: str | None
    occurred_at: str
    event_digest: str
