"""Bind active Windows AEP discovery to the existing owner approval service.

An approved *action* must cover exactly the WinRT protocol, potential network
broadcast reach, response address filter, timeout and result cap. This helper
does not request/grant approvals and does not create a second authority store.
"""

from __future__ import annotations

from jarvis.authority.approval import ApprovalService
from jarvis.authority.proposal import ActionProposal, canonical_json
from jarvis.authority.types import ApprovalRequirement, ApprovalStatus

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


class AepExistingApprovalValidator:
    """Only an existing, granted and proposal-bound approval enables AEP."""

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
        if (
            self._proposal.target_json != canonical_json(target)
            or self._proposal.parameters_json != canonical_json(parameters)
        ):
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
