"""Read-only capability discovery and catalog merge."""

from __future__ import annotations

from typing import Protocol

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    DiscoverySnapshot,
    DiscoveryState,
)


class CapabilityDiscoveryError(RuntimeError):
    """Expected source-local discovery failure that may be isolated."""


class CapabilityDiscoverySource(Protocol):
    source_id: str

    def discover(self) -> DiscoverySnapshot: ...


class CapabilityResolver:
    def __init__(
        self,
        sources: tuple[CapabilityDiscoverySource, ...]
        | list[CapabilityDiscoverySource],
        *,
        builtins: tuple[CapabilityDescriptor, ...] = (),
    ) -> None:
        self._sources = tuple(sources)
        self._builtins = tuple(builtins)
        source_ids = [source.source_id for source in self._sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("capability discovery source ids must be unique")

    def refresh(self) -> CapabilityCatalog:
        snapshots: list[DiscoverySnapshot] = []
        capabilities: list[CapabilityDescriptor] = list(self._builtins)
        seen = {item.key for item in capabilities}
        if len(seen) != len(capabilities):
            raise ValueError("duplicate built-in capability identity")

        for source in self._sources:
            try:
                snapshot = source.discover()
            except CapabilityDiscoveryError as exc:
                snapshot = DiscoverySnapshot(
                    source_id=source.source_id,
                    state=DiscoveryState.FAILED,
                    reason=str(exc),
                )
            if snapshot.source_id != source.source_id:
                raise ValueError("discovery source returned mismatched source_id")
            snapshots.append(snapshot)
            for capability in snapshot.capabilities:
                if capability.key in seen:
                    raise ValueError("duplicate discovered capability identity")
                seen.add(capability.key)
                capabilities.append(capability)

        return CapabilityCatalog(
            sources=tuple(snapshots),
            capabilities=tuple(sorted(capabilities, key=lambda item: item.key)),
        )
