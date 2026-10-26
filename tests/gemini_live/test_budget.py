import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.gemini_fallback.helpers import budget_fixture
from tests.gemini_live.test_contract import raw_usage, synthetic_contract

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.gemini import build_gemini_role_targets
from jarvis.model_routing.pricing import PricingUnavailable
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission


def live_env(tmp_path, *, authorize=lambda: True):
    governor, store, _, base = budget_fixture(tmp_path / "routing.db")
    profile = replace(
        base.profile,
        input_usd_per_million_tokens=None,
        output_usd_per_million_tokens=None,
        usage_rates_usd_per_million=(
            ("input_tokens", 1.0),
            ("input_audio_tokens", 1.0),
            ("output_tokens", 1.0),
            ("output_audio_tokens", 1.0),
        ),
    )
    price = replace(
        base, model_id="gemini-3.8-live", service_key="live", profile=profile
    )
    free, target = build_gemini_role_targets(
        role="voice.live",
        model="gemini-3.8-live",
        adapter_id="gemini",
        config=governor.config,
        cost_profile=profile,
    )
    store.record_pressure(
        target=free,
        failure=ProviderFailure("gemini", ProviderFailureKind.QUOTA_EXHAUSTED),
        config=governor.config,
        now_epoch=100,
    )
    runtime = SimpleNamespace(
        paid_budget=governor,
        store=store,
        config=governor.config,
        clock=lambda: 100,
        pricing_for=lambda _: price,
    )
    admission = ControlledLiveAdmission(
        runtime,
        session_id="canonical-session",
        authorize=authorize,
        contract=synthetic_contract(),
    )
    return admission, runtime, target, price


async def reserve(env, trigger="first"):
    admission, _, target, _ = env
    return await admission.reserve(
        target,
        connection_id="connection-1",
        trigger_id=trigger,
        exposure=admission.contract.exposure("canonical-session"),
    )


