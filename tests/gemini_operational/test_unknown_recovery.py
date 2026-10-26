import pytest

from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError
from jarvis.model_routing.budget import PaidBudgetDenied

from .admin_helpers import broker
from .test_governor import checkpoint, finish, reserve


def closed_capture(env):
    r = reserve(env, capture_only=True)
    checkpoint(env, r)
    finish(env, r, complete=False)
    return r


def administration(env):
    from jarvis.model_routing.live_unknown_recovery import UnknownUsageAdministration

    b, verifier = broker()
    return UnknownUsageAdministration(env.runtime, broker=b), b, verifier


def acknowledge(admin, rid):
    snapshot = admin.preview_unknown(rid)
    return admin.acknowledge_unknown(
        rid, snapshot_ref=snapshot.fingerprint, session_id="owner-recovery"
    )


def test_recovery_retains_unknown_and_full_hold_but_allows_new_parent(op_env):
    r = closed_capture(op_env)
    a, _, _ = administration(op_env)
    result = acknowledge(a, r.reservation_id)
    assert result.state == "acknowledged_unknown"
    status = op_env.governor.status()
    assert status.unknown_reservations == 1
    assert status.spent_inr_minor == 0
    assert status.reserved_inr_minor == 1000
    assert status.estimated_total_inr_minor is None
    assert status.blocked_reason is None
    from jarvis.model_routing.status import paid_live_ledger_status

    row = paid_live_ledger_status(op_env.runtime)[0]
    assert row["usage_status"] == "unknown" and row["held_minor"] == 1000
    reserve(op_env, invocation_id="second")
    assert op_env.governor.status().reserved_inr_minor == 2000


def test_recovery_requires_financial_approval(op_env):
    r = closed_capture(op_env)
    a, _, v = administration(op_env)
    v.allowed = False
    with pytest.raises(CapabilityAuthorizationError):
        acknowledge(a, r.reservation_id)
    assert op_env.governor.status().blocked_reason == "unknown_usage"


def test_stale_snapshot_denied_before_approval(op_env):
    r = closed_capture(op_env)
    a, _, v = administration(op_env)
    with pytest.raises(PaidBudgetDenied):
        a.acknowledge_unknown(
            r.reservation_id, snapshot_ref="f" * 64, session_id="owner"
        )
    assert v.sequence == 0


@pytest.mark.parametrize("case", ["active", "unclosed", "not_capture", "overrun"])
def test_unsafe_recovery_denied(op_env, case):
    r = reserve(op_env, capture_only=case != "not_capture")
    checkpoint(op_env, r)
    if case != "active":
        finish(op_env, r, complete=False, teardown_confirmed=case != "unclosed")
    if case == "overrun":
        with op_env.store.work_store.extension_transaction() as c:
            c.execute(
                "UPDATE paid_fallback_budgets SET blocked_reason='observed_overrun'"
            )
    a, _, v = administration(op_env)
    with pytest.raises(PaidBudgetDenied):
        acknowledge(a, r.reservation_id)
    assert v.sequence == 0


def test_acknowledgement_idempotent_and_new_unknown_blocks(op_env):
    r = closed_capture(op_env)
    a, _, _ = administration(op_env)
    acknowledge(a, r.reservation_id)
    acknowledge(a, r.reservation_id)
    assert op_env.governor.status().reserved_inr_minor == 1000
    second = reserve(op_env, invocation_id="second", capture_only=True)
    checkpoint(op_env, second, trigger="second-initial")
    finish(op_env, second, complete=False, event_id="second-close")
    assert op_env.governor.status().unknown_reservations == 2
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="third")


def test_failed_result_audit_blocks_and_retry_retains_hold(op_env, monkeypatch):
    r = closed_capture(op_env)
    a, b, _ = administration(op_env)
    original = b.audit_result
    calls = [0]

    def fail_result(**kw):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("audit unavailable")
        return original(**kw)

    monkeypatch.setattr(b, "audit_result", fail_result)
    with pytest.raises(OSError):
        acknowledge(a, r.reservation_id)
    assert op_env.governor.status().blocked_reason == "admin_audit_unresolved"
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="blocked")
    monkeypatch.setattr(b, "audit_result", original)
    acknowledge(a, r.reservation_id)
    assert op_env.governor.status().blocked_reason is None
    assert op_env.governor.status().reserved_inr_minor == 1000


def test_acknowledged_hold_still_enforces_shared_ceiling(op_env):
    r = closed_capture(op_env)
    a, _, _ = administration(op_env)
    acknowledge(a, r.reservation_id)
    with op_env.store.work_store.extension_transaction() as c:
        c.execute("UPDATE paid_fallback_budgets SET spent_minor=33500")
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="would-overrun")


def test_preview_cli_does_not_ask_owner_or_mutate(op_env, capsys):
    from jarvis.paid_budget_cli import main

    r = closed_capture(op_env)
    a, _, v = administration(op_env)
    assert (
        main(
            ["acknowledge-unknown", "--reservation-id", r.reservation_id],
            administration=a,
        )
        == 0
    )
    assert v.sequence == 0
    assert '"snapshot_ref"' in capsys.readouterr().out
    assert op_env.governor.status().blocked_reason == "unknown_usage"


def test_lock_after_approval_preserves_unknown_state(op_env, monkeypatch):
    r = closed_capture(op_env)
    a, b, _ = administration(op_env)
    original = b.audit_result

    def lock(**kw):
        original(**kw)
        b._session_provider.transition("lock")

    monkeypatch.setattr(b, "audit_result", lock)
    with pytest.raises(CapabilityAuthorizationError):
        acknowledge(a, r.reservation_id)
    assert op_env.governor.status().blocked_reason == "unknown_usage"
    assert op_env.governor.status().reserved_inr_minor == 1000


def test_snapshot_race_after_approval_is_denied(op_env, monkeypatch):
    from jarvis.model_routing.operational_budget import _journal

    r = closed_capture(op_env)
    a, b, _ = administration(op_env)
    original = b.audit_result

    def change_capture(**kw):
        original(**kw)
        with op_env.store.work_store.extension_transaction() as c:
            _journal(
                op_env.governor,
                c,
                r.reservation_id,
                "late-event",
                {"kind": "late_numeric_evidence", "count": 2},
            )

    monkeypatch.setattr(b, "audit_result", change_capture)
    with pytest.raises(PaidBudgetDenied, match="changed"):
        acknowledge(a, r.reservation_id)
    assert op_env.governor.status().blocked_reason == "unknown_usage"


def test_acknowledged_capture_does_not_qualify_profile(op_env):
    from jarvis.model_routing.live_budget_admin import resolve_qualified_live_profile

    r = closed_capture(op_env)
    a, _, _ = administration(op_env)
    acknowledge(a, r.reservation_id)
    assert resolve_qualified_live_profile(op_env.runtime, policy=op_env.policy) is None
