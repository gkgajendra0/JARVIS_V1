from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    ApprovalMethod,
    ApprovalRequirement,
    ApprovalService,
    ApprovalStatus,
    AttentionState,
    AuthorityEffect,
    AuthorityError,
    AuthorityService,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    PermitStatus,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    ProposalValidationError,
    RiskClass,
    RiskClassifier,
    TrustTier,
)
from jarvis.authority.types import AuthorityEffect as Effect


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class LocalPolicy:
    version = "step3-v1"

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        risk = policy_input.risk_class
        origin = policy_input.proposal.origin
        if risk is RiskClass.ROUTINE:
            req = PolicyRequirements(
                TrustTier.UNVERIFIED,
                ApprovalRequirement.NONE,
                audit_required=False,
            )
        elif risk is RiskClass.PRIVATE_READ:
            if origin is ActionOrigin.DIRECT_USER:
                req = PolicyRequirements(
                    TrustTier.CORROBORATED_OWNER,
                    ApprovalRequirement.DIRECT_INTENT,
                )
            else:
                req = PolicyRequirements(
                    TrustTier.CORROBORATED_OWNER,
                    ApprovalRequirement.EXPLICIT,
                    require_owner_attentive=True,
                    require_actor_unambiguous=True,
                )
        elif risk is RiskClass.REVERSIBLE_LOCAL_CHANGE:
            req = PolicyRequirements(
                TrustTier.CORROBORATED_OWNER,
                (
                    ApprovalRequirement.DIRECT_INTENT
                    if origin is ActionOrigin.DIRECT_USER
                    else ApprovalRequirement.EXPLICIT
                ),
            )
        elif risk is RiskClass.PERSISTENT_OR_EXTERNAL:
            req = PolicyRequirements(
                TrustTier.CORROBORATED_OWNER,
                ApprovalRequirement.EXPLICIT,
            )
        elif risk is RiskClass.CRITICAL:
            req = PolicyRequirements(
                TrustTier.VERIFIED_OWNER,
                ApprovalRequirement.STRONG,
            )
        else:
            return PolicyDecision.deny(
                "restricted_dev_only",
                policy_version=self.version,
            )
        return PolicyDecision(
            effect=Effect.ALLOW,
            requirements=req,
            reason_codes=(),
            policy_version=self.version,
        )


class FailingAudit:
    def append(self, event: object) -> None:
        from jarvis.authority import AuditError

        raise AuditError("disk full")


def proposal(
    clock: FakeClock,
    *,
    session_id: str = "session-1",
    attributes: ActionAttributes | None = None,
    origin: ActionOrigin = ActionOrigin.DIRECT_USER,
    target: object | None = None,
    parameters: object | None = None,
) -> ActionProposal:
    return ActionProposal.create(
        session_id=session_id,
        capability="test",
        operation="do",
        target={} if target is None else target,
        parameters={} if parameters is None else parameters,
        material_summary="test action",
        attributes=attributes or ActionAttributes(),
        origin=origin,
        ttl_seconds=120,
        now_monotonic=clock(),
        proposal_id="proposal-1",
        nonce="nonce-1",
    )


def context(
    *,
    session_id: str = "session-1",
    trust: TrustTier = TrustTier.CORROBORATED_OWNER,
    attention: AttentionState = AttentionState.ATTENTIVE,
    actor_unambiguous: bool = True,
    windows_valid: bool = True,
) -> InteractionContext:
    return InteractionContext(
        session_id=session_id,
        trust_tier=trust,
        attention_state=attention,
        actor_unambiguous=actor_unambiguous,
        windows_session_valid=windows_valid,
    )


def service(
    clock: FakeClock,
    *,
    audit: object | None = None,
    policy: object | None = None,
) -> tuple[AuthorityService, ApprovalService, PermitRegistry]:
    approvals = ApprovalService(clock=clock)
    permits = PermitRegistry(clock=clock, ttl_seconds=5)
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=policy or LocalPolicy(),
        approvals=approvals,
        audit_store=audit or InMemoryAuditEventStore(),
        permits=permits,
        clock=clock,
    )
    return authority, approvals, permits