@pytest.mark.asyncio
async def test_live_reserves_shared_governor_before_dispatch_and_settles_once(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    assert env[1].paid_budget.status().reserved_inr_minor == 3993
    assert not lease.allow_frame(samples=320, sample_rate=16000)
    await lease.mark_dispatched()
    assert lease.allow_frame(samples=320, sample_rate=16000)
    lease.observe("usage-1", raw_usage())
    lease.observe("usage-1", raw_usage())
    assert env[1].paid_budget.status().reserved_inr_minor == 3993
    await lease.finish(complete=True)
    assert env[1].paid_budget.status().spent_inr_minor == 1
    assert env[1].paid_budget.status().reserved_inr_minor == 0
    await lease.finish(complete=True)
    assert env[1].paid_budget.status().spent_inr_minor == 1
    assert not lease.allow_frame(samples=320, sample_rate=16000)


@pytest.mark.asyncio
async def test_concurrent_same_live_trigger_has_one_durable_dispatch(tmp_path):
    env = live_env(tmp_path)
    first, second = await asyncio.gather(reserve(env), reserve(env))
    results = await asyncio.gather(
        first.mark_dispatched(), second.mark_dispatched(), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert any(isinstance(r, PaidOutcomeUnknown) for r in results)
    with pytest.raises(PaidOutcomeUnknown):
        await reserve(env)


@pytest.mark.asyncio
async def test_unknown_usage_goaway_holds_exposure_and_blocks_new_paid(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    await lease.mark_dispatched()
    partial = raw_usage()
    partial.pop("thoughts_token_count")
    lease.observe("partial", partial)
    await lease.finish(complete=False)
    status = env[1].paid_budget.status()
    assert status.unknown_reservations == 1 and status.reserved_inr_minor == 3993
    assert status.blocked_reason == "unknown_usage"
    with pytest.raises(PaidBudgetDenied):
        await reserve(env, "next")
    with pytest.raises(PaidOutcomeUnknown):
        await lease.cancel_unsent()


@pytest.mark.asyncio
async def test_proven_unsent_is_only_refund_and_audio_limits_are_local(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    await lease.cancel_unsent()
    assert env[1].paid_budget.status().reserved_inr_minor == 0
    with pytest.raises(PaidOutcomeUnknown):
        await lease.mark_dispatched()
    next_lease = await reserve(env, "next")
    await next_lease.mark_dispatched()
    assert not next_lease.allow_frame(samples=1, sample_rate=48000)
    assert next_lease.allow_frame(samples=480000, sample_rate=16000)
    assert not next_lease.allow_frame(samples=1, sample_rate=16000)
    env[1].clock = lambda: 161
    assert not next_lease.allow_frame(samples=1, sample_rate=16000)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["price", "dimension", "pressure", "credential"])
async def test_invalid_pricing_or_nonquota_target_never_admitted(tmp_path, failure):
    env = live_env(tmp_path)
    _admission, runtime, target, price = env
    if failure == "price":
        runtime.pricing_for = lambda _: None
    if failure == "dimension":
        bad = replace(
            price,
            profile=replace(
                price.profile, usage_rates_usd_per_million=(("input_tokens", 1.0),)
            ),
        )
        runtime.pricing_for = lambda _: bad
    if failure == "pressure":
        old = runtime.store.get_health(target.target_id.replace(".paid.", ".free."))
        runtime.store.save_health(
            old.recovered(now_epoch=101), expected_version=old.version
        )
    if failure == "credential":
        runtime.store.disable_paid_credential(
            failure=ProviderFailure(
                "gemini", ProviderFailureKind.AUTHENTICATION_FAILED
            ),
            now_epoch=100,
        )
    with pytest.raises((PaidBudgetDenied, PricingUnavailable)):
        await reserve(env)
    assert runtime.paid_budget.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_source_revoked_during_transaction_is_cancelled_unsent(
    tmp_path, monkeypatch
):
    valid = [True]
    env = live_env(tmp_path, authorize=lambda: valid[0])
    original = env[1].paid_budget.reserve

    def revoked(**kwargs):
        result = original(**kwargs)
        valid[0] = False
        return result

    monkeypatch.setattr(env[1].paid_budget, "reserve", revoked)
    with pytest.raises(PaidBudgetDenied):
        await reserve(env)
    assert env[1].paid_budget.status().reserved_inr_minor == 0
    assert env[1].paid_budget.status().spent_inr_minor == 0


@pytest.mark.asyncio
async def test_cancelled_reserve_waits_for_transaction_then_refunds_unsent(
    tmp_path, monkeypatch
):
    env = live_env(tmp_path)
    gate = threading.Event()
    entered = threading.Event()
    original = env[1].paid_budget.reserve

    def delayed(**kwargs):
        result = original(**kwargs)
        entered.set()
        assert gate.wait(timeout=10)
        return result

    monkeypatch.setattr(env[1].paid_budget, "reserve", delayed)
    task = asyncio.create_task(reserve(env))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        task.cancel()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert env[1].paid_budget.status().reserved_inr_minor == 0
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_whole_envelope_and_original_session_cannot_be_replaced(tmp_path):
    env = live_env(tmp_path)
    admission, _, target, _ = env
    wrong = admission.contract.exposure("other-session")
    with pytest.raises(PaidBudgetDenied):
        await admission.reserve(
            target, connection_id="c", trigger_id="t", exposure=wrong
        )
    bound = admission.contract.exposure("canonical-session")
    tiny = replace(bound, usage_bounds={"input_tokens": 1, "output_tokens": 1})
    with pytest.raises(PaidBudgetDenied):
        await admission.reserve(
            target, connection_id="c", trigger_id="t", exposure=tiny
        )


@pytest.mark.asyncio
async def test_regressing_or_colliding_usage_keeps_unknown(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    await lease.mark_dispatched()
    lease.observe("same", raw_usage())
    reduced = raw_usage()
    reduced.update(response_token_count=29, total_token_count=53)
    reduced["response_tokens_details"][0]["token_count"] = 9
    lease.observe("same", reduced)
    await lease.finish(complete=True)
    assert env[1].paid_budget.status().unknown_reservations == 1


@pytest.mark.asyncio
async def test_same_trigger_cannot_change_reviewed_contract_after_restart(tmp_path):
    env = live_env(tmp_path)
    await reserve(env)
    contract = env[0].contract
    changed = replace(
        contract, auxiliary_bounds=replace(contract.auxiliary_bounds, version=2)
    )
    restarted = ControlledLiveAdmission(
        env[1], session_id="canonical-session", authorize=lambda: True, contract=changed
    )
    with pytest.raises(PaidBudgetDenied):
        await restarted.reserve(
            env[2],
            connection_id="connection-1",
            trigger_id="first",
            exposure=changed.exposure("canonical-session"),
        )
    assert env[1].paid_budget.status().reserved_inr_minor == 3993


@pytest.mark.asyncio
async def test_expired_reservation_cannot_open_a_late_paid_connection(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    env[1].clock = lambda: 161
    with pytest.raises(PaidBudgetDenied):
        await lease.mark_dispatched()
    assert env[1].paid_budget.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_cancelled_finalization_waits_for_commit_and_closes_frame_permit(
    tmp_path, monkeypatch
):
    env = live_env(tmp_path)
    lease = await reserve(env)
    await lease.mark_dispatched()
    lease.observe("final", raw_usage())
    gate = threading.Event()
    entered = threading.Event()
    original = env[1].paid_budget.settle

    def delayed(**kwargs):
        entered.set()
        assert gate.wait(timeout=10)
        return original(**kwargs)

    monkeypatch.setattr(env[1].paid_budget, "settle", delayed)
    task = asyncio.create_task(lease.finish(complete=True))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert not lease.allow_frame(samples=320, sample_rate=16000)
        task.cancel()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lease.allow_frame(samples=320, sample_rate=16000)
        await lease.finish(complete=True)
        assert env[1].paid_budget.status().spent_inr_minor == 1
    finally:
        gate.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["work", "hands", "memory"])
async def test_live_uses_remaining_shared_ceiling_after_other_lane(tmp_path, scope):
    from jarvis.model_routing.pricing import PaidExposure

    env = live_env(tmp_path)
    governor, _, target, price = budget_fixture(tmp_path / "routing.db")
    governor.reserve(
        invocation_id="other-lane",
        target=target,
        exposure=PaidExposure(
            usage_bounds={"input_tokens": 5000, "output_tokens": 5000},
            scope_kind=scope,
            scope_id="original-operation",
        ),
        pricing=price,
    )
    for n in range(3):
        await reserve(env, str(n))
    assert governor.status().reserved_inr_minor == 31979
    with pytest.raises(PaidBudgetDenied):
        await reserve(env, "over-ceiling")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled-target", "target-cooldown"])
async def test_paid_target_health_cannot_be_bypassed_by_direct_admission(
    tmp_path, change
):
    from jarvis.model_routing.eligibility import TargetHealthEligibility
    from jarvis.model_routing.health import TargetHealthRecord

    env = live_env(tmp_path)
    if change == "disabled-target":
        env = (*env[:2], replace(env[2], enabled=False), env[3])
    else:
        env[1].store.create_health(
            TargetHealthRecord(
                env[2].target_id,
                state=TargetHealthEligibility.COOLDOWN,
                cooldown_until_epoch=130,
                last_failure_kind="service_unavailable",
                updated_at_epoch=100,
            )
        )
    with pytest.raises(PaidBudgetDenied):
        await reserve(env)
    assert env[1].paid_budget.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_auth_block_during_reserved_wait_prevents_dispatch(tmp_path):
    env = live_env(tmp_path)
    lease = await reserve(env)
    env[1].store.disable_paid_credential(
        failure=ProviderFailure("gemini", ProviderFailureKind.AUTHENTICATION_FAILED),
        now_epoch=100,
    )
    with pytest.raises(PaidBudgetDenied):
        await lease.mark_dispatched()
    assert env[1].paid_budget.status().reserved_inr_minor == 0
