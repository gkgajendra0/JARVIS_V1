"""Bind active Windows AEP discovery to the existing owner approval service.

An approved *action* must cover exactly the WinRT protocol, potential network
broadcast reach, response address filter, timeout and result cap. This helper
does not request/grant approvals and does not create a second authority store.
"""

from __future__ import annotations

from jarvis.authority.approval import ApprovalService
from jarvis.authority.permit import PermitStatus
from jarvis.authority.proposal import ActionProposal, canonical_json
from jarvis.authority.service import AuthorityService
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalRequirement,
    ApprovalStatus,
    InteractionContext,
)

from .windows_aep import ReviewedAepScopeV1


def aep_approval_material(
    scope: ReviewedAepScopeV1,
    *,
    goal_id: str | None = None,
    need_id: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Bind one network discovery to a specific GICC goal when provided."""

    if (goal_id is None) != (need_id is None):
        raise ValueError("goal and information need must be bound together")
    target: dict[str, object] = {
        "resource": "windows_association_endpoint_discovery",
        "protocol": scope.protocol,
        "address_result_filters": list(scope.approved_address_ranges),
        "all_local_interfaces": scope.all_local_interfaces_authorized,
    }
    if goal_id is not None and need_id is not None:
        if (
            not isinstance(goal_id, str)
            or not goal_id.strip()
            or not isinstance(need_id, str)
            or not need_id.strip()
        ):
            raise ValueError("discovery needs concrete goal and information need IDs")
        target["gicc_goal_id"] = goal_id.strip()
        target["gicc_need_id"] = need_id.strip()
    return (
        target,
        {
            "timeout_seconds": scope.timeout_seconds,
            "max_results": scope.max_results,
            "device_control": False,
            "pairing": False,
        },
    )


def _material_for_proposal(
    scope: ReviewedAepScopeV1, proposal: ActionProposal
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Rebuild exact proposal material while preserving goal lineage."""

    values = proposal.target()
    goal_id = values.get("gicc_goal_id")
    need_id = values.get("gicc_need_id")
    if (goal_id is None) != (need_id is None):
        return None
    try:
        return aep_approval_material(scope, goal_id=goal_id, need_id=need_id)
    except (TypeError, ValueError):
        return None


def build_aep_consent_proposal(
    *,
    scope: ReviewedAepScopeV1,
    session_id: str,
    goal_id: str | None = None,
    need_id: str | None = None,
    ttl_seconds: float = 120.0,
) -> ActionProposal:
    """Prepare an exact owner-facing request; never grant or execute it.

    AEP discovery can emit active multicast/broadcast queries over ALL local
    network interfaces. The listed address ranges filter *returned records*,
    not the reach of those packets. That distinction must be visible before
    the owner grants a one-shot, policy-audited execution permit.
    """

    target, parameters = aep_approval_material(scope, goal_id=goal_id, need_id=need_id)
    ranges = ", ".join(scope.approved_address_ranges)
    return ActionProposal.create(
        session_id=session_id,
        capability="network_discovery",
        operation="enumerate_aep",
        target=target,
        parameters=parameters,
        material_summary=(
            f"Allow one {scope.protocol} Windows network-discovery query "
            "across all local network interfaces? "
            f"Keep only device results from {ranges}, "
            f"wait at most {scope.timeout_seconds:g} seconds and retain no "
            f"more than {scope.max_results} results. No control, pairing, "
            "login or configuration changes will be attempted."
        ),
        attributes=ActionAttributes(external_side_effect=True),
        origin=ActionOrigin.PROACTIVE,
        ttl_seconds=ttl_seconds,
    )


class AepExistingApprovalValidator:
    """Check approval readiness only; NOT a full execution authorization.

    A production AEP watcher must instead use AepAuthorityExecutionGuard,
    which revalidates policy, audit and the one-time execution permit.
    """

    def __init__(
        self,
        *,
        approvals: ApprovalService,
        proposal: ActionProposal,
        session_id: str,
    ) -> None:
        if not isinstance(approvals, ApprovalService):
            raise TypeError("AEP approvals must use existing ApprovalService")
        if not isinstance(proposal, ActionProposal):
            raise TypeError("AEP needs the canonical authority ActionProposal")
        if not session_id.strip() or proposal.session_id != session_id.strip():
            raise ValueError("AEP approval must match the active session")
        self._approvals = approvals
        self._proposal = proposal
        self._session_id = session_id.strip()

    def __call__(self, scope: ReviewedAepScopeV1) -> bool:
        if not isinstance(scope, ReviewedAepScopeV1):
            return False
        if (
            self._proposal.capability != "network_discovery"
            or self._proposal.operation != "enumerate_aep"
        ):
            return False
        material = _material_for_proposal(scope, self._proposal)
        if material is None:
            return False
        target, parameters = material
        if self._proposal.target_json != canonical_json(
            target
        ) or self._proposal.parameters_json != canonical_json(parameters):
            return False
        try:
            record = self._approvals.validate(
                scope.consent_record_id,
                proposal=self._proposal,
                session_id=self._session_id,
                minimum_requirement=ApprovalRequirement.EXPLICIT,
            )
            return record.status is ApprovalStatus.GRANTED
        except Exception:  # noqa: BLE001 - never permit on Authority failure
            return False


class AepAuthorityExecutionGuard:
    """One-shot full Authority enforcement immediately before active enumeration.

    It must not issue a new approval, permit or grant. Those are provided by
    the canonical owner approval/action flow, then revalidated and consumed
    with policy/audit immediately before the first network discovery.
    """

    def __init__(
        self,
        *,
        authority: AuthorityService,
        proposal: ActionProposal,
        context: InteractionContext,
        permit_id: str,
        approval_id: str,
    ) -> None:
        if not isinstance(authority, AuthorityService):
            raise TypeError("AEP execution requires the canonical AuthorityService")
        if not isinstance(proposal, ActionProposal):
            raise TypeError("AEP execution requires the canonical ActionProposal")
        if not isinstance(context, InteractionContext):
            raise TypeError("AEP execution requires an InteractionContext")
        if proposal.session_id != context.session_id:
            raise ValueError("AEP execution session does not match proposal")
        if not permit_id.strip() or not approval_id.strip():
            raise ValueError("AEP execution needs existing permit and approval ids")
        self._authority = authority
        self._proposal = proposal
        self._context = context
        self._permit_id = permit_id.strip()
        self._approval_id = approval_id.strip()
        self._consumed = False

    @property
    def consumed(self) -> bool:
        """True only once Authority has consumed this exact one-time permit."""

        return self._consumed

    @property
    def session_id(self) -> str:
        """Expose the exact session bound by the canonical action permit."""

        return self._context.session_id

    def binds_information_need(self, *, goal_id: str, need_id: str) -> bool:
        """Deny redirecting a one-time scan to an unrelated owner goal."""

        target = self._proposal.target()
        return (
            target.get("gicc_goal_id") == goal_id
            and target.get("gicc_need_id") == need_id
        )

    def __call__(self, scope: ReviewedAepScopeV1) -> bool:
        if not isinstance(scope, ReviewedAepScopeV1):
            return False
        if scope.consent_record_id != self._approval_id:
            return False
        if (
            self._proposal.capability != "network_discovery"
            or self._proposal.operation != "enumerate_aep"
        ):
            return False
        material = _material_for_proposal(scope, self._proposal)
        if material is None:
            return False
        target, parameters = material
        if self._proposal.target_json != canonical_json(
            target
        ) or self._proposal.parameters_json != canonical_json(parameters):
            return False
        try:
            permit = self._authority.revalidate_and_consume(
                permit_id=self._permit_id,
                proposal=self._proposal,
                context=self._context,
            )
        except Exception:  # noqa: BLE001 - policy, audit and permit failures deny
            return False
        allowed = (
            permit.status is PermitStatus.CONSUMED
            and permit.approval_id == self._approval_id
        )
        if allowed:
            self._consumed = True
        return allowed
