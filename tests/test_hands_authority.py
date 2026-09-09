from __future__ import annotations

import types

from jarvis.authority.types import ActionAttributes, AuthorityEffect, TrustTier
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


def prepared(attributes: ActionAttributes) -> PreparedCapability:
    request = CapabilityRequest(
        session_id="hands-session",
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        parameters={"app": "notepad"},
    )
    return PreparedCapability(
        request=request,
        target={"app": "notepad", "strategy": "structured_winapp"},
        parameters={"app": "notepad"},
        material_summary="Control Notepad to type hello",
        attributes=attributes,
        execution_payload={},
    )


def test_reversible_local_control_escalates_to_t3_strong_owner() -> None:
    canonical = FakeCanonicalAuthority()
    strong = FakeStrongApproval()
    broker = CapabilityAuthorityBroker()
    broker._authority = canonical
    broker._strong = strong

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
    canonical = FakeCanonicalAuthority()
    strong = FakeStrongApproval()
    broker = CapabilityAuthorityBroker()
    broker._authority = canonical
    broker._strong = strong

    broker.authorize(prepared(ActionAttributes()))

    assert strong.calls == []
    _, context, approval_id = canonical.evaluations[0]
    assert context.trust_tier is TrustTier.UNVERIFIED
    assert approval_id is None
