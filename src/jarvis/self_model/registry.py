"""Canonical static Self Model registry with deterministic health overlays."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from jarvis.self_model.health import (
    HealthRegistry,
    HealthSnapshot,
    roll_up_dependency_health,
)
from jarvis.self_model.models import ComponentDescriptor, DependencyDescriptor


@dataclass(frozen=True, slots=True)
class ComponentSnapshot:
    descriptor: ComponentDescriptor
    health: HealthSnapshot
    dependencies: tuple[DependencyDescriptor, ...]


class SelfModelRegistry:
    def __init__(
        self,
        *,
        components: tuple[ComponentDescriptor, ...] = (),
        dependencies: tuple[DependencyDescriptor, ...] = (),
    ) -> None:
        self._components = {item.component_id: item for item in components}
        if len(self._components) != len(components):
            raise ValueError("component ids must be unique")
        self._dependencies = dependencies
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        seen: set[tuple[str, str, str]] = set()
        for dependency in self._dependencies:
            if dependency.source_component_id not in self._components:
                raise ValueError(
                    "dependency source component is not registered: "
                    f"{dependency.source_component_id}"
                )
            if dependency.target_component_id not in self._components:
                raise ValueError(
                    "dependency target component is not registered: "
                    f"{dependency.target_component_id}"
                )
            if (
                dependency.fallback_component_id is not None
                and dependency.fallback_component_id not in self._components
            ):
                raise ValueError(
                    "dependency fallback component is not registered: "
                    f"{dependency.fallback_component_id}"
                )
            key = (
                dependency.source_component_id,
                dependency.target_component_id,
                dependency.relation,
            )
            if key in seen:
                raise ValueError(f"duplicate dependency: {key}")
            seen.add(key)

    @property
    def components(self) -> tuple[ComponentDescriptor, ...]:
        return tuple(
            sorted(self._components.values(), key=lambda item: item.component_id)
        )

    @property
    def dependencies(self) -> tuple[DependencyDescriptor, ...]:
        return tuple(
            sorted(
                self._dependencies,
                key=lambda item: (
                    item.source_component_id,
                    item.target_component_id,
                    item.relation,
                ),
            )
        )

    def component(self, component_id: str) -> ComponentDescriptor | None:
        return self._components.get(str(component_id).strip().lower())

    def dependencies_for(self, component_id: str) -> tuple[DependencyDescriptor, ...]:
        normalized = str(component_id).strip().lower()
        return tuple(
            item for item in self.dependencies if item.source_component_id == normalized
        )

    def dependents_of(self, component_id: str) -> tuple[DependencyDescriptor, ...]:
        normalized = str(component_id).strip().lower()
        return tuple(
            item for item in self.dependencies if item.target_component_id == normalized
        )

    def affected_components(self, component_id: str) -> tuple[str, ...]:
        normalized = str(component_id).strip().lower()
        if normalized not in self._components:
            return ()
        affected: set[str] = set()
        queue = deque([normalized])
        while queue:
            target = queue.popleft()
            for dependency in self.dependents_of(target):
                source = dependency.source_component_id
                if source in affected:
                    continue
                affected.add(source)
                queue.append(source)
        return tuple(sorted(affected))

    def snapshot(
        self,
        component_id: str,
        health: HealthRegistry,
        *,
        now_epoch: float | None = None,
    ) -> ComponentSnapshot:
        normalized = str(component_id).strip().lower()
        descriptor = self.component(normalized)
        if descriptor is None:
            raise KeyError(f"unknown component: {component_id}")
        base = health.snapshot(normalized, now_epoch=now_epoch)
        dependencies = self.dependencies_for(normalized)
        dependency_snapshots = tuple(
            (
                item.target_component_id,
                item.criticality,
                health.snapshot(item.target_component_id, now_epoch=now_epoch),
            )
            for item in dependencies
        )
        return ComponentSnapshot(
            descriptor=descriptor,
            health=roll_up_dependency_health(base, dependency_snapshots),
            dependencies=dependencies,
        )

    def system_snapshot(
        self,
        health: HealthRegistry,
        *,
        now_epoch: float | None = None,
    ) -> tuple[ComponentSnapshot, ...]:
        return tuple(
            self.snapshot(item.component_id, health, now_epoch=now_epoch)
            for item in self.components
        )
