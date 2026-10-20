from __future__ import annotations

import types
from dataclasses import replace

import pytest

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import InMemoryAuditEventStore
from jarvis.authority.permit import PermitRegistry, PermitStatus
from jarvis.authority.policy import PolicyDecision, hard_floor_for
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityService
from jarvis.authority.session import AuthoritySession, WindowsSessionUnavailable
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
    AuthorityEffect,
    TrustTier,
)
from jarvis.capabilities.authority_bridge import (
    CapabilityAuthorityBroker,
    CapabilityAuthorizationError,
)
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityRequest


class FakeCanonicalAuthority:
    def __init__(self) -> None:
        self.evaluations: list[tuple[object, object, str | None]] = []
        self.consumed: list[tuple[str, object, object]] = []
        self.invalidated: list[str] = []

    def invalidate_session(self, session_id):
        self.invalidated.append(session_id)

    def evaluate(self, *, proposal, context, approval_id=None):
        self.evaluations.append((proposal, context, approval_id))
        return types.SimpleNamespace(
            effect=AuthorityEffect.ALLOW,
            execution_permit=types.SimpleNamespace(permit_id="hands-permit"),
            reason_codes=(),
        )

    def revalidate_and_consume(self, *, permit_id, proposal, context):
        self.consumed.append((permit_id, proposal, context))
        return object()


class FakeStrongApproval:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def verify_and_resolve(self, *, proposal, session_id):
        self.calls.append((proposal, session_id))
        return types.SimpleNamespace(
            granted=True,
            approval=types.SimpleNamespace(approval_id="hands-approval"),
            verification=types.SimpleNamespace(reason_codes=()),
        )


class MutableWindowsSessionProvider:
    def __init__(self) -> None:
        self.session = AuthoritySession(
            session_id="wts:1",
            windows_session_id=1,
            windows_user_sid_hash="owner-sid",
            active_unlocked=True,
            generation=0,
            created_at_monotonic=100.0,
        )
        self.unavailable = False

    def current_session(self):
        if self.unavailable:
            raise WindowsSessionUnavailable("controlled WTS failure")
        return self.session

    def transition(self, change):
        if change == "lock":
            self.session = replace(self.session, active_unlocked=False)
        elif change == "switch":
            self.session = replace(
                self.session, windows_session_id=2, session_id="wts:2"
            )
        elif change == "user_change":
            self.session = replace(self.session, windows_user_sid_hash="different-sid")
        else:
            self.unavailable = True


def prepared(
    attributes: ActionAttributes,
    *,
    session_id: str = "hands-session",
    origin: ActionOrigin = ActionOrigin.DIRECT_USER,
) -> PreparedCapability:
    request = CapabilityRequest(
        session_id=session_id,
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        parameters={"app": "notepad"},
        origin=origin,
    )
    return PreparedCapability(
        request=request,
        target={"app": "notepad", "strategy": "structured_winapp"},
        parameters={"app": "notepad"},
        material_summary="Control Notepad to type hello",
        attributes=attributes,
        execution_payload={},
    )


def configured_broker(
    *,
    ttl_seconds: float = 30.0,
    clock=lambda: 100.0,
) -> tuple[
    CapabilityAuthorityBroker,
    FakeCanonicalAuthority,
    FakeStrongApproval,
    ApprovalService,
]:
    canonical = FakeCanonicalAuthority()
    strong = FakeStrongApproval()
    approvals = ApprovalService()
    broker = CapabilityAuthorityBroker(
        trusted_session_ttl_seconds=ttl_seconds,
        clock=clock,
        session_provider=MutableWindowsSessionProvider(),
    )
    broker._authority = canonical
    broker._strong = strong
    broker._approvals = approvals
    return broker, canonical, strong, approvals


def test_reversible_local_control_first_use_escalates_to_t3_strong_owner() -> None:
    broker, canonical, strong, _ = configured_broker()

    authorized = broker.authorize(
        prepared(ActionAttributes(reversible_local_change=True))
    )
    broker.consume(authorized)

    assert len(strong.calls) == 1
    proposal, context, approval_id = canonical.evaluations[0]
    assert proposal.attributes.reversible_local_change is True
    assert context.trust_tier is TrustTier.VERIFIED_OWNER
    assert context.actor_unambiguous is True
    assert approval_id == "hands-approval"
    assert canonical.consumed[0][0] == "hands-permit"
    assert canonical.consumed[0][1].fingerprint == proposal.fingerprint


