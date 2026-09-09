"""Capability discovery source contract and resolver."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    DiscoverySnapshot,
    DiscoveryState,
)


class CapabilityDiscoverySourceError(RuntimeError):
    """Declared source failure that the resolver may isolate truthfully."""


class CapabilityDiscoverySource(Protocol):
    """Read-only source of capability metadata."""

    @property
    def source_id(self) -> str: ...

    def discover(self) -> DiscoverySnapshot: ...


class CapabilityResolver:
    """Merge read-only capability metadata without granting execution authority."""

    def __init__(self, sources: Iterable[CapabilityDiscoverySource]) -> None:
        self._sources = tuple(sources)
        source_ids = [source.source_id for source in self._sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("capability discovery source ids must be unique")

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self._sources)

    def refresh(self) -> CapabilityCatalog:
        snapshots: list[DiscoverySnapshot] = []
        merged: dict[str, CapabilityDescriptor] = {}

        for source in self._sources:
            try:
                snapshot = source.discover()
            except CapabilityDiscoverySourceError as exc:
                snapshot = DiscoverySnapshot(
                    source_id=source.source_id,
                    state=DiscoveryState.FAILED,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            snapshots.append(snapshot)

            for capability in snapshot.capabilities:
                if capability.source_id != snapshot.source_id:
                    raise ValueError(
                        "capability source_id must match its discovery snapshot"
                    )
                if capability.key in merged:
                    raise ValueError(
                        f"duplicate discovered capability identity: {capability.key}"
                    )
                merged[capability.key] = capability

        return CapabilityCatalog(
            sources=tuple(snapshots),
            capabilities=tuple(merged[key] for key in sorted(merged)),
        )
