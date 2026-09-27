"""In-process effective capability projection and transition fencing for Phase 8."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock

from jarvis.capabilities.models import CapabilityCatalog, CapabilityDescriptor
from jarvis.capability_registry.compatibility import CompatibilityVerdict
from jarvis.capability_registry.models import (
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.provider import CapabilityProviderRegistry
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.self_model.health import HealthState
from jarvis.self_model.models import ComponentDescriptor
from jarvis.self_model.registry import SelfModelRegistry

_COMPONENT_ID_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,179}$")


class CapabilityManagementMode(str, Enum):
    CORE_PINNED = "core_pinned"
    PACKAGE_MANAGED = "package_managed"


@dataclass(frozen=True, slots=True)
class CapabilityInventoryEntry:
    capability_id: str
    capability_key: str
    management_mode: CapabilityManagementMode


@dataclass(frozen=True, slots=True)
class EffectiveCapabilityState:
    capability_id: str
    capability_key: str | None
    component_id: str
    management_mode: CapabilityManagementMode
    registry_generation: int
    applied_generation: int
    desired_state: DesiredActivationState
    selected_package_id: str | None
    selected_package_version: str | None
    selected_package_digest: str | None
    package_disposition: PackageDisposition | None
    compatibility_verdict: CompatibilityVerdict | None
    compatibility_digest: str | None
    health_state: HealthState
    transition_fenced: bool
    effective_enabled: bool
    reason_codes: tuple[str, ...]
    required_health_probe_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityEffectiveSnapshot:
    release_sha: str
    states: tuple[EffectiveCapabilityState, ...]
    reconciled_at_epoch: float
    trigger: str

    def state(self, capability_id: str) -> EffectiveCapabilityState | None:
        normalized = str(capability_id).strip().casefold()
        return next(
            (item for item in self.states if item.capability_id == normalized),
            None,
        )

    def state_for_key(self, capability_key: str) -> EffectiveCapabilityState | None:
        normalized = str(capability_key).strip()
        return next(
            (item for item in self.states if item.capability_key == normalized),
            None,
        )

    def payload(self) -> dict[str, object]:
        return {
            "release_sha": self.release_sha,
            "reconciled_at_epoch": self.reconciled_at_epoch,
            "trigger": self.trigger,
            "states": [
                {
                    "capability_id": item.capability_id,
                    "capability_key": item.capability_key,
                    "component_id": item.component_id,
                    "management_mode": item.management_mode.value,
                    "registry_generation": item.registry_generation,
                    "applied_generation": item.applied_generation,
                    "desired_state": item.desired_state.value,
                    "selected_package_id": item.selected_package_id,
                    "selected_package_version": item.selected_package_version,
                    "selected_package_digest": item.selected_package_digest,
                    "package_disposition": (
                        None
                        if item.package_disposition is None
                        else item.package_disposition.value
                    ),
                    "compatibility_verdict": (
                        None
                        if item.compatibility_verdict is None
                        else item.compatibility_verdict.value
                    ),
                    "compatibility_digest": item.compatibility_digest,
                    "health_state": item.health_state.value,
                    "transition_fenced": item.transition_fenced,
                    "effective_enabled": item.effective_enabled,
                    "reason_codes": list(item.reason_codes),
                    "required_health_probe_ids": list(item.required_health_probe_ids),
                }
                for item in self.states
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.payload())


def package_component_id(capability_id: str) -> str:
    normalized = str(capability_id).strip().casefold()
    candidate = f"capability.package:{normalized}"
    if _COMPONENT_ID_SAFE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"capability.package:id-{digest}"


class CapabilityTransitionFence:
    """Per-capability in-process routing fence used around lifecycle mutation."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = RLock()

    @staticmethod
    def _capability_id(value: str) -> str:
        normalized = str(value).strip().casefold()
        if not normalized:
            raise ValueError("capability_id must not be empty")
        return normalized

    def is_fenced(self, capability_id: str) -> bool:
        normalized = self._capability_id(capability_id)
        with self._lock:
            return self._counts.get(normalized, 0) > 0

    @contextmanager
    def hold(self, capability_id: str) -> Iterator[None]:
        normalized = self._capability_id(capability_id)
        with self._lock:
            self._counts[normalized] = self._counts.get(normalized, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                remaining = self._counts.get(normalized, 0) - 1
                if remaining <= 0:
                    self._counts.pop(normalized, None)
                else:
                    self._counts[normalized] = remaining


class CapabilityRegistryProjection:
    """Atomic effective snapshot used by the routing hot path without SQLite reads."""

    def __init__(
        self,
        *,
        provider_registry: CapabilityProviderRegistry,
        transition_fence: CapabilityTransitionFence | None = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.transition_fence = transition_fence or CapabilityTransitionFence()
        self._lock = RLock()
        self._snapshot: CapabilityEffectiveSnapshot | None = None
        self._managed_keys: dict[str, str] = {}
        for registration in provider_registry.registrations():
            key = registration.descriptor.key
            existing = self._managed_keys.get(key)
            if existing is not None and existing != registration.capability_id:
                raise ValueError(
                    "provider descriptor key maps to multiple capabilities"
                )
            self._managed_keys[key] = registration.capability_id

    @property
    def snapshot(self) -> CapabilityEffectiveSnapshot | None:
        with self._lock:
            return self._snapshot

    def install(self, snapshot: CapabilityEffectiveSnapshot) -> None:
        if not isinstance(snapshot, CapabilityEffectiveSnapshot):
            raise TypeError("snapshot must be CapabilityEffectiveSnapshot")
        capability_ids = [item.capability_id for item in snapshot.states]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("effective snapshot capability ids must be unique")
        keys = [
            item.capability_key
            for item in snapshot.states
            if item.capability_key is not None
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("effective snapshot capability keys must be unique")
        if any(
            item.applied_generation > item.registry_generation
            for item in snapshot.states
        ):
            raise ValueError("applied generation cannot exceed registry generation")
        with self._lock:
            self._snapshot = snapshot

    def managed_capability_id(self, capability_key: str) -> str | None:
        return self._managed_keys.get(str(capability_key).strip())

    def allows(self, capability_key: str) -> bool:
        key = str(capability_key).strip()
        capability_id = self._managed_keys.get(key)
        if capability_id is None:
            return True
        if self.transition_fence.is_fenced(capability_id):
            return False
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None:
            return False
        state = snapshot.state(capability_id)
        if state is None or state.capability_key != key:
            return False
        return bool(
            state.effective_enabled
            and not state.transition_fenced
            and state.applied_generation == state.registry_generation
        )

    def project(self, catalog: CapabilityCatalog) -> CapabilityCatalog:
        capabilities: list[CapabilityDescriptor] = []
        for descriptor in catalog.capabilities:
            capability_id = self._managed_keys.get(descriptor.key)
            if capability_id is None:
                capabilities.append(descriptor)
                continue
            capabilities.append(
                replace(
                    descriptor,
                    execution_enabled=(
                        descriptor.execution_enabled and self.allows(descriptor.key)
                    ),
                )
            )
        return CapabilityCatalog(
            sources=catalog.sources,
            capabilities=tuple(capabilities),
        )

    def inventory(
        self,
        catalog: CapabilityCatalog,
    ) -> tuple[CapabilityInventoryEntry, ...]:
        return tuple(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=(
                    CapabilityManagementMode.PACKAGE_MANAGED
                    if descriptor.key in self._managed_keys
                    else CapabilityManagementMode.CORE_PINNED
                ),
            )
            for descriptor in catalog.capabilities
        )

    def fail_closed(self, reason_code: str) -> CapabilityEffectiveSnapshot | None:
        normalized_reason = str(reason_code).strip().casefold()
        if not normalized_reason:
            raise ValueError("reason_code must not be empty")
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None:
                return None
            blocked = tuple(
                replace(
                    item,
                    transition_fenced=(
                        item.transition_fenced
                        or self.transition_fence.is_fenced(item.capability_id)
                    ),
                    effective_enabled=False,
                    reason_codes=tuple(sorted({*item.reason_codes, normalized_reason})),
                )
                for item in snapshot.states
            )
            replacement = replace(snapshot, states=blocked, trigger=normalized_reason)
            self._snapshot = replacement
            return replacement


class CapabilitySelfModelProjection:
    """Expose package-managed lifecycle components through the canonical Self Model."""

    def project(
        self,
        base: SelfModelRegistry,
        snapshot: CapabilityEffectiveSnapshot,
    ) -> SelfModelRegistry:
        existing = {item.component_id for item in base.components}
        parent = "capability_runtime" if base.component("capability_runtime") else None
        dynamic: list[ComponentDescriptor] = []
        for state in snapshot.states:
            if state.management_mode is not CapabilityManagementMode.PACKAGE_MANAGED:
                continue
            if state.component_id in existing:
                continue
            dynamic.append(
                ComponentDescriptor(
                    component_id=state.component_id,
                    purpose=(
                        "Package-managed capability lifecycle, compatibility and "
                        f"health projection for {state.capability_id}."
                    ),
                    source_paths=("src/jarvis/capability_registry",),
                    parent_component_id=parent,
                    health_surface=True,
                    capability_keys=(
                        () if state.capability_key is None else (state.capability_key,)
                    ),
                    health_probes=state.required_health_probe_ids,
                    docs=("docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ARCHITECTURE.md",),
                )
            )
        return SelfModelRegistry(
            components=base.components + tuple(dynamic),
            dependencies=base.dependencies,
        )
