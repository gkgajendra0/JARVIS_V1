"""Provider-neutral capability discovery models."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CapabilityKind(str, Enum):
    """Execution substrate represented by discovered capability metadata."""

    SEMANTIC_CONNECTOR = "semantic_connector"
    STRUCTURED_AUTOMATION = "structured_automation"
    NATIVE_API = "native_api"
    VISUAL_FALLBACK = "visual_fallback"


class DiscoveryState(str, Enum):
    """Truthful availability state for one discovery source."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


def _clean(value: str, *, field: str, max_length: int = 300) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _metadata_json(value: dict[str, Any] | None) -> str:
    return json.dumps(
        value or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Normalized, non-authoritative metadata about one available capability.

    Discovery metadata never grants execution authority. `execution_enabled` is
    intentionally false for the Step-7 discovery slice.
    """

    capability_id: str
    source_id: str
    kind: CapabilityKind
    name: str
    description: str
    operations: tuple[str, ...] = ()
    metadata_json: str = "{}"
    execution_enabled: bool = False

    @classmethod
    def create(
        cls,
        *,
        capability_id: str,
        source_id: str,
        kind: CapabilityKind,
        name: str,
        description: str,
        operations: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityDescriptor:
        normalized_operations = tuple(
            sorted(
                {
                    _clean(item, field="operation", max_length=120)
                    for item in operations
                    if str(item).strip()
                }
            )
        )
        return cls(
            capability_id=_clean(
                capability_id,
                field="capability_id",
                max_length=180,
            ),
            source_id=_clean(source_id, field="source_id", max_length=120),
            kind=kind,
            name=_clean(name, field="name", max_length=180),
            description=_clean(
                description,
                field="description",
                max_length=1000,
            ),
            operations=normalized_operations,
            metadata_json=_metadata_json(metadata),
            execution_enabled=False,
        )

    @property
    def key(self) -> str:
        return f"{self.source_id}:{self.capability_id}"

    def metadata(self) -> dict[str, Any]:
        decoded = json.loads(self.metadata_json)
        return decoded if isinstance(decoded, dict) else {}

    def search_text(self) -> str:
        return " ".join(
            (
                self.capability_id,
                self.source_id,
                self.kind.value,
                self.name,
                self.description,
                *self.operations,
            )
        ).casefold()


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    """One source's read-only discovery result."""

    source_id: str
    state: DiscoveryState
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    reason: str | None = None
    elapsed_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must not be negative")


@dataclass(frozen=True, slots=True)
class CapabilityCatalog:
    """Merged discovery snapshot across all configured sources."""

    sources: tuple[DiscoverySnapshot, ...]
    capabilities: tuple[CapabilityDescriptor, ...]

    def by_key(self, key: str) -> CapabilityDescriptor | None:
        normalized = str(key).strip()
        for capability in self.capabilities:
            if capability.key == normalized:
                return capability
        return None

    def search(self, query: str) -> tuple[CapabilityDescriptor, ...]:
        tokens = tuple(
            token for token in str(query).casefold().split() if token.strip()
        )
        if not tokens:
            return self.capabilities
        return tuple(
            capability
            for capability in self.capabilities
            if all(token in capability.search_text() for token in tokens)
        )
