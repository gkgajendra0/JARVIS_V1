"""Deterministic GICC world/entity registry and resolver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.capabilities.models import CapabilityCatalog

from .models import EntityLifecycleState, ResourceBindingV1, WorldEntityRefV1
from .store import GoalStore


class EntityResolutionState(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class EntityResolution:
    state: EntityResolutionState
    entity_id: str | None = None
    candidate_entity_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, EntityResolutionState):
            raise TypeError("state must be EntityResolutionState")
        if self.state is EntityResolutionState.RESOLVED:
            if self.entity_id is None:
                raise ValueError("resolved entity result requires entity_id")
            if self.candidate_entity_ids:
                raise ValueError("resolved entity result cannot contain candidates")
        elif self.entity_id is not None:
            raise ValueError("non-resolved entity result cannot contain entity_id")
        if self.state is EntityResolutionState.AMBIGUOUS:
            if len(self.candidate_entity_ids) < 2:
                raise ValueError("ambiguous entity result requires multiple candidates")


class BoundedEntityDiscovery(Protocol):
    """Read-only bounded discovery. Implementations must not mutate devices/resources."""

    discovery_id: str

    def discover(
        self,
        *,
        mention: str,
        expected_entity_types: tuple[str, ...],
    ) -> tuple[WorldEntityRefV1, ...]: ...


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _generic_reference_types(mention: str) -> tuple[str, ...]:
    normalized = _normalize(mention)
    tokens = set(normalized.replace("-", " ").split())
    inferred: list[str] = []
    if "tv" in tokens or "television" in tokens:
        inferred.append("media_player")
    if "camera" in tokens or "cam" in tokens:
        inferred.append("camera")
    if "computer" in tokens or "pc" in tokens or "laptop" in tokens:
        inferred.append("computer")
    if "display" in tokens or "monitor" in tokens or "screen" in tokens:
        inferred.append("display")
    if "gate" in tokens or "door" in tokens or "entrance" in tokens:
        inferred.append("entrance")
    if "app" in tokens or "application" in tokens:
        inferred.append("application")
    return tuple(sorted(set(inferred)))


class WorldRegistry:
    """Thin canonical registry facade; no duplicate device truth is introduced."""

    def __init__(self, store: GoalStore) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        self._store = store

    @property
    def store(self) -> GoalStore:
        return self._store

    def register_entity(self, entity: WorldEntityRefV1) -> WorldEntityRefV1:
        return self._store.put_entity(entity)

    def register_binding(self, binding: ResourceBindingV1) -> ResourceBindingV1:
        return self._store.put_resource_binding(binding)

    def entities(self) -> tuple[WorldEntityRefV1, ...]:
        return self._store.list_entities(limit=200)

    def bindings(
        self,
        *,
        entity_id: str | None = None,
    ) -> tuple[ResourceBindingV1, ...]:
        return self._store.list_resource_bindings(entity_id=entity_id, limit=200)

    def project_current_computer(
        self,
        catalog: CapabilityCatalog,
    ) -> tuple[WorldEntityRefV1, ResourceBindingV1]:
        """Project capability truth onto one stable local-computer resource identity."""

        if not isinstance(catalog, CapabilityCatalog):
            raise TypeError("catalog must be CapabilityCatalog")
        entity = self.register_entity(
            WorldEntityRefV1.create(
                entity_type="computer",
                canonical_name="Current Computer",
                aliases=("my computer", "my pc", "this computer", "current pc"),
                provenance_refs=("capability_runtime:local_machine",),
            )
        )
        keys = tuple(
            sorted(
                descriptor.key
                for descriptor in catalog.capabilities
                if descriptor.execution_enabled
            )
        )
        binding = self.register_binding(
            ResourceBindingV1.create(
                entity_id=entity.entity_id,
                provider_id="capability_runtime",
                provider_resource_id="local_machine",
                capability_keys=keys,
                evidence_refs=("capability_runtime:catalog",),
            )
        )
        return entity, binding


class EntityResolver:
    """Resolve stable entity identity without allowing model-only IDs to become truth."""

    def __init__(
        self,
        registry: WorldRegistry,
        *,
        discoveries: tuple[BoundedEntityDiscovery, ...] = (),
    ) -> None:
        if not isinstance(registry, WorldRegistry):
            raise TypeError("registry must be WorldRegistry")
        self._registry = registry
        self._discoveries = tuple(discoveries)
        ids = [item.discovery_id for item in self._discoveries]
        if len(ids) != len(set(ids)):
            raise ValueError("bounded entity discovery ids must be unique")

    def _eligible(
        self,
        *,
        expected_entity_types: tuple[str, ...],
        require_live_binding: bool,
    ) -> tuple[WorldEntityRefV1, ...]:
        expected = {item.casefold() for item in expected_entity_types if item.strip()}
        result = []
        for entity in self._registry.entities():
            if entity.lifecycle_state is not EntityLifecycleState.ACTIVE:
                continue
            if expected and entity.entity_type not in expected:
                continue
            if require_live_binding and not self._registry.bindings(
                entity_id=entity.entity_id
            ):
                continue
            result.append(entity)
        return tuple(result)

    @staticmethod
    def _identity_matches(
        entity: WorldEntityRefV1,
        mention: str,
    ) -> bool:
        needle = _normalize(mention)
        return needle in {
            _normalize(entity.entity_id),
            _normalize(entity.canonical_name),
        }

    @staticmethod
    def _alias_matches(
        entity: WorldEntityRefV1,
        mention: str,
    ) -> bool:
        needle = _normalize(mention)
        return needle in {_normalize(alias) for alias in entity.aliases}

    def _result(
        self,
        candidates: tuple[WorldEntityRefV1, ...],
        *,
        reason: str,
        evidence_prefix: str,
    ) -> EntityResolution:
        if len(candidates) == 1:
            entity = candidates[0]
            return EntityResolution(
                state=EntityResolutionState.RESOLVED,
                entity_id=entity.entity_id,
                evidence_refs=(
                    f"{evidence_prefix}:{entity.entity_id}",
                    *entity.provenance_refs,
                ),
                reason=reason,
            )
        if len(candidates) > 1:
            return EntityResolution(
                state=EntityResolutionState.AMBIGUOUS,
                candidate_entity_ids=tuple(
                    sorted(entity.entity_id for entity in candidates)
                ),
                evidence_refs=(evidence_prefix,),
                reason=reason,
            )
        return EntityResolution(
            state=EntityResolutionState.MISSING,
            reason=reason,
        )

    def resolve(
        self,
        mention: str,
        *,
        expected_entity_types: tuple[str, ...] | list[str] = (),
        recent_entity_ids: tuple[str, ...] | list[str] = (),
        require_live_binding: bool = False,
        allow_discovery: bool = True,
    ) -> EntityResolution:
        query = _normalize(mention)
        if not query:
            raise ValueError("entity mention must not be empty")
        expected = tuple(
            sorted(
                {
                    _normalize(item)
                    for item in expected_entity_types
                    if str(item).strip()
                }
            )
        )
        candidates = self._eligible(
            expected_entity_types=expected,
            require_live_binding=require_live_binding,
        )

        exact = tuple(
            entity for entity in candidates if self._identity_matches(entity, query)
        )
        if exact:
            return self._result(
                exact,
                reason="exact identity/name match",
                evidence_prefix="world_exact",
            )

        recent_ids = tuple(
            item.strip().casefold() for item in recent_entity_ids if str(item).strip()
        )
        recent = tuple(
            entity for entity in candidates if entity.entity_id.casefold() in recent_ids
        )
        if len(recent) == 1:
            return self._result(
                recent,
                reason="unique recent entity referent",
                evidence_prefix="world_recent",
            )

        alias = tuple(
            entity for entity in candidates if self._alias_matches(entity, query)
        )
        if alias:
            return self._result(
                alias,
                reason="unique alias match"
                if len(alias) == 1
                else "ambiguous alias match",
                evidence_prefix="world_alias",
            )

        # Relation traversal is allowed only from an exactly named/aliased anchor.
        all_entities = self._registry.entities()
        anchors = tuple(
            entity
            for entity in all_entities
            if entity.lifecycle_state is EntityLifecycleState.ACTIVE
            and (
                self._identity_matches(entity, query)
                or self._alias_matches(entity, query)
            )
        )
        related_ids = {
            relation_id.casefold()
            for anchor in anchors
            for relation_id in anchor.relation_ids
        }
        related = tuple(
            entity
            for entity in candidates
            if entity.entity_id.casefold() in related_ids
        )
        if related:
            return self._result(
                related,
                reason=(
                    "unique relation match"
                    if len(related) == 1
                    else "ambiguous relation match"
                ),
                evidence_prefix="world_relation",
            )

        inferred_types = set(expected or _generic_reference_types(query))
        if inferred_types:
            typed = tuple(
                entity for entity in candidates if entity.entity_type in inferred_types
            )
            if typed:
                return self._result(
                    typed,
                    reason=(
                        "unique trusted entity by requested type"
                        if len(typed) == 1
                        else "multiple trusted entities match requested type"
                    ),
                    evidence_prefix="world_type",
                )

        if allow_discovery:
            discovered: list[WorldEntityRefV1] = []
            for source in self._discoveries:
                for entity in source.discover(
                    mention=query,
                    expected_entity_types=expected,
                ):
                    if entity.lifecycle_state is not EntityLifecycleState.ACTIVE:
                        continue
                    if expected and entity.entity_type not in expected:
                        continue
                    self._registry.register_entity(entity)
                    discovered.append(entity)
            unique = {entity.entity_id: entity for entity in discovered}
            if unique:
                return self._result(
                    tuple(unique[key] for key in sorted(unique)),
                    reason="bounded read-only discovery",
                    evidence_prefix="world_discovery",
                )

        return EntityResolution(
            state=EntityResolutionState.MISSING,
            reason="no trustworthy entity match",
        )
