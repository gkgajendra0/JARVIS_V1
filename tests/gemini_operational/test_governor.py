from dataclasses import replace

import pytest

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.live_policy import LiveUsageReport


def reserve(env, **changes):
    args = {
        "invocation_id": "op-first",
        "target": env.target,
        "pricing": env.price,
        "policy": env.policy,
        "profile": env.profile,
        "scope_id": "original-demand",
    }
    args.update(changes)
    return env.governor.reserve_operational_live(**args)


def checkpoint(env, r, kind="initial", round_id="r1", trigger="initial"):
    return env.governor.checkpoint_operational_live(
        reservation_id=r.reservation_id,
        trigger_id=trigger,
        kind=kind,
        round_id=round_id,
        tool_call_ids=("call-1",) if kind == "tool" else (),
    )


def report(env, tokens=100, *, complete=True, sequence=2, round_id="r1"):
    return LiveUsageReport(
        round_id,
        sequence,
        {
            "input_tokens": tokens,
            "input_audio_tokens": 0,
            "output_tokens": 0,
            "output_audio_tokens": 0,
        },
        complete,
        env.profile.fingerprint,
        complete,
        1,
    )


def observe(env, r, **changes):
    return env.governor.observe_operational_live(
        reservation_id=r.reservation_id,
        report=report(env, **changes),
        event_id="usage-" + str(changes.get("sequence", 2)),
    )


def finish(env, r, **changes):
    args = {
        "reservation_id": r.reservation_id,
        "complete": True,
        "teardown_confirmed": True,
        "event_id": "close",
    }
    args.update(changes)
    return env.governor.finish_operational_live(**args)


def test_operational_hold_shares_ceiling_with_structured_calls(op_env):
    from tests.gemini_fallback.helpers import budget_fixture, exposure

    # Independent structured target, same actual store.
    _, _, target, price = budget_fixture(op_env.store.work_store.path)
    op_env.governor.reserve(
        invocation_id="structured",
        target=target,
        exposure=exposure(8500, 8500),
        pricing=price,
    )
    r = reserve(op_env)
    assert r.reserved_inr_minor == 1000
    s = op_env.governor.status()
    assert s.spent_inr_minor + s.reserved_inr_minor == 35000
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="another")


def test_one_physical_parent_even_when_money_remains(op_env):
    reserve(op_env)
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="another")


def test_round_checkpoints_cannot_duplicate_or_reset(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    with pytest.raises(PaidOutcomeUnknown):
        checkpoint(op_env, r)
    with pytest.raises(PaidBudgetDenied):
        checkpoint(op_env, r, kind="tool", round_id="r2", trigger="tool1")
    observe(op_env, r)
    checkpoint(op_env, r, kind="tool", round_id="r2", trigger="tool1")
    assert op_env.governor.status().reserved_inr_minor == 999


def test_partial_observation_keeps_allocation_constant(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    o = observe(op_env, r, tokens=85000, complete=False)
    assert (o.known_minor, o.held_minor, o.stop_required) == (850, 150, True)
    s = op_env.governor.status()
    assert s.spent_inr_minor + s.reserved_inr_minor == 1000
    assert s.estimated_total_inr_minor is None
    with pytest.raises(PaidBudgetDenied):
        checkpoint(op_env, r, kind="tool", round_id="r2", trigger="tool1")


def test_complete_usage_releases_only_after_confirmed_close(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    observe(op_env, r)
    assert op_env.governor.status().reserved_inr_minor == 999
    finish(op_env, r)
    finish(op_env, r)
    assert op_env.governor.status().spent_inr_minor == 1
    assert op_env.governor.status().reserved_inr_minor == 0


@pytest.mark.parametrize(
    "changes", [{"teardown_confirmed": False}, {"complete": False}]
)
def test_incomplete_close_keeps_unknown_hold(op_env, changes):
    r = reserve(op_env)
    checkpoint(op_env, r)
    observe(op_env, r)
    finish(op_env, r, **changes)
    s = op_env.governor.status()
    assert (
        s.unknown_reservations,
        s.reserved_inr_minor,
        s.estimated_total_inr_minor,
    ) == (1, 999, None)
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="other")


def test_overrun_is_not_clipped(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    o = observe(op_env, r, tokens=4000000)
    assert o.known_minor == 40000 and o.stop_required
    finish(op_env, r)
    assert op_env.governor.status().spent_inr_minor == 40000
    assert op_env.governor.status().blocked_reason == "observed_overrun"


def test_duplicate_observation_is_idempotent_but_collision_denied(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    observe(op_env, r)
    observe(op_env, r)
    assert op_env.governor.status().spent_inr_minor == 1
    with pytest.raises(PaidBudgetDenied):
        observe(op_env, r, tokens=200)


def test_regression_marks_unknown_without_reducing_accounting(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    observe(op_env, r, tokens=300)
    o = observe(op_env, r, tokens=200, sequence=3)
    assert o.unknown_reason is not None
    assert op_env.governor.status().spent_inr_minor == 3
    assert op_env.governor.status().unknown_reservations == 1


def test_two_rounds_aggregate_once_without_extra_allowance(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    observe(op_env, r)
    checkpoint(op_env, r, kind="tool", round_id="r2", trigger="tool1")
    observe(op_env, r, tokens=150, sequence=3, round_id="r2")
    finish(op_env, r)
    assert (
        op_env.governor.status().spent_inr_minor == 3
    )  # ceil(2.5), not separately rounded


def test_strict_settle_cannot_release_operational_parent(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    with pytest.raises(PaidBudgetDenied):
        op_env.governor.settle(
            reservation_id=r.reservation_id,
            usage={
                "input_tokens": 0,
                "input_audio_tokens": 0,
                "output_tokens": 0,
                "output_audio_tokens": 0,
            },
            usage_complete=True,
            event_id="forged-strict",
        )


def test_replayed_invocation_cannot_change_policy_or_scope(op_env):
    reserve(op_env)
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, scope_id="different")
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, policy=replace(op_env.policy, provenance="changed"))
