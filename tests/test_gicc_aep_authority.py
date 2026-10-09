"""Existing AuthorityService approval must bind active AEP discovery exactly."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.test_gicc_windows_aep import FakeWatcher, _device

from jarvis.authority.approval import ApprovalService
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
)
from jarvis.goal_intelligence.aep_authority import (
    AepExistingApprovalValidator,
    aep_approval_material,
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


def test_real_authority_grant_required_before_winrt_watcher_can_start() -> None:
    scope, approvals, proposal, validator, clock = _setup()
    watcher = FakeWatcher(rows=(_device(),))
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=validator,
        watcher_factory=lambda _: watcher,
        clock=lambda: 100.0,
    )

    assert backend.observe(scope) == ()
    assert watcher.started == 0

    approvals.grant(
        scope.consent_record_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    assert len(backend.observe(scope)) == 1
    assert watcher.started == watcher.stopped == 1

    # Expiring an existing session grant must disable discovery immediately.
    clock[0] = 131.0
    assert backend.observe(scope) == ()
    assert watcher.started == 1


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