def grant(
    approvals: ApprovalService,
    p: ActionProposal,
    *,
    requirement: ApprovalRequirement,
    method: ApprovalMethod,
    ttl: float = 30,
) -> str:
    record = approvals.request(
        p,
        session_id=p.session_id,
        requirement=requirement,
        ttl_seconds=ttl,
    )
    return approvals.grant(
        record.approval_id,
        proposal=p,
        session_id=p.session_id,
        method=method,
    ).approval_id


def test_canonical_hash_is_order_independent() -> None:
    clock = FakeClock()
    first = proposal(
        clock,
        target={"b": 2, "a": 1},
        parameters={"x": [3, 2, 1]},
    )
    second = ActionProposal.create(
        session_id="session-1",
        capability="test",
        operation="do",
        target={"a": 1, "b": 2},
        parameters={"x": [3, 2, 1]},
        material_summary="different wording does not alter material hash",
        attributes=ActionAttributes(),
        origin=ActionOrigin.DIRECT_USER,
        ttl_seconds=120,
        now_monotonic=clock(),
        proposal_id="other-id",
        nonce="nonce-1",
    )
    assert first.fingerprint == second.fingerprint


def test_material_parameter_change_changes_hash() -> None:
    clock = FakeClock()
    first = proposal(clock, parameters={"recipient": "a@example.com"})
    second = proposal(clock, parameters={"recipient": "b@example.com"})
    assert first.fingerprint != second.fingerprint


def test_unicode_normalized_key_collision_rejected() -> None:
    clock = FakeClock()
    with pytest.raises(ProposalValidationError):
        proposal(
            clock,
            parameters={
                "\u00e9": 1,
                "e\u0301": 2,
            },
        )


def test_proposal_is_session_bound_and_expires() -> None:
    clock = FakeClock()
    p = proposal(clock)
    assert not p.is_expired(clock())
    clock.advance(120)
    assert p.is_expired(clock())


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (ActionAttributes(), RiskClass.ROUTINE),
        (
            ActionAttributes(private_read=True),
            RiskClass.PRIVATE_READ,
        ),
        (
            ActionAttributes(reversible_local_change=True),
            RiskClass.REVERSIBLE_LOCAL_CHANGE,
        ),
        (
            ActionAttributes(persistent_write=True),
            RiskClass.PERSISTENT_OR_EXTERNAL,
        ),
        (
            ActionAttributes(destructive=True),
            RiskClass.CRITICAL,
        ),
        (
            ActionAttributes(authority_policy_change=True),
            RiskClass.RESTRICTED_DEV_ONLY,
        ),
    ],
)
def test_risk_hard_floors(
    attributes: ActionAttributes,
    expected: RiskClass,
) -> None:
    assert RiskClassifier().classify(attributes).risk_class is expected


def test_lower_risk_flags_cannot_downgrade_critical() -> None:
    attributes = ActionAttributes(
        private_read=True,
        persistent_write=True,
        financial_or_legal=True,
    )
    assert (
        RiskClassifier().classify(attributes).risk_class
        is RiskClass.CRITICAL
    )


def test_direct_intent_requires_direct_user_origin() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(private_read=True),
        origin=ActionOrigin.MODEL_SUGGESTED,
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.DIRECT_INTENT,
        method=ApprovalMethod.DIRECT_INTENT,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert "approval_too_weak" in decision.reason_codes


