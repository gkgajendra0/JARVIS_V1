"""Suggest the next governed network-discovery permission for a waiting goal.

No model-generated device type, vendor/IP guess or ambient approval can trigger
an active scan. This returns an owner-facing canonical ActionProposal only.
AuthorityService and the one-time AEP execution guard own actual permission.
"""

from __future__ import annotations

from jarvis.authority.proposal import ActionProposal

from .aep_authority import build_aep_consent_proposal
from .models import GoalState, InformationNeedCategory, InformationNeedState
from .store import GoalStore
from .windows_lan_scope import WindowsLanScopePlanner
from .world import canonical_world_entity_type

_APPROVED_DISCOVERY_SOURCES = frozenset(
    {"bounded_local_discovery", "current_state_observation"}
)


def prepare_pending_device_discovery_consent(
    *,
    store: GoalStore,
    goal_id: str,
    session_id: str,
    planner: WindowsLanScopePlanner | None = None,
) -> ActionProposal | None:
    """Prepare at most one exact consent request, never perform discovery."""

    if not isinstance(store, GoalStore):
        raise TypeError("discovery consent must use the canonical GoalStore")
    session = session_id.strip()
    goal = store.get_goal(goal_id)
    if (
        not session
        or goal is None
        or goal.source_session_id != session
        or goal.state is not GoalState.WAITING_INFORMATION
    ):
        return None

    scope_planner = planner or WindowsLanScopePlanner()
    for need in store.list_information_needs(goal_id=goal.goal_id):
        if (
            need.state is InformationNeedState.RESOLVED
            or need.category
            in {
                InformationNeedCategory.OWNER_SECRET,
                InformationNeedCategory.OWNER_PREFERENCE,
                InformationNeedCategory.AUTHORIZATION,
                InformationNeedCategory.SUCCESS_CRITERIA,
                InformationNeedCategory.PHYSICAL_OBSERVATION,
            }
            or need.answer_schema.get("type") != "entity_id"
            or not _APPROVED_DISCOVERY_SOURCES.intersection(
                need.allowed_resolution_sources
            )
        ):
            continue
        kind = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        if kind not in {"media_player", "camera"}:
            continue
        scopes = scope_planner.consent_scopes_for(kind)
        if not scopes:
            continue
        # Protocol-specific approvals are sequential, not a blanket permission.
        return build_aep_consent_proposal(
            scope=scopes[0],
            session_id=session,
            goal_id=goal.goal_id,
            need_id=need.information_need_id,
        )
    return None