def test_routine_capability_does_not_invoke_windows_hello() -> None:
    broker, canonical, strong, _ = configured_broker()

    broker.authorize(prepared(ActionAttributes()))

    assert strong.calls == []
    _, context, approval_id = canonical.evaluations[0]
    assert context.trust_tier is TrustTier.UNVERIFIED
    assert approval_id is None


def test_trusted_session_reuses_t2_without_second_strong_verification() -> None:
    broker, canonical, strong, approvals = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(prepared(ActionAttributes(private_read=True)))

    assert len(strong.calls) == 1
    proposal, context, approval_id = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.CORROBORATED_OWNER
    assert context.actor_unambiguous is True
    assert approval_id is not None
    record = approvals.get(approval_id)
    assert record.proposal_id == proposal.proposal_id
    assert record.requirement is ApprovalRequirement.DIRECT_INTENT
    assert record.method is ApprovalMethod.DIRECT_INTENT


def test_trusted_session_persistent_action_keeps_explicit_approval() -> None:
    broker, canonical, strong, approvals = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(prepared(ActionAttributes(persistent_write=True)))

    assert len(strong.calls) == 1
    proposal, context, approval_id = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.CORROBORATED_OWNER
    assert approval_id is not None
    record = approvals.get(approval_id)
    assert record.proposal_id == proposal.proposal_id
    assert record.requirement is ApprovalRequirement.EXPLICIT
    assert record.method is ApprovalMethod.SPOKEN


def test_critical_action_never_reuses_trusted_session() -> None:
    broker, canonical, strong, _ = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(prepared(ActionAttributes(destructive=True)))

    assert len(strong.calls) == 2
    _, context, approval_id = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.VERIFIED_OWNER
    assert approval_id == "hands-approval"


def test_restricted_action_never_reuses_trusted_session() -> None:
    broker, canonical, strong, _ = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(prepared(ActionAttributes(self_modification=True)))

    assert len(strong.calls) == 2
    _, context, _ = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.VERIFIED_OWNER


def test_trusted_session_is_scoped_to_exact_session_id() -> None:
    broker, canonical, strong, _ = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(
        prepared(
            ActionAttributes(reversible_local_change=True),
            session_id="different-session",
        )
    )

    assert len(strong.calls) == 2
    _, context, _ = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.VERIFIED_OWNER


def test_trusted_session_expires_without_sliding_refresh() -> None:
    now = [100.0]
    broker, canonical, strong, _ = configured_broker(
        ttl_seconds=30.0,
        clock=lambda: now[0],
    )

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    now[0] = 120.0
    broker.authorize(prepared(ActionAttributes(private_read=True)))
    now[0] = 131.0
    broker.authorize(prepared(ActionAttributes(private_read=True)))

    assert len(strong.calls) == 2
    assert canonical.evaluations[1][1].trust_tier is TrustTier.CORROBORATED_OWNER
    assert canonical.evaluations[2][1].trust_tier is TrustTier.VERIFIED_OWNER


def test_model_suggested_action_cannot_reuse_direct_user_trust() -> None:
    broker, canonical, strong, _ = configured_broker()

    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    broker.authorize(
        prepared(
            ActionAttributes(private_read=True),
            origin=ActionOrigin.MODEL_SUGGESTED,
        )
    )

    assert len(strong.calls) == 2
    _, context, _ = canonical.evaluations[1]
    assert context.trust_tier is TrustTier.VERIFIED_OWNER


def test_close_clears_trusted_session() -> None:
    broker, _, strong, _ = configured_broker()
    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    assert len(strong.calls) == 1

    broker.close()

    canonical = FakeCanonicalAuthority()
    approvals = ApprovalService()
    broker._authority = canonical
    broker._strong = strong
    broker._approvals = approvals
    broker.authorize(prepared(ActionAttributes(private_read=True)))

    assert len(strong.calls) == 2
    assert canonical.evaluations[0][1].trust_tier is TrustTier.VERIFIED_OWNER


