from dataclasses import replace

import pytest

from jarvis.authority.approval import ApprovalError
from jarvis.authority.personal_learning import (
    LearningActionBinding,
    LearningGrantHandle,
)
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
)


def binding(**changes):
    return replace(
        LearningActionBinding("admit", "source-1", "a" * 64, ("owned_item",)),
        **changes,
    )


def opened(authority):
    grant = authority.open("runtime-A", "gemini")
    authority.register_source(grant, "source-1")
    return grant


def test_absolute_expiry_is_not_renewed_by_input(authority, clock):
    grant = opened(authority)
    for index in range(4):
        clock.advance(200)
        authority.observe_accepted_input(grant, f"turn-{index}")
    clock.advance(100)
    assert authority.validate(grant).status == "expired"


def test_duplicate_input_does_not_extend_idle(authority, clock):
    grant = opened(authority)
    authority.observe_accepted_input(grant, "one")
    clock.advance(299)
    authority.observe_accepted_input(grant, "one")
    clock.advance(1)
    assert authority.validate(grant).status == "expired"


def test_one_hello_for_multiple_exact_system_children(authority, authority_parts):
    grant = opened(authority)
    for _ in range(2):
        permit = authority.issue_child(grant, binding())
        with authority.commit_scope(permit):
            pass
        with pytest.raises(PermissionError), authority.commit_scope(permit):
            pass
    assert len(authority_parts.hello.calls) == 1
    assert authority_parts.broker._trusted_sessions == {}
    summary = authority_parts.hello.calls[0].material_summary
    assert "15" in summary and "5" in summary and "speaker" in summary


def test_lock_epoch_invalidates_late_child(authority, authority_parts):
    grant = opened(authority)
    permit = authority.issue_child(grant, binding())
    authority_parts.windows.lock_unlock()
    with pytest.raises(PermissionError), authority.commit_scope(permit):
        pytest.fail("lock transition must veto commit")
    assert authority.validate(grant).status == "revoked"


def test_forged_or_copied_grants_are_not_registered(authority):
    grant = opened(authority)
    for forged in [LearningGrantHandle("invented"), replace(grant)]:
        assert authority.validate(forged).status == "denied"
        with pytest.raises(PermissionError):
            authority.issue_child(forged, binding())


def test_denied_open_never_grants(authority, authority_parts):
    authority_parts.hello.denied = True
    with pytest.raises(PermissionError):
        authority.open("runtime-A", "gemini")


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "forget"},
        {"categories": ("medical",)},
        {"policy_version": "spoofed"},
        {"source_receipt_id": "unknown"},
        {"payload_sha256": "bad"},
    ],
)
def test_children_cannot_expand_scope(authority, change):
    grant = opened(authority)
    with pytest.raises((ValueError, PermissionError)):
        authority.issue_child(grant, binding(**change))


def test_parent_id_cannot_be_used_as_generic_approval(authority, authority_parts):
    grant = opened(authority)
    permit = authority.issue_child(grant, binding())
    issued = authority.describe_child(permit)
    assert issued.proposal.origin is ActionOrigin.SYSTEM
    with pytest.raises(ApprovalError):
        authority_parts.approvals.grant(
            issued.proposal.proposal_id,
            proposal=issued.proposal,
            session_id=issued.proposal.session_id,
            method=ApprovalMethod.DELEGATED_POLICY,
        )


def test_expiry_checked_inside_lease(authority, clock):
    grant = opened(authority)
    permit = authority.issue_child(grant, binding())
    with pytest.raises(PermissionError), authority.commit_scope(permit):
        clock.advance(901)


def test_read_lease_checks_grant_after_consumption(authority, clock):
    grant = opened(authority)
    permit = authority.issue_child(grant, binding(operation="read"))
    authority.consume_read(permit)
    authority.validate_read(permit)
    clock.advance(300)
    with pytest.raises(PermissionError):
        authority.validate_read(permit)


def test_delegation_cannot_approve_another_capability(authority, authority_parts):
    grant = opened(authority)
    proposal = ActionProposal.create(
        session_id="runtime-A",
        capability="windows:desktop.control",
        operation="admit",
        target={},
        parameters={},
        material_summary="unrelated",
        origin=ActionOrigin.SYSTEM,
        attributes=ActionAttributes(persistent_write=True),
        now_monotonic=100,
    )
    pending = authority_parts.approvals.request(
        proposal,
        session_id="runtime-A",
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=30,
    )
    with pytest.raises(ApprovalError):
        authority_parts.approvals.grant_delegated(
            pending.approval_id, proposal=proposal, session_id="runtime-A", grant=grant
        )


def test_child_must_use_registered_source(authority):
    grant = opened(authority)
    with pytest.raises(PermissionError):
        authority.issue_child(
            grant, binding(source_receipt_id="source-from-other-runtime")
        )
