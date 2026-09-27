"""Read-only live capability context providers for Phase-9 acquisition."""

from __future__ import annotations

from typing import Protocol

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
    CapabilityRegistryProjection,
)


class AcquisitionContextProvider(Protocol):
    def current(self) -> AcquisitionContextV1: ...


class StaticAcquisitionContextProvider:
    def __init__(self, context: AcquisitionContextV1) -> None:
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")
        self._context = context

    def current(self) -> AcquisitionContextV1:
        return self._context


class CapabilityRuntimeAcquisitionContextProvider:
    """Project the canonical runtime catalog plus optional Phase-8 lifecycle view."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        *,
        projection: CapabilityRegistryProjection | None = None,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be CapabilityRuntime")
        if projection is not None and not isinstance(
            projection,
            CapabilityRegistryProjection,
        ):
            raise TypeError("projection must be CapabilityRegistryProjection or None")
        self._runtime = runtime
        self._projection = projection

    def current(self) -> AcquisitionContextV1:
        catalog = self._runtime.catalog
        if self._projection is None:
            inventory = tuple(
                CapabilityInventoryEntry(
                    capability_id=descriptor.capability_id,
                    capability_key=descriptor.key,
                    management_mode=CapabilityManagementMode.CORE_PINNED,
                )
                for descriptor in catalog.capabilities
            )
            snapshot = None
        else:
            inventory = self._projection.inventory(catalog)
            snapshot = self._projection.snapshot
        return AcquisitionContextV1(
            catalog=catalog,
            inventory=inventory,
            effective_snapshot=snapshot,
        )
