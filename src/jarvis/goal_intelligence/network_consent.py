"""Suggest the next governed network-discovery permission for a waiting goal.

No model-generated device type, vendor/IP guess or ambient approval can trigger
an active scan. This returns an owner-facing canonical ActionProposal only.
AuthorityService and the one-time AEP execution guard own actual permission.
"""

from __future__ import annotations

from jarvis.authority.proposal import ActionProposal

from .aep_authority import build_aep_consent_proposal
from .information import can_rediscover_information
from .models import GoalState
from .store import GoalStore
from .vidaa_udp import ReviewedVidaaScopeV1, build_vidaa_consent_proposal
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
    resume_existing_goal: bool = False,
) -> ActionProposal | None:
    """Prepare a read-only scope bound to the active owner conversation.

    A resumed goal keeps its immutable source-session provenance. Only a trusted
    caller with independently verified current goal selection may opt in to
    proposing a fresh *current-session* approval. This never authorizes a scan.
    """

    if not isinstance(store, GoalStore):
        raise TypeError("discovery consent must use the canonical GoalStore")
    session = session_id.strip()
    goal = store.get_goal(goal_id)
    if (
        not session
        or goal is None
        or (goal.source_session_id != session and not resume_existing_goal)
        or goal.state is not GoalState.WAITING_INFORMATION
    ):
        return None

    scope_planner = planner or WindowsLanScopePlanner()
    for need in store.list_information_needs(goal_id=goal.goal_id):
        if (
            not can_rediscover_information(need)
            or need.answer_schema.get("type") != "entity_id"
            or not _APPROVED_DISCOVERY_SOURCES.issubset(need.allowed_resolution_sources)
        ):
            continue
        kind = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        if kind not in {"media_player", "camera"}:
            continue
        scopes = scope_planner.consent_scopes_for(kind)
        if not scopes:
            continue
        # Protocol-specific approvals are sequential, not a blanket permission.
        # A consumed, exact Authority permit is recorded on this same
        # InformationNeed; never repeatedly propose the first protocol.
        for scope in scopes:
            marker = f"windows_aep_authorized_scope_consumed:{scope.protocol}"
            if marker in need.evidence_refs:
                continue
            return build_aep_consent_proposal(
                scope=scope,
                session_id=session,
                goal_id=goal.goal_id,
                need_id=need.information_need_id,
            )

        # An exhausted media-player AEP attempt is NOT authority to broadcast.
        # Offer a separately scoped, fresh Windows Hello-protected VIDAA
        # directed broadcast only after both prior methods were consumed.
        if kind == "media_player" and {
            "windows_aep_authorized_scope_consumed:upnp",
            "windows_aep_authorized_scope_consumed:dns_sd",
        }.issubset(need.evidence_refs):
            networks = scope_planner.inspect()
            if networks:
                selected = networks[0]
                marker = (
                    "windows_vidaa_authorized_scope_consumed:vidaa_udp:" + selected.cidr
                )
                if marker not in need.evidence_refs:
                    try:
                        reviewed_vidaa = ReviewedVidaaScopeV1(
                            cidr=selected.cidr,
                            interface_index=selected.interface_index,
                        )
                    except (ValueError, TypeError):
                        continue
                    return build_vidaa_consent_proposal(
                        scope=reviewed_vidaa,
                        session_id=session,
                        goal_id=goal.goal_id,
                        need_id=need.information_need_id,
                    )
    return None
