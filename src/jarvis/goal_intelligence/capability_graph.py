"""Resolve semantic GICC requirements against canonical capability truth."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capabilities.models import CapabilityDescriptor
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import CapabilityManagementMode

from .models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
)
from .monitoring import GICC_MONITOR_EVENT_CONTRACT
from .store import GoalStore


@dataclass(frozen=True, slots=True)
class CapabilityRequirementMatch:
    requirement_id: str
    capability_key: str
    operation: str


@dataclass(frozen=True, slots=True)
class CapabilityGapAnalysis:
    goal_id: str
    graph_id: str
    satisfied_requirement_ids: tuple[str, ...]
    matches: tuple[CapabilityRequirementMatch, ...]
    gaps: tuple[CapabilityGapV1, ...]

    @property
    def satisfied(self) -> bool:
        return not self.gaps


def _normalized_operations(descriptor: CapabilityDescriptor) -> set[str]:
    return {
        str(operation).strip().casefold()
        for operation in descriptor.operations
        if str(operation).strip()
    }


class CapabilityGraphResolver:
    """Read current capability/Phase-8 truth and emit only genuine reusable gaps."""

    def __init__(self, *, store: GoalStore | None = None) -> None:
        if store is not None and not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore or None")
        self._store = store

    @staticmethod
    def _effectively_enabled(
        descriptor: CapabilityDescriptor,
        context: AcquisitionContextV1,
    ) -> bool:
        if not descriptor.execution_enabled:
            return False
        inventory = context.inventory_entry(descriptor.key)
        if inventory is None:
            return False
        if inventory.management_mode is CapabilityManagementMode.CORE_PINNED:
            return True
        snapshot = context.effective_snapshot
        if snapshot is None:
            return False
        state = snapshot.state_for_key(descriptor.key)
        return bool(
            state is not None
            and state.effective_enabled
            and not state.transition_fenced
            and state.applied_generation == state.registry_generation
        )

    @staticmethod
    def _family_target_compatible(
        requirement: CapabilityRequirementV1,
        descriptor: CapabilityDescriptor,
        context: AcquisitionContextV1,
    ) -> bool:
        semantic = descriptor.semantic_metadata()
        inventory = context.inventory_entry(descriptor.key)
        if inventory is None:
            return False

        if inventory.management_mode is CapabilityManagementMode.PACKAGE_MANAGED:
            if semantic.semantic_capability_family != requirement.semantic_capability:
                return False
            return not (
                requirement.target_entity_type
                and (
                    not semantic.target_entity_types
                    or requirement.target_entity_type
                    not in semantic.target_entity_types
                )
            )

        if (
            semantic.semantic_capability_family is not None
            and semantic.semantic_capability_family != requirement.semantic_capability
        ):
            return False
        return not (
            requirement.target_entity_type
            and semantic.target_entity_types
            and requirement.target_entity_type not in semantic.target_entity_types
        )

    @staticmethod
    def _monitor_event_compatible(
        requirement: CapabilityRequirementV1,
        descriptor: CapabilityDescriptor,
        *,
        monitoring_goal: bool,
    ) -> bool:
        if not monitoring_goal:
            return True
        family = requirement.semantic_capability
        observation_family = (
            ".observe" in family
            or ".perceive" in family
            or family.startswith(("vision.", "camera."))
        )
        if not observation_family:
            return True
        semantic = descriptor.semantic_metadata()
        metadata = descriptor.metadata()
        return bool(
            requirement.operation in semantic.observation_operations
            and metadata.get("monitor_event_contract") == GICC_MONITOR_EVENT_CONTRACT
        )

    @classmethod
    def _matches(
        cls,
        requirement: CapabilityRequirementV1,
        descriptor: CapabilityDescriptor,
        context: AcquisitionContextV1,
        *,
        monitoring_goal: bool,
    ) -> bool:
        if not cls._effectively_enabled(descriptor, context):
            return False
        if not cls._family_target_compatible(requirement, descriptor, context):
            return False
        if not cls._monitor_event_compatible(
            requirement,
            descriptor,
            monitoring_goal=monitoring_goal,
        ):
            return False
        return requirement.operation in _normalized_operations(descriptor)

    @classmethod
    def _partial_keys(
        cls,
        requirements: tuple[CapabilityRequirementV1, ...],
        context: AcquisitionContextV1,
    ) -> tuple[str, ...]:
        keys = {
            descriptor.key
            for descriptor in context.catalog.capabilities
            if cls._effectively_enabled(descriptor, context)
            and any(
                cls._family_target_compatible(requirement, descriptor, context)
                for requirement in requirements
            )
        }
        return tuple(sorted(keys))

    def _persist_gap(self, gap: CapabilityGapV1) -> CapabilityGapV1:
        if self._store is None:
            return gap
        existing = self._store.get_gap(gap.gap_id)
        if existing is None:
            return self._store.put_gap(gap)
        if existing.state is CapabilityGapState.OPEN:
            return existing
        return self._store.update_gap_state(
            existing.gap_id,
            CapabilityGapState.OPEN,
            expected_revision=existing.revision,
        )

    def analyze(
        self,
        graph: CapabilityRequirementGraphV1,
        context: AcquisitionContextV1,
        *,
        persist_gaps: bool = False,
        monitoring_goal: bool = False,
    ) -> CapabilityGapAnalysis:
        if not isinstance(graph, CapabilityRequirementGraphV1):
            raise TypeError("graph must be CapabilityRequirementGraphV1")
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")
        if persist_gaps and self._store is None:
            raise ValueError("persist_gaps requires a GoalStore")

        matches: list[CapabilityRequirementMatch] = []
        missing: list[CapabilityRequirementV1] = []
        for requirement in graph.requirements:
            candidates = tuple(
                descriptor
                for descriptor in context.catalog.capabilities
                if self._matches(
                    requirement,
                    descriptor,
                    context,
                    monitoring_goal=monitoring_goal,
                )
            )
            if candidates:
                selected = min(candidates, key=lambda item: item.key)
                matches.append(
                    CapabilityRequirementMatch(
                        requirement_id=requirement.requirement_id,
                        capability_key=selected.key,
                        operation=requirement.operation,
                    )
                )
            else:
                missing.append(requirement)

        grouped: dict[
            tuple[str, str, str | None],
            list[CapabilityRequirementV1],
        ] = {}
        for requirement in missing:
            key = (
                requirement.semantic_capability,
                requirement.target_entity_type or "generic_external_resource",
                requirement.target_entity_id,
            )
            grouped.setdefault(key, []).append(requirement)

        gaps: list[CapabilityGapV1] = []
        for (
            family,
            target_type,
            target_id,
        ), requirements in sorted(grouped.items(), key=lambda item: str(item[0])):
            requirement_values = tuple(
                sorted(requirements, key=lambda item: item.requirement_id)
            )
            gap = CapabilityGapV1.create(
                goal_id=graph.goal_id,
                requirement_ids=tuple(
                    item.requirement_id for item in requirement_values
                ),
                reusable_capability_family=family,
                target_entity_type=target_type,
                target_entity_id=target_id,
                minimum_required_operations=tuple(
                    sorted({item.operation for item in requirement_values})
                ),
                matching_capability_keys=self._partial_keys(
                    requirement_values,
                    context,
                ),
                missing_reason_codes=("no_effective_capability_match",),
                motivating_goal_id=graph.goal_id,
            )
            gaps.append(self._persist_gap(gap) if persist_gaps else gap)

        return CapabilityGapAnalysis(
            goal_id=graph.goal_id,
            graph_id=graph.graph_id,
            satisfied_requirement_ids=tuple(
                sorted(match.requirement_id for match in matches)
            ),
            matches=tuple(
                sorted(
                    matches,
                    key=lambda item: (
                        item.requirement_id,
                        item.capability_key,
                    ),
                )
            ),
            gaps=tuple(sorted(gaps, key=lambda item: item.gap_id)),
        )
