from __future__ import annotations

import types

from jarvis.authority.approval import ApprovalService
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
    AuthorityEffect,
    TrustTier,
)
from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityRequest


class FakeCanonicalAuthority:
    def __init__(self) -> None:
        self.evaluations: list[tuple[object, object, str | None]] = []
        self.consumed: list[tuple[str, object, object]] = []

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
