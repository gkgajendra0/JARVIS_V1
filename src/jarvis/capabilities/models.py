"""Provider-neutral capability discovery and execution models."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.authority.types import ActionOrigin


class CapabilityKind(str, Enum):
    """Execution substrate represented by capability metadata."""

    SEMANTIC_CONNECTOR = "semantic_connector"
    STRUCTURED_AUTOMATION = "structured_automation"
    NATIVE_API = "native_api"
    VISUAL_FALLBACK = "visual_fallback"
    LOCAL_READ = "local_read"
    DISCOVERED_SERVICE = "discovered_service"


class DiscoveryState(str, Enum):
    """Truthful availability state for one discovery source."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class CapabilityStatus(str, Enum):
    """Normalized Step-7 execution result state."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    DENIED = "denied"
    INVALID = "invalid"
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
class CapabilitySemanticMetadata:
    """Optional normalized semantic metadata layered over legacy descriptors."""

    semantic_capability_family: str | None = None
    target_entity_types: tuple[str, ...] = ()
    operation_effects: tuple[tuple[str, str], ...] = ()
    observation_operations: tuple[str, ...] = ()
    idempotent_operations: tuple[str, ...] = ()
    reversible_operations: tuple[str, ...] = ()
    acquisition_target_hints: tuple[str, ...] = ()

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> CapabilitySemanticMetadata:
        def text(value: object) -> str | None:
            normalized = str(value or "").strip().casefold()
            return normalized or None

        def strings(value: object) -> tuple[str, ...]:
            raw = (value,) if isinstance(value, str) else value
            if not isinstance(raw, (list, tuple, set)):
                return ()
            return tuple(
                sorted(
                    {str(item).strip().casefold() for item in raw if str(item).strip()}
                )
            )

        family = text(metadata.get("semantic_capability_family"))
        raw_effects = metadata.get("operation_effects", {})
        effects: tuple[tuple[str, str], ...] = ()
        if isinstance(raw_effects, dict):
            effects = tuple(
                sorted(
                    (
                        str(operation).strip().casefold(),
                        str(effect).strip().casefold(),
                    )
                    for operation, effect in raw_effects.items()
                    if str(operation).strip() and str(effect).strip()
                )
            )
        return cls(
            semantic_capability_family=family,
            target_entity_types=strings(metadata.get("target_entity_types", ())),
            operation_effects=effects,
            observation_operations=strings(metadata.get("observation_operations", ())),
            idempotent_operations=strings(metadata.get("idempotent_operations", ())),
            reversible_operations=strings(metadata.get("reversible_operations", ())),
            acquisition_target_hints=strings(
                metadata.get("acquisition_target_hints", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Normalized metadata describing one available or built-in capability."""

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
        execution_enabled: bool = False,
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
            execution_enabled=bool(execution_enabled),
        )

    @property
    def key(self) -> str:
        return f"{self.source_id}:{self.capability_id}"

    def metadata(self) -> dict[str, Any]:
        decoded = json.loads(self.metadata_json)
        return decoded if isinstance(decoded, dict) else {}

    def semantic_metadata(self) -> CapabilitySemanticMetadata:
        return CapabilitySemanticMetadata.from_metadata(self.metadata())

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
        tokens = tuple(token for token in str(query).casefold().split() if token)
        if not tokens:
            return self.capabilities
        return tuple(
            item
            for item in self.capabilities
            if all(token in item.search_text() for token in tokens)
        )


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    session_id: str
    capability_key: str
    operation: str
    parameters: dict[str, Any]
    origin: ActionOrigin = ActionOrigin.DIRECT_USER

    def __post_init__(self) -> None:
        _clean(self.session_id, field="session_id", max_length=180)
        _clean(self.capability_key, field="capability_key", max_length=300)
        _clean(self.operation, field="operation", max_length=120)
        if not isinstance(self.parameters, dict):
            raise TypeError("capability parameters must be an object")


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    status: CapabilityStatus
    capability_key: str
    operation: str
    data: dict[str, Any]
    reason: str | None = None
    elapsed_ms: float = 0.0
    truncated: bool = False
    provenance: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in {CapabilityStatus.SUCCEEDED, CapabilityStatus.PARTIAL}
