"""Owner confirmation of one discovered device, distinct from protocol access.

AEP advertisements are untrusted. Only a fresh, explicit owner confirmation
for one unambiguous candidate may establish a canonical *owner inventory*
identity; it does not verify an endpoint, a transport, pairing, or execution.
"""

from __future__ import annotations

from .device_suggestions import pending_owner_device_suggestions
from .information import can_rediscover_information
from .models import (
    EntityLifecycleState,
    GoalState,
    InformationNeedCategory,
    WorldEntityRefV1,
)
from .store import GoalStore
from .world import WorldRegistry, canonical_world_entity_type

_CONFIRMABLE_TYPES = {
    "media_player": ("Owner-confirmed TV", ("my tv", "my television")),
    "camera": ("Owner-confirmed camera", ("my camera",)),
}


def confirm_single_discovered_device(
    *,
    store: GoalStore,
    world: WorldRegistry,
    goal_id: str,
    information_need_id: str,
    session_id: str,
    owner_turn_id: str,
) -> WorldEntityRefV1 | None:
    """Bind one *fresh* owner-reaffirmed physical identity to the original goal.

    Caller must independently verify the canonical USER turn actually expresses
    explicit identification of the returned device, not a generic yes.
    """
    if not isinstance(store, GoalStore) or not isinstance(world, WorldRegistry):
        raise TypeError("owner confirmation requires the canonical GICC stores")
    if world.store is not store:
        raise ValueError("device confirmation must use the same WorldRegistry store")
    turn_id = str(owner_turn_id).strip()
    if not turn_id or len(turn_id) > 128:
        return None
    goal = store.get_goal(str(goal_id).strip())
    if (
        goal is None
        or goal.state is not GoalState.WAITING_INFORMATION
        or goal.source_session_id != str(session_id).strip()
    ):
        return None
    need = store.get_information_need(str(information_need_id).strip())
    if (
        need is None
        or need.goal_id != goal.goal_id
        or not can_rediscover_information(need)
        or need.category not in {
            InformationNeedCategory.MISSING_VALUE,
            InformationNeedCategory.AMBIGUOUS_REFERENCE,
            InformationNeedCategory.DISAMBIGUATION,
        }
        or need.answer_schema.get("type") != "entity_id"
        or "owner_input" not in need.allowed_resolution_sources
    ):
        return None
    kind = canonical_world_entity_type(need.answer_schema.get("entity_type"))
    details = _CONFIRMABLE_TYPES.get(kind)
    if details is None:
        return None
    hints = pending_owner_device_suggestions(
        store=store, goal_id=goal.goal_id, session_id=goal.source_session_id
    )
    # Never silently choose between conflicting or multiple network devices.
    if len(hints) != 1 or hints[0].evidence_ref not in need.evidence_refs:
        return None
    canonical_name, aliases = details
    # Existing canonical owner inventory should use the already bound
    # entity-disambiguation path rather than create a second "my TV".
    entity_id = f"owner_confirmed_network:{need.information_need_id}"
    for entity in world.entities():
        if entity.entity_id == entity_id:
            continue
        if (
            entity.lifecycle_state is EntityLifecycleState.ACTIVE
            and canonical_world_entity_type(entity.entity_type) == kind
            and any(alias in entity.aliases for alias in aliases)
        ):
            return None
    entry = WorldEntityRefV1.create(
        entity_type=kind,
        canonical_name=canonical_name,
        aliases=aliases,
        entity_id=entity_id,
        provenance_refs=(
            f"owner_inventory:explicit_device_confirmation:{goal.goal_id}:{turn_id}",
            f"unverified_aep_evidence:{hints[0].evidence_ref}",
        ),
    )
    return world.register_entity(entry)
