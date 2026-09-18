"""Canonical static descriptors for JARVIS operational self-knowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,179}$")


def _identifier(value: str, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid {field}: {value!r}")
    return normalized


def _text(value: str, *, field: str, max_length: int = 1000) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _unique_text(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


class DependencyCriticality(str, Enum):
    """How dependency health should affect the source component."""

    BLOCKING = "blocking"
    DEGRADING = "degrading"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class DependencyDescriptor:
    source_component_id: str
    target_component_id: str
    relation: str = "depends_on"
    criticality: DependencyCriticality = DependencyCriticality.BLOCKING
    fallback_component_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_component_id",
            _identifier(self.source_component_id, field="source_component_id"),
        )
        object.__setattr__(
            self,
            "target_component_id",
            _identifier(self.target_component_id, field="target_component_id"),
        )
        object.__setattr__(
            self,
            "relation",
            _identifier(self.relation, field="relation"),
        )
        if self.fallback_component_id is not None:
            object.__setattr__(
                self,
                "fallback_component_id",
                _identifier(self.fallback_component_id, field="fallback_component_id"),
            )


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    resource_id: str
    kind: str
    description: str
    sensitive: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_id",
            _identifier(self.resource_id, field="resource_id"),
        )
        object.__setattr__(self, "kind", _identifier(self.kind, field="kind"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, field="description"),
        )


@dataclass(frozen=True, slots=True)
class ComponentDescriptor:
    """Version-controlled facts describing one operational JARVIS component."""

    component_id: str
    purpose: str
    source_paths: tuple[str, ...]
    owner: str = "jarvis"
    lifecycle: str = "active"
    product_capabilities: tuple[str, ...] = ()
    capability_keys: tuple[str, ...] = ()
    code_symbols: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    config_keys: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    health_probes: tuple[str, ...] = ()
    stale_after_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _identifier(self.component_id, field="component_id"),
        )
        object.__setattr__(self, "purpose", _text(self.purpose, field="purpose"))
        object.__setattr__(self, "owner", _identifier(self.owner, field="owner"))
        object.__setattr__(
            self,
            "lifecycle",
            _identifier(self.lifecycle, field="lifecycle"),
        )
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        for field_name in (
            "source_paths",
            "product_capabilities",
            "capability_keys",
            "code_symbols",
            "tests",
            "config_keys",
            "docs",
            "resources",
            "health_probes",
        ):
            object.__setattr__(
                self,
                field_name,
                _unique_text(getattr(self, field_name)),
            )
        if not self.source_paths:
            raise ValueError("component source_paths must not be empty")
