from __future__ import annotations

import sqlite3

import pytest

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    ApprovalError,
    ApprovalMethod,
    ApprovalRequirement,
    ApprovalService,
    AttentionState,
    AuditError,
    AuditEvent,
    AuthorityEffect,
    AuthorityService,
    AuthoritySessionManager,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    RiskClassifier,
    SessionSecurityEvent,
    SqliteAuditEventStore,
    TrustTier,
)


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class WeakCriticalPolicy:
    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=PolicyRequirements(
                required_trust=TrustTier.UNVERIFIED,
                approval_requirement=ApprovalRequirement.NONE,
                audit_required=False,
            ),
            reason_codes=(),
            policy_version="step3-v1",
        )


def critical_proposal(clock: FakeClock) -> ActionProposal:
    return ActionProposal.create(
        session_id="s1",
        capability="finance",
        operation="transfer",
        target={"account": "redacted"},
        parameters={"amount": 10},
        material_summary="transfer funds",
        attributes=ActionAttributes(financial_or_legal=True),
        origin=ActionOrigin.DIRECT_USER,
        now_monotonic=clock(),
    )


def test_policy_cannot_lower_critical_hard_floor() -> None:
    clock = FakeClock()
    approvals = ApprovalService(clock=clock)
    service = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=WeakCriticalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    p = critical_proposal(clock)
    decision = service.evaluate(
        proposal=p,
        context=InteractionContext(
            session_id="s1",
            trust_tier=TrustTier.UNVERIFIED,
        ),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("insufficient_trust",)


def test_strong_approval_cannot_be_replayed_after_consumption() -> None:
    clock = FakeClock()
    approvals = ApprovalService(clock=clock)
    p = critical_proposal(clock)
    record = approvals.request(
        p,
        session_id="s1",
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=30,
    )
    granted = approvals.grant(
        record.approval_id,
        proposal=p,
        session_id="s1",
        method=ApprovalMethod.STRONG_VERIFIER,
    )
    approvals.consume(
        granted.approval_id,
        proposal=p,
        session_id="s1",
        minimum_requirement=ApprovalRequirement.STRONG,
    )
    with pytest.raises(ApprovalError):
        approvals.validate(
            granted.approval_id,
            proposal=p,
            session_id="s1",
            minimum_requirement=ApprovalRequirement.STRONG,
        )


def test_audit_rejects_sensitive_metadata_keys() -> None:
    with pytest.raises(AuditError, match="forbidden"):
        AuditEvent.create(
            event_type="authority",
            component="test",
            metadata={"face_embedding": "do-not-store"},
        )
    with pytest.raises(AuditError, match="forbidden"):
        AuditEvent.create(
            event_type="authority",
            component="test",
            metadata={"access_token": "do-not-store"},
        )


def test_sqlite_audit_store_persists_structured_event(tmp_path) -> None:
    db_path = tmp_path / "audit.db"
    store = SqliteAuditEventStore(db_path)
    event = AuditEvent.create(
        event_type="authority_deny",
        component="test",
        session_id="s1",
        reason_codes=("denied",),
        metadata={"risk_class": "CRITICAL"},
        now_epoch=123.0,
    )
    store.append(event)
    store.close()

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        """
        SELECT event_type, session_id, metadata_json
        FROM authority_audit_event
        """
    ).fetchone()
    connection.close()
    assert row == (
        "authority_deny",
        "s1",
        '{"risk_class":"CRITICAL"}',
    )


def test_authority_session_manager_invalidates_security_transition() -> None:
    manager = AuthoritySessionManager()
    session = manager.start(
        windows_session_id=7,
        windows_user_sid_hash="sid-hash",
        now_monotonic=10,
    )
    invalidated = manager.invalidate(
        SessionSecurityEvent.LOCK,
        now_monotonic=20,
    )
    assert invalidated is not None
    assert invalidated.session_id == session.session_id
    assert not invalidated.active_unlocked
    assert invalidated.invalidation_reason is SessionSecurityEvent.LOCK
    assert invalidated.invalidated_at_monotonic == 20


def test_model_suggested_private_disclosure_requires_attention() -> None:
    class PrivatePolicy:
        def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
            return PolicyDecision(
                effect=AuthorityEffect.ALLOW,
                requirements=PolicyRequirements(
                    required_trust=TrustTier.CORROBORATED_OWNER,
                    approval_requirement=ApprovalRequirement.EXPLICIT,
                    require_owner_attentive=True,
                    require_actor_unambiguous=True,
                ),
                reason_codes=(),
                policy_version="step3-v1",
            )

    clock = FakeClock()
    approvals = ApprovalService(clock=clock)
    service = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=PrivatePolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    p = ActionProposal.create(
        session_id="s1",
        capability="private",
        operation="reveal",
        target={},
        parameters={},
        material_summary="reveal private information",
        attributes=ActionAttributes(private_read=True),
        origin=ActionOrigin.MODEL_SUGGESTED,
        now_monotonic=clock(),
    )
    record = approvals.request(
        p,
        session_id="s1",
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=30,
    )
    granted = approvals.grant(
        record.approval_id,
        proposal=p,
        session_id="s1",
        method=ApprovalMethod.SPOKEN,
    )
    decision = service.evaluate(
        proposal=p,
        context=InteractionContext(
            session_id="s1",
            trust_tier=TrustTier.CORROBORATED_OWNER,
            attention_state=AttentionState.NOT_ATTENTIVE,
            actor_unambiguous=True,
        ),
        approval_id=granted.approval_id,
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("owner_attention_required",)


def test_policy_engine_exception_fails_closed() -> None:
    class BrokenPolicy:
        def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
            raise RuntimeError("boom")

    clock = FakeClock()
    service = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=BrokenPolicy(),
        approvals=ApprovalService(clock=clock),
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    p = ActionProposal.create(
        session_id="s1",
        capability="test",
        operation="read",
        target={},
        parameters={},
        material_summary="routine action",
        attributes=ActionAttributes(),
        origin=ActionOrigin.DIRECT_USER,
        now_monotonic=clock(),
    )
    decision = service.evaluate(
        proposal=p,
        context=InteractionContext(
            session_id="s1",
            trust_tier=TrustTier.UNVERIFIED,
        ),
    )
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("policy_engine_exception",)
    assert decision.risk_class.name == "ROUTINE"
