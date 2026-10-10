"""Existing AuthorityService approval must bind active AEP discovery exactly."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.test_authority_foundation import LocalPolicy
from tests.test_gicc_windows_aep import FakeWatcher, _device

from jarvis.authority import (
    AttentionState,
    AuthorityEffect,
    AuthorityService,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    RiskClassifier,
    TrustTier,
)
from jarvis.authority.approval import ApprovalService
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
)
from jarvis.goal_intelligence.aep_authority import (
    AepAuthorityExecutionGuard,
    AepExistingApprovalValidator,
    aep_approval_material,
    build_aep_consent_proposal,
)
from jarvis.goal_intelligence.windows_aep import (
    ReviewedAepScopeV1,
    WindowsAepIdentityBackend,
)


def _scope(*, record: str = "pending") -> ReviewedAepScopeV1:
    return ReviewedAepScopeV1(
        protocol="upnp",
        approved_address_ranges=("192.168.1.0/24",),
        consent_record_id=record,
        all_local_interfaces_authorized=True,
        timeout_seconds=0.5,
        max_results=4,
    )


def _setup():
    clock = [100.0]
    approvals = ApprovalService(clock=lambda: clock[0])
    scope = _scope()
    target, parameters = aep_approval_material(scope)
    proposal = ActionProposal.create(
        session_id="owner-session",
        capability="network_discovery",
        operation="enumerate_aep",
        target=target,
        parameters=parameters,
        material_summary="Permit bounded UPnP AEP discovery on my local interfaces.",
        attributes=ActionAttributes(external_side_effect=True),
        origin=ActionOrigin.DIRECT_USER,
        ttl_seconds=60.0,
        now_monotonic=100.0,
    )
    record = approvals.request(
        proposal,
        session_id="owner-session",
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=30.0,
    )
    scope = replace(scope, consent_record_id=record.approval_id)
    validator = AepExistingApprovalValidator(
        approvals=approvals,
        proposal=proposal,
        session_id="owner-session",
    )
    return scope, approvals, proposal, validator, clock


def test_owner_approval_readiness_alone_is_not_an_execution_permit() -> None:
    scope, approvals, proposal, readiness, clock = _setup()

    assert not readiness(scope)
    approvals.grant(
        scope.consent_record_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    # This reports approval status only. Production scanning requires the
    # audited execution permit consumed by AepAuthorityExecutionGuard.
    assert readiness(scope)
    clock[0] = 131.0
    assert not readiness(scope)


def test_real_authority_grant_is_exact_to_protocol_network_and_timeout() -> None:
    scope, approvals, proposal, validator, _clock = _setup()
    approvals.grant(
        scope.consent_record_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    assert validator(scope)
    assert not validator(replace(scope, protocol="dns_sd"))
    assert not validator(replace(scope, approved_address_ranges=("192.168.2.0/24",)))
    assert not validator(replace(scope, timeout_seconds=0.75))
    assert not validator(replace(scope, max_results=6))
    assert not validator(replace(scope, consent_record_id="unrelated-approval"))


def test_unapproved_action_and_wrong_session_cannot_be_reused_for_aep() -> None:
    scope, approvals, proposal, validator, _clock = _setup()
    with pytest.raises(ValueError, match="active session"):
        AepExistingApprovalValidator(
            approvals=approvals,
            proposal=proposal,
            session_id="unrelated-session",
        )
    assert not validator(scope)
    approvals.invalidate_session("owner-session")
    assert not validator(scope)


def _policy_authority(approvals: ApprovalService, clock):
    return AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=lambda: clock[0]),
        clock=lambda: clock[0],
    )


def _policy_context():
    return InteractionContext(
        session_id="owner-session",
        trust_tier=TrustTier.CORROBORATED_OWNER,
        attention_state=AttentionState.ATTENTIVE,
        actor_unambiguous=True,
    )


def test_aep_requires_policy_audit_and_one_time_execution_permit() -> None:
    scope, approvals, proposal, _readiness, clock = _setup()
    authority = _policy_authority(approvals, clock)
    context = _policy_context()

    denied = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=scope.consent_record_id,
    )
    assert denied.effect is AuthorityEffect.DENY

    approvals.grant(
        scope.consent_record_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=scope.consent_record_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None

    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=context,
        permit_id=decision.execution_permit.permit_id,
        approval_id=scope.consent_record_id,
    )
    watcher = FakeWatcher(rows=(_device(),))
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=guard,
        watcher_factory=lambda _: watcher,
        clock=lambda: 100.0,
    )
    assert len(backend.observe(scope)) == 1
    assert watcher.started == watcher.stopped == 1

    # Neither the approval nor its execution permit is reusable.
    assert backend.observe(scope) == ()
    assert watcher.started == 1


def test_aep_full_authority_guard_denies_scope_change_without_consuming_permit() -> (
    None
):
    scope, approvals, proposal, _readiness, clock = _setup()
    approvals.grant(
        scope.consent_record_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    authority = _policy_authority(approvals, clock)
    context = _policy_context()
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=scope.consent_record_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=context,
        permit_id=decision.execution_permit.permit_id,
        approval_id=scope.consent_record_id,
    )
    assert not guard(replace(scope, protocol="dns_sd"))
    assert not guard(replace(scope, max_results=5))
    assert not guard(replace(scope, consent_record_id="unrelated"))
    assert guard(scope)
    assert not guard(scope)


def test_active_aep_guard_rejects_non_authority_service() -> None:
    scope, _approvals, proposal, _readiness, _clock = _setup()
    with pytest.raises(TypeError, match="canonical AuthorityService"):
        AepAuthorityExecutionGuard(
            authority=object(),
            proposal=proposal,
            context=_policy_context(),
            permit_id="some-permit",
            approval_id=scope.consent_record_id,
        )


def test_jarvis_prepares_owner_consent_request_without_network_actions() -> None:
    """GICC, not the owner, constructs the reviewed discovery permission ask."""

    from jarvis.authority.types import ActionOrigin

    scope = _scope()
    proposal = build_aep_consent_proposal(
        scope=scope,
        session_id="owner-session",
    )
    assert proposal.has_valid_fingerprint()
    assert proposal.origin is ActionOrigin.PROACTIVE
    assert proposal.capability == "network_discovery"
    assert proposal.operation == "enumerate_aep"
    assert proposal.target()["all_local_interfaces"] is True
    assert proposal.parameters()["device_control"] is False
    assert proposal.parameters()["pairing"] is False
    assert "across all local network interfaces" in proposal.material_summary
    assert "192.168.1.0/24" in proposal.material_summary
    assert "No control, pairing" in proposal.material_summary
    assert proposal.expires_at_monotonic > proposal.created_at_monotonic


def test_consent_proposal_fingerprint_changes_with_reviewed_scope() -> None:
    scope = _scope()
    base = build_aep_consent_proposal(scope=scope, session_id="owner-session")
    narrower = build_aep_consent_proposal(
        scope=replace(scope, max_results=2), session_id="owner-session"
    )
    assert base.target_json == narrower.target_json
    assert base.parameters_json != narrower.parameters_json
    assert base.fingerprint != narrower.fingerprint