def test_private_direct_read_needs_t2_and_direct_intent() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(private_read=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.DIRECT_INTENT,
        method=ApprovalMethod.DIRECT_INTENT,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW


def test_insufficient_trust_denies_private_read() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(private_read=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.DIRECT_INTENT,
        method=ApprovalMethod.DIRECT_INTENT,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(trust=TrustTier.PRESENT_CONTEXT),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("insufficient_trust",)


def test_spoken_r3_requires_fresh_attention() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(attention=AttentionState.NOT_ATTENTIVE),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == (
        "spoken_approval_requires_attention",
    )


def test_spoken_r3_requires_unambiguous_actor() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(actor_unambiguous=False),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == (
        "spoken_approval_requires_actor_binding",
    )


def test_r3_spoken_approval_allows_when_attention_bound() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW


def test_r4_rejects_spoken_and_requires_strong() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(financial_or_legal=True),
    )
    record = approvals.request(
        p,
        session_id=p.session_id,
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=30,
    )
    with pytest.raises(Exception):
        approvals.grant(
            record.approval_id,
            proposal=p,
            session_id=p.session_id,
            method=ApprovalMethod.SPOKEN,
        )
    decision = authority.evaluate(
        proposal=p,
        context=context(trust=TrustTier.VERIFIED_OWNER),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("approval_required",)


def test_r4_strong_verification_does_not_require_empty_room() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(financial_or_legal=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.STRONG,
        method=ApprovalMethod.STRONG_VERIFIER,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(
            trust=TrustTier.VERIFIED_OWNER,
            actor_unambiguous=False,
            attention=AttentionState.AMBIGUOUS,
        ),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW


def test_r5_is_unavailable_to_normal_runtime() -> None:
    clock = FakeClock()
    authority, _, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(authority_policy_change=True),
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(trust=TrustTier.VERIFIED_OWNER),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("restricted_dev_only",)


def test_windows_session_invalid_denies() -> None:
    clock = FakeClock()
    authority, _, _ = service(clock)
    p = proposal(clock)
    decision = authority.evaluate(
        proposal=p,
        context=context(windows_valid=False),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("windows_session_invalid",)


def test_approval_expiry_fails_closed() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
        ttl=2,
    )
    clock.advance(3)
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("approval_invalid",)


def test_session_invalidation_cancels_approval_and_permit() -> None:
    clock = FakeClock()
    authority, approvals, permits = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.execution_permit is not None
    authority.invalidate_session("session-1")
    assert approvals.get(approval_id).status is ApprovalStatus.CANCELED
    with permits.lock:
        permit = permits.get_locked(decision.execution_permit.permit_id)
    assert permit.status is PermitStatus.INVALIDATED


def test_final_revalidation_consumes_approval_and_permit_once() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.execution_permit is not None
    consumed = authority.revalidate_and_consume(
        permit_id=decision.execution_permit.permit_id,
        proposal=p,
        context=context(),
    )
    assert consumed.status is PermitStatus.CONSUMED
    assert approvals.get(approval_id).status is ApprovalStatus.CONSUMED
    with pytest.raises(AuthorityError):
        authority.revalidate_and_consume(
            permit_id=consumed.permit_id,
            proposal=p,
            context=context(),
        )


def test_parameter_mutation_invalidates_execution() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock)
    p = proposal(
        clock,
        attributes=ActionAttributes(external_side_effect=True),
        parameters={"recipient": "a@example.com"},
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.EXPLICIT,
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.execution_permit is not None
    mutated = replace(
        p,
        parameters_json='{"recipient":"b@example.com"}',
    )
    with pytest.raises(
        AuthorityError,
        match="proposal_integrity_invalid",
    ):
        authority.revalidate_and_consume(
            permit_id=decision.execution_permit.permit_id,
            proposal=mutated,
            context=context(),
        )


def test_permit_expiry_denies_replay() -> None:
    clock = FakeClock()
    authority, _, _ = service(clock)
    p = proposal(clock)
    decision = authority.evaluate(
        proposal=p,
        context=context(trust=TrustTier.UNVERIFIED),
    )
    assert decision.execution_permit is not None
    clock.advance(6)
    with pytest.raises(AuthorityError, match="execution permit is expired"):
        authority.revalidate_and_consume(
            permit_id=decision.execution_permit.permit_id,
            proposal=p,
            context=context(trust=TrustTier.UNVERIFIED),
        )


def test_required_audit_failure_blocks_protected_action() -> None:
    clock = FakeClock()
    authority, approvals, _ = service(clock, audit=FailingAudit())
    p = proposal(
        clock,
        attributes=ActionAttributes(private_read=True),
    )
    approval_id = grant(
        approvals,
        p,
        requirement=ApprovalRequirement.DIRECT_INTENT,
        method=ApprovalMethod.DIRECT_INTENT,
    )
    decision = authority.evaluate(
        proposal=p,
        context=context(),
        approval_id=approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("audit_unavailable",)


def test_session_mismatch_denies() -> None:
    clock = FakeClock()
    authority, _, _ = service(clock)
    p = proposal(clock)
    decision = authority.evaluate(
        proposal=p,
        context=context(session_id="different"),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("proposal_session_mismatch",)