@pytest.mark.parametrize("change", ["lock", "switch", "user_change", "unavailable"])
def test_windows_security_transition_denies_cached_trust_and_requires_new_hello(change):
    broker, canonical, strong, _ = configured_broker()
    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    provider = broker._session_provider
    provider.transition(change)

    with pytest.raises(CapabilityAuthorizationError, match="Windows session"):
        broker.authorize(prepared(ActionAttributes(private_read=True)))

    assert canonical.invalidated == ["hands-session"]
    provider.session = replace(provider.session, active_unlocked=True)
    provider.unavailable = False
    broker.authorize(prepared(ActionAttributes(private_read=True)))
    assert len(strong.calls) == 2


@pytest.mark.parametrize("change", ["lock", "switch", "unavailable"])
def test_windows_transition_after_authorization_blocks_consumption_permanently(change):
    broker, canonical, _, _ = configured_broker()
    authorized = broker.authorize(
        prepared(ActionAttributes(reversible_local_change=True))
    )
    provider = broker._session_provider
    original = provider.session
    provider.transition(change)

    with pytest.raises(CapabilityAuthorizationError, match="Windows session"):
        broker.consume(authorized)
    assert canonical.consumed == []

    provider.session = original
    provider.unavailable = False
    with pytest.raises(CapabilityAuthorizationError):
        broker.consume(authorized)
    assert canonical.consumed == []


@pytest.mark.parametrize("change", ["lock", "switch", "unavailable"])
def test_windows_transition_during_hello_cannot_create_authorization(change):
    broker, canonical, strong, _ = configured_broker()
    verify = strong.verify_and_resolve

    def transition_during_verification(**kwargs):
        outcome = verify(**kwargs)
        broker._session_provider.transition(change)
        return outcome

    strong.verify_and_resolve = transition_during_verification
    with pytest.raises(CapabilityAuthorizationError, match="Windows session"):
        broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    assert canonical.evaluations == []


def test_initial_unavailable_windows_session_denies_even_routine_action():
    broker, canonical, strong, _ = configured_broker()
    broker._session_provider.unavailable = True
    with pytest.raises(CapabilityAuthorizationError, match="Windows session"):
        broker.authorize(prepared(ActionAttributes()))
    assert canonical.evaluations == []
    assert strong.calls == []


@pytest.mark.parametrize("change", ["lock", "switch", "unavailable"])
def test_windows_transition_invalidates_real_pending_permits_across_voice_sessions(
    change,
):
    broker, _, _, approvals = configured_broker()
    permits = PermitRegistry()
    policy = types.SimpleNamespace(
        evaluate=lambda request: PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=hard_floor_for(request.risk_class),
            reason_codes=(),
            policy_version="offline-test",
        )
    )
    broker._authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=policy,
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=permits,
    )
    first = broker.authorize(prepared(ActionAttributes(), session_id="first-voice"))
    second = broker.authorize(prepared(ActionAttributes(), session_id="second-voice"))
    broker._session_provider.transition(change)
    with pytest.raises(CapabilityAuthorizationError):
        broker.consume(first)
    with permits.lock:
        assert permits.get_locked(first.permit_id).status is PermitStatus.INVALIDATED
        assert permits.get_locked(second.permit_id).status is PermitStatus.INVALIDATED


def test_trusted_session_expiring_after_approval_cannot_be_consumed():
    now = [100.0]
    broker, canonical, _, _ = configured_broker(ttl_seconds=30.0, clock=lambda: now[0])
    broker.authorize(prepared(ActionAttributes(reversible_local_change=True)))
    now[0] = 129.0
    authorized = broker.authorize(prepared(ActionAttributes(private_read=True)))
    now[0] = 131.0
    with pytest.raises(CapabilityAuthorizationError, match="trust expired"):
        broker.consume(authorized)
    assert canonical.consumed == []


def test_lock_unlock_between_authorizations_invalidates_cached_trust_and_old_permit():
    broker, canonical, strong, _ = configured_broker()
    original_permit = broker.authorize(
        prepared(ActionAttributes(reversible_local_change=True))
    )
    provider = broker._session_provider
    # The native event listener preserves these two transitions even though
    # both boundary snapshots see the same unlocked Windows session.
    provider.session = replace(
        provider.session, generation=provider.session.generation + 2
    )
    with pytest.raises(CapabilityAuthorizationError, match="Windows session changed"):
        broker.authorize(prepared(ActionAttributes(private_read=True)))
    broker.authorize(prepared(ActionAttributes(private_read=True)))
    assert len(strong.calls) == 2
    with pytest.raises(CapabilityAuthorizationError, match="invalidated"):
        broker.consume(original_permit)
    assert canonical.consumed == []
