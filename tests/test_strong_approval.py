from __future__ import annotations

import pytest

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    ApprovalError,
    ApprovalMethod,
    ApprovalRequirement,
    ApprovalService,
    ApprovalStatus,
    AuthorityEffect,
    AuthorityService,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    RiskClassifier,
    StrongApprovalService,
    StrongVerificationResult,
    StrongVerificationStatus,
    TrustTier,
)


class CriticalPolicy:
    version = "step3-v1"

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=PolicyRequirements(
                required_trust=TrustTier.VERIFIED_OWNER,
                approval_requirement=ApprovalRequirement.STRONG,
                audit_required=True,
            ),
            reason_codes=("critical_action",),
            policy_version=self.version,
        )


class BoundVerifier:
    def __init__(self, status: StrongVerificationStatus) -> None:
        self._status = status
        self.calls = 0

    def verify(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult:
        self.calls += 1
        return StrongVerificationResult(
            status=self._status,
            verifier_id="test-verifier",
            verification_id=f"verification-{self.calls}",
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
            reason_codes=(self._status.value,),
        )


class MismatchedVerifier:
    def verify(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult:
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id="mismatched-verifier",
            verification_id="verification-mismatch",
            proposal_fingerprint="wrong-fingerprint",
            session_id=session_id,
            reason_codes=("verified",),
        )


def proposal() -> ActionProposal:
    return ActionProposal.create(
        session_id="session-1",
        capability="finance",
        operation="critical_action",
        target={"account": "local"},
        parameters={"amount": 1},
        material_summary="test critical action",
        attributes=ActionAttributes(financial_or_legal=True),
        origin=ActionOrigin.DIRECT_USER,
    )


def context() -> InteractionContext:
    return InteractionContext(
        session_id="session-1",
        trust_tier=TrustTier.VERIFIED_OWNER,
        windows_session_valid=True,
    )


def authority(approvals: ApprovalService) -> AuthorityService:
    return AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=CriticalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(),
    )


def test_generic_grant_cannot_claim_strong_verifier() -> None:
    approvals = ApprovalService()
    action = proposal()
    record = approvals.request(
        action,
        session_id=action.session_id,
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=60,
    )
    with pytest.raises(ApprovalError, match="bound verification result"):
        approvals.grant(
            record.approval_id,
            proposal=action,
            session_id=action.session_id,
            method=ApprovalMethod.STRONG_VERIFIER,
        )


def test_verified_strong_approval_reaches_and_consumes_r4_authority() -> None:
    approvals = ApprovalService()
    verifier = BoundVerifier(StrongVerificationStatus.VERIFIED)
    strong = StrongApprovalService(approvals=approvals, verifier=verifier)
    action = proposal()

    outcome = strong.verify_and_resolve(
        proposal=action,
        session_id=action.session_id,
    )
    assert outcome.granted
    assert outcome.approval.method is ApprovalMethod.STRONG_VERIFIER

    service = authority(approvals)
    decision = service.evaluate(
        proposal=action,
        context=context(),
        approval_id=outcome.approval.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None

    service.revalidate_and_consume(
        permit_id=decision.execution_permit.permit_id,
        proposal=action,
        context=context(),
    )
    assert approvals.get(outcome.approval.approval_id).status is ApprovalStatus.CONSUMED


def test_canceled_strong_verification_never_grants() -> None:
    approvals = ApprovalService()
    strong = StrongApprovalService(
        approvals=approvals,
        verifier=BoundVerifier(StrongVerificationStatus.CANCELED),
    )
    action = proposal()

    outcome = strong.verify_and_resolve(
        proposal=action,
        session_id=action.session_id,
    )
    assert not outcome.granted
    assert outcome.approval.status is ApprovalStatus.CANCELED

    decision = authority(approvals).evaluate(
        proposal=action,
        context=context(),
        approval_id=outcome.approval.approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY


def test_mismatched_verified_result_is_denied() -> None:
    approvals = ApprovalService()
    strong = StrongApprovalService(
        approvals=approvals,
        verifier=MismatchedVerifier(),
    )
    action = proposal()

    outcome = strong.verify_and_resolve(
        proposal=action,
        session_id=action.session_id,
    )
    assert not outcome.granted
    assert outcome.approval.status is ApprovalStatus.DENIED


def test_strong_verification_proof_cannot_be_reused() -> None:
    approvals = ApprovalService()
    action = proposal()
    verification = StrongVerificationResult(
        status=StrongVerificationStatus.VERIFIED,
        verifier_id="test-verifier",
        verification_id="one-time-proof",
        proposal_fingerprint=action.fingerprint,
        session_id=action.session_id,
        reason_codes=("verified",),
    )

    first = approvals.request(
        action,
        session_id=action.session_id,
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=60,
    )
    approvals.grant_verified_strong(
        first.approval_id,
        proposal=action,
        session_id=action.session_id,
        verification=verification,
    )

    second = approvals.request(
        action,
        session_id=action.session_id,
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=60,
    )
    with pytest.raises(ApprovalError, match="already consumed"):
        approvals.grant_verified_strong(
            second.approval_id,
            proposal=action,
            session_id=action.session_id,
            verification=verification,
        )
