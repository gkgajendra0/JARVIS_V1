from dataclasses import replace

import pytest

from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError
from jarvis.model_routing.budget import PaidBudgetDenied

from .admin_helpers import broker, unknown_complete


def admin(env, b):
    from jarvis.model_routing.live_budget_admin import LiveBudgetAdministration

    return LiveBudgetAdministration(env.runtime, broker=b)


def test_reconcile_requires_exact_fresh_owner_approval(op_env):
    _r, e = unknown_complete(op_env)
    b, v = broker()
    a = admin(op_env, b)
    p = a.prepare_reconciliation(e, session_id="owner")
    assert p.attributes.financial_or_legal and p.attributes.persistent_write
    v.allowed = False
    with pytest.raises(CapabilityAuthorizationError):
        a.reconcile(e, session_id="owner")
    assert op_env.governor.status().unknown_reservations == 1
    v.allowed = True
    result = a.reconcile(e, session_id="owner")
    assert result.state == "settled"
    s = op_env.governor.status()
    assert (s.spent_inr_minor, s.reserved_inr_minor, s.unknown_reservations) == (
        850,
        0,
        0,
    )
    a.reconcile(e, session_id="owner")
    assert op_env.governor.status().spent_inr_minor == 850


@pytest.mark.parametrize(
    "field,value",
    [("target_id", "wrong"), ("profile_ref", "b" * 64), ("source_digest", "c" * 64)],
)
def test_receipt_or_profile_hash_tamper_is_denied(op_env, field, value):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    with pytest.raises(PaidBudgetDenied):
        admin(op_env, b).reconcile(replace(e, **{field: value}), session_id="owner")
    assert op_env.governor.status().reserved_inr_minor == 150


def test_lock_between_approval_and_commit_rolls_back(op_env, monkeypatch):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    a = admin(op_env, b)
    original = b.audit_result

    def lock(**kwargs):
        original(**kwargs)
        b._session_provider.transition("lock")

    monkeypatch.setattr(b, "audit_result", lock)
    with pytest.raises(CapabilityAuthorizationError):
        a.reconcile(e, session_id="owner")
    assert op_env.governor.status().unknown_reservations == 1


def test_result_audit_failure_blocks_without_replaying_debit(op_env, monkeypatch):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    a = admin(op_env, b)
    real = b.audit_result
    count = [0]

    def failing(**kwargs):
        count[0] += 1
        if count[0] == 2:
            raise OSError("offline result audit failed")
        real(**kwargs)

    monkeypatch.setattr(b, "audit_result", failing)
    with pytest.raises(OSError):
        a.reconcile(e, session_id="owner")
    s = op_env.governor.status()
    assert s.spent_inr_minor == 850 and s.blocked_reason == "admin_audit_unresolved"
    monkeypatch.setattr(b, "audit_result", real)
    a.reconcile(e, session_id="owner")
    assert op_env.governor.status().spent_inr_minor == 850
    assert op_env.governor.status().blocked_reason is None


def test_zero_guess_or_project_aggregate_cannot_clear_hold(op_env):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    fake = replace(e.reports[0], usage={k: 0 for k in e.reports[0].usage})
    with pytest.raises(PaidBudgetDenied):
        admin(op_env, b).reconcile(replace(e, reports=(fake,)), session_id="owner")
    assert op_env.governor.status().unknown_reservations == 1


def test_consumed_admin_permit_cannot_replay(op_env):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    a = admin(op_env, b)
    prepared = a.prepare_reconciliation(e, session_id="owner")
    authorized = b.authorize_fresh_owner(prepared)
    b.consume(authorized)
    with pytest.raises(CapabilityAuthorizationError):
        b.consume(authorized)
    assert op_env.governor.status().unknown_reservations == 1


def test_lock_at_transaction_commit_rolls_back_money_and_receipt(op_env, monkeypatch):
    _, e = unknown_complete(op_env)
    b, _ = broker()
    a = admin(op_env, b)
    real = b.validate_binding
    n = [0]

    def validate(auth):
        n[0] += 1
        if n[0] == 3:
            b._session_provider.transition("lock")
        real(auth)

    monkeypatch.setattr(b, "validate_binding", validate)
    with pytest.raises(CapabilityAuthorizationError):
        a.reconcile(e, session_id="owner")
    s = op_env.governor.status()
    assert (s.spent_inr_minor, s.reserved_inr_minor, s.unknown_reservations) == (
        850,
        150,
        1,
    )


def test_other_unknown_rows_keep_budget_blocked(op_env):
    from tests.gemini_fallback.helpers import budget_fixture, exposure

    _, _, target, price = budget_fixture(op_env.store.work_store.path)
    strict = op_env.governor.reserve(
        invocation_id="other-work",
        target=target,
        pricing=price,
        exposure=exposure(1, 1),
    )
    op_env.governor.mark_dispatched(strict.reservation_id)
    _, e = unknown_complete(op_env)
    op_env.governor.settle(
        reservation_id=strict.reservation_id,
        usage={},
        usage_complete=False,
        event_id="other-work-unknown",
    )
    b, _ = broker()
    admin(op_env, b).reconcile(e, session_id="owner")
    assert op_env.governor.status().unknown_reservations == 1
    assert op_env.governor.status().blocked_reason == "unknown_usage"


def test_reconciliation_does_not_acknowledge_a_different_profile_action(op_env):
    from jarvis.model_routing.operational_budget import _journal

    r, e = unknown_complete(op_env)
    with op_env.store.work_store.extension_transaction() as c:
        _journal(
            op_env.governor,
            c,
            r.reservation_id,
            "unresolved-profile-action",
            {
                "kind": "operational_admin_commit",
                "operation": "qualify_profile",
                "evidence_ref": e.fingerprint,
            },
        )
    b, _ = broker()
    admin(op_env, b).reconcile(e, session_id="owner")
    assert op_env.governor.status().blocked_reason == "admin_audit_unresolved"


def test_strict_settlement_cannot_clear_an_unresolved_financial_audit(op_env):
    from tests.gemini_fallback.helpers import budget_fixture, exposure

    _, _, target, price = budget_fixture(op_env.store.work_store.path)
    strict = op_env.governor.reserve(
        invocation_id="parallel-work",
        target=target,
        pricing=price,
        exposure=exposure(1, 1),
    )
    op_env.governor.mark_dispatched(strict.reservation_id)
    _r, e = unknown_complete(op_env)
    op_env.governor.reconcile_operational_live(
        evidence=e, validate_owner=lambda: None, administrative_action_id="unresolved"
    )
    assert op_env.governor.status().blocked_reason == "admin_audit_unresolved"
    op_env.governor.settle(
        reservation_id=strict.reservation_id,
        usage={"input_tokens": 1, "output_tokens": 1},
        usage_complete=True,
        event_id="parallel-work-settle",
    )
    assert op_env.governor.status().blocked_reason == "admin_audit_unresolved"
