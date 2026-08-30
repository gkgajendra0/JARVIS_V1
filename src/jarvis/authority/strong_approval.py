from __future__ import annotations

from dataclasses import dataclass

from .approval import ApprovalError, ApprovalRecord, ApprovalService
from .proposal import ActionProposal
from .types import ApprovalRequirement, ApprovalStatus
from .verifier import (
    StrongVerificationResult,
    StrongVerificationStatus,
    StrongVerifier,
    StrongVerifierError,
)


@dataclass(frozen=True, slots=True)
class StrongApprovalOutcome:
    approval: ApprovalRecord
    verification: StrongVerificationResult

    @property
    def granted(self) -> bool:
        return self.approval.status is ApprovalStatus.GRANTED


class StrongApprovalService:
    """Resolve one exact-action strong approval through a StrongVerifier."""

    def __init__(
        self,
        *,
        approvals: ApprovalService,
        verifier: StrongVerifier,
    ) -> None:
        self._approvals = approvals
        self._verifier = verifier

    def verify_and_resolve(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
        ttl_seconds: float = 60.0,
    ) -> StrongApprovalOutcome:
        approval = self._approvals.request(
            proposal,
            session_id=session_id,
            requirement=ApprovalRequirement.STRONG,
            ttl_seconds=ttl_seconds,
        )
        try:
            verification = self._verifier.verify(
                proposal=proposal,
                session_id=session_id,
            )
        except StrongVerifierError:
            verification = StrongVerificationResult(
                status=StrongVerificationStatus.ERROR,
                verifier_id="strong-verifier-error",
                proposal_fingerprint=proposal.fingerprint,
                session_id=session_id,
                reason_codes=("verifier_error",),
            )

        if verification.verified:
            try:
                approval = self._approvals.grant_verified_strong(
                    approval.approval_id,
                    proposal=proposal,
                    session_id=session_id,
                    verification=verification,
                )
            except ApprovalError:
                approval = self._deny_if_pending(approval.approval_id)
        elif verification.status is StrongVerificationStatus.CANCELED:
            approval = self._cancel_if_pending(approval.approval_id)
        else:
            approval = self._deny_if_pending(approval.approval_id)

        return StrongApprovalOutcome(
            approval=approval,
            verification=verification,
        )

    def _deny_if_pending(self, approval_id: str) -> ApprovalRecord:
        try:
            return self._approvals.deny(approval_id)
        except ApprovalError:
            return self._approvals.get(approval_id)

    def _cancel_if_pending(self, approval_id: str) -> ApprovalRecord:
        try:
            return self._approvals.cancel(approval_id)
        except ApprovalError:
            return self._approvals.get(approval_id)
