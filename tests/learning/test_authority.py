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


def test_session_permission_survives_old_absolute_limit(authority, clock):
    grant = opened(authority)
    for index in range(4):
        clock.advance(200)
        authority.observe_accepted_input(grant, f"turn-{index}")
    clock.advance(100)
    assert authority.validate(grant).status == "active"


def test_session_permission_survives_idle_without_new_input(authority, clock):
    grant = opened(authority)
    authority.observe_accepted_input(grant, "one")
    clock.advance(299)
    authority.observe_accepted_input(grant, "one")
    clock.advance(1)
    assert authority.validate(grant).status == "active"


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
    assert "unlocked Windows session" in summary and "speaker" in summary


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


def test_short_child_lease_expiry_checked_inside_commit(authority, clock):
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


@pytest.mark.parametrize("pause", [301, 901, 86400])
def test_fresh_children_after_long_pause_need_no_new_hello(
    authority, authority_parts, clock, pause
):
    grant = opened(authority)
    clock.advance(pause)
    authority.observe_accepted_input(grant, "fresh-turn")
    authority.register_source(grant, "fresh-source")
    permit = authority.issue_child(grant, binding(source_receipt_id="fresh-source"))
    with authority.commit_scope(permit):
        pass
    assert len(authority_parts.hello.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"active_unlocked": False},
        {"windows_user_sid_hash": "another-user"},
        {"windows_session_id": 2},
        {"generation": 2},
    ],
)
def test_session_changes_revoke_even_after_long_idle(
    authority, authority_parts, clock, change
):
    grant = opened(authority)
    clock.advance(86400)
    authority_parts.windows.value = replace(authority_parts.windows.value, **change)
    assert authority.validate(grant).status == "revoked"
    with pytest.raises(PermissionError):
        authority.register_source(grant, "fresh-source")


def test_close_revokes_session_permission(authority, clock):
    grant = opened(authority)
    clock.advance(86400)
    authority.close()
    assert authority.validate(grant).status == "revoked"


def test_second_revoke_after_controller_closes_broker_is_harmless(
    authority, authority_parts, tmp_path
):
    from jarvis.authority.audit import SqliteAuditEventStore

    authority_parts.broker._audit = SqliteAuditEventStore(
        tmp_path / "authority.sqlite3"
    )
    grant = opened(authority)
    authority.close()
    authority_parts.broker.close()
    authority.revoke(grant)
    state = authority.validate(grant)
    assert state.status == "revoked"
    assert state.reason == "runtime_closed"
    with pytest.raises(PermissionError):
        authority.register_source(grant, "late-source")
