"""Bind physical capability requirements to canonical GICC entities before Phase 9.

Physical target identity is a planning prerequisite, NOT proof of network access,
execution authority, authentication or verified physical control.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    EntityLifecycleState,
    WorldEntityRefV1,
)
from .world import (
    canonical_world_entity_type,
    has_independent_target_provenance,
)

# Do not accidentally require device identification for generic capabilities,
# cloud services, notifications or an unscoped software skill.
_PHYSICAL_ENTITY_TYPES = frozenset(
    {"media_player", "camera", "computer", "display", "speaker", "printer"}
)


class PhysicalTargetPreflightError(ValueError):
    """A purported canonical physical target is invalid or contradictory."""


def _target_type(requirement: CapabilityRequirementV1) -> str | None:
    declared = canonical_world_entity_type(requirement.target_entity_type)
    if declared in _PHYSICAL_ENTITY_TYPES:
        return declared
    if declared and declared != "generic_external_resource":
        return None
    prefix = requirement.semantic_capability.split(".", 1)[0]
    return prefix if prefix in _PHYSICAL_ENTITY_TYPES else None


def bind_physical_target_requirements(
    graph: CapabilityRequirementGraphV1,
    *,
    referenced_entity_ids: tuple[str, ...],
    get_entity: Callable[[str], WorldEntityRefV1 | None],
) -> tuple[CapabilityRequirementGraphV1, tuple[str, ...]]:
    """Bind only a *unique* existing canonical entity; otherwise report missing type.

    No model, IP address, alias, vendor, or protocol is generated. The caller must
    resolve missing/ambiguous targets through canonical information needs before
    admitting device-specific acquisition. A resolved entity alone does not prove
    that any requested operation can be executed.
    """

    known = {
        item.entity_id: item
        for entity_id in referenced_entity_ids
        if (item := get_entity(entity_id)) is not None
        and item.lifecycle_state is EntityLifecycleState.ACTIVE
        and has_independent_target_provenance(item.provenance_refs)
    }
    replacements: dict[str, str] = {}
    requirements: list[CapabilityRequirementV1] = []
    missing: set[str] = set()
    changed = False

    for requirement in graph.requirements:
        kind = _target_type(requirement)
        if kind is None:
            requirements.append(requirement)
            continue

        target_id = requirement.target_entity_id
        if target_id is not None:
            entity = known.get(target_id)
            if (
                entity is None
                or canonical_world_entity_type(entity.entity_type) != kind
            ):
                raise PhysicalTargetPreflightError(
                    "physical capability target must be a referenced active "
                    "canonical entity of the requested type"
                )
        else:
            matching = tuple(
                entity
                for entity in known.values()
                if canonical_world_entity_type(entity.entity_type) == kind
            )
            if len(matching) != 1:
                missing.add(kind)
                requirements.append(requirement)
                continue
            target_id = matching[0].entity_id

        if (
            requirement.target_entity_id == target_id
            and requirement.target_entity_type == kind
        ):
            requirements.append(requirement)
            continue

        bound = CapabilityRequirementV1.create(
            goal_id=requirement.goal_id,
            semantic_capability=requirement.semantic_capability,
            operation=requirement.operation,
            target_entity_id=target_id,
            target_entity_type=kind,
            required_parameters_schema=requirement.required_parameters_schema,
            preconditions=requirement.preconditions,
            expected_postconditions=requirement.expected_postconditions,
            observation_requirements=requirement.observation_requirements,
            reason=requirement.reason,
        )
        replacements[requirement.requirement_id] = bound.requirement_id
        requirements.append(bound)
        changed = True

    if not changed:
        return graph, tuple(sorted(missing))

    return (
        CapabilityRequirementGraphV1.create(
            goal_id=graph.goal_id,
            requirements=tuple(requirements),
            information_need_ids=graph.information_need_ids,
            world_state_preconditions=graph.world_state_preconditions,
            completion_predicates=graph.completion_predicates,
            edges=tuple(
                (replacements.get(source, source), replacements.get(target, target))
                for source, target in graph.edges
            ),
        ),
        tuple(sorted(missing)),
    )
