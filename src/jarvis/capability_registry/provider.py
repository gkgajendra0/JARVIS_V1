"""Release-owned trusted capability provider registrations for Phase 8."""

from __future__ import annotations

import re
from dataclasses import dataclass
from jarvis.capabilities.execution import CapabilityExecutor
from jarvis.capabilities.models import CapabilityDescriptor
from jarvis.engineering_substrate.canonical import canonical_digest

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class CapabilityProviderRegistryError(RuntimeError):
    pass


class DuplicateCapabilityProviderError(CapabilityProviderRegistryError):
    pass


class UnknownCapabilityProviderError(CapabilityProviderRegistryError):
    pass


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _release_sha(value: object) -> str:
    normalized = str(value).strip().casefold()
    if _GIT_SHA.fullmatch(normalized) is None:
        raise ValueError("provider release_sha must be an exact lowercase Git SHA")
    return normalized


@dataclass(frozen=True, slots=True)
class CapabilityProviderRegistration:
    """Trusted source-owned binding from manifest identity to runtime implementation."""

    capability_id: str
    executor_id: str
    adapter_id: str
    descriptor: CapabilityDescriptor
    executor: CapabilityExecutor
    release_sha: str
    runtime_api_id: str = "jarvis.capability_runtime"
    supported_runtime_api_versions: tuple[int, ...] = (1,)
    health_probe_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        capability_id = _token(self.capability_id, field="capability_id")
        executor_id = _token(self.executor_id, field="executor_id")
        adapter_id = _token(self.adapter_id, field="adapter_id")
        runtime_api_id = _token(self.runtime_api_id, field="runtime_api_id")
        release_sha = _release_sha(self.release_sha)
        versions = tuple(sorted(set(self.supported_runtime_api_versions)))
        if not versions or any(type(item) is not int or item <= 0 for item in versions):
            raise ValueError("supported runtime API versions must be positive integers")
        health = tuple(
            sorted({_token(item, field="health_probe_id") for item in self.health_probe_ids})
        )
        if self.descriptor.capability_id != capability_id:
            raise ValueError("provider descriptor capability_id does not match registration")
        if self.executor.capability_key != self.descriptor.key:
            raise ValueError("provider executor capability_key does not match descriptor key")
        if set(self.executor.operations) != set(self.descriptor.operations):
            raise ValueError("provider executor operations do not match descriptor operations")
        if not self.descriptor.execution_enabled:
            raise ValueError("trusted provider descriptor must be execution-enabled")
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "executor_id", executor_id)
        object.__setattr__(self, "adapter_id", adapter_id)
        object.__setattr__(self, "runtime_api_id", runtime_api_id)
        object.__setattr__(self, "release_sha", release_sha)
        object.__setattr__(self, "supported_runtime_api_versions", versions)
        object.__setattr__(self, "health_probe_ids", health)

    @property
    def descriptor_digest(self) -> str:
        return canonical_digest(self.descriptor)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.capability_id, self.executor_id, self.adapter_id)


class CapabilityProviderRegistry:
    """Code-owned provider inventory; package data cannot manufacture registrations."""

    def __init__(self, registrations: tuple[CapabilityProviderRegistration, ...] = ()) -> None:
        self._registrations: dict[
            tuple[str, str, str], CapabilityProviderRegistration
        ] = {}
        for registration in registrations:
            self.register(registration)

    def register(
        self,
        registration: CapabilityProviderRegistration,
    ) -> CapabilityProviderRegistration:
        if not isinstance(registration, CapabilityProviderRegistration):
            raise TypeError("registration must be CapabilityProviderRegistration")
        key = registration.identity
        if key in self._registrations:
            raise DuplicateCapabilityProviderError(
                "trusted capability provider is already registered"
            )
        self._registrations[key] = registration
        return registration

    def get(
        self,
        capability_id: str,
        executor_id: str,
        adapter_id: str,
    ) -> CapabilityProviderRegistration | None:
        key = (
            _token(capability_id, field="capability_id"),
            _token(executor_id, field="executor_id"),
            _token(adapter_id, field="adapter_id"),
        )
        return self._registrations.get(key)

    def require(
        self,
        capability_id: str,
        executor_id: str,
        adapter_id: str,
    ) -> CapabilityProviderRegistration:
        registration = self.get(capability_id, executor_id, adapter_id)
        if registration is None:
            raise UnknownCapabilityProviderError(
                "trusted capability provider is not registered"
            )
        return registration

    def registrations(self) -> tuple[CapabilityProviderRegistration, ...]:
        return tuple(
            self._registrations[key] for key in sorted(self._registrations)
        )
