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
) -> tuple[dict[str, object], dict[str, object]]:
    """Exact target and parameters for the canonical Authority proposal."""

    return (
        {
            "resource": "windows_association_endpoint_discovery",
            "protocol": scope.protocol,
            "address_result_filters": list(scope.approved_address_ranges),
            "all_local_interfaces": scope.all_local_interfaces_authorized,
        },
        {
            "timeout_seconds": scope.timeout_seconds,
            "max_results": scope.max_results,
            "device_control": False,
            "pairing": False,
        },
    )


def build_aep_consent_proposal(
    *,
    scope: ReviewedAepScopeV1,
    session_id: str,
    ttl_seconds: float = 120.0,
) -> ActionProposal:
    """Prepare an exact owner-facing request; never grant or execute it.

    AEP discovery can emit active multicast/broadcast queries over ALL local
    network interfaces. The listed address ranges filter *returned records*,
    not the reach of those packets. That distinction must be visible before
    the owner grants a one-shot, policy-audited execution permit.
    """

    target, parameters = aep_approval_material(scope)
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
        target, parameters = aep_approval_material(scope)
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
        target, parameters = aep_approval_material(scope)
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
        return (
            permit.status is PermitStatus.CONSUMED
            and permit.approval_id == self._approval_id
        )
