import asyncio
import threading

import pytest

from jarvis.model_routing.budget import PaidBudgetDenied


def admission(env, authorize=lambda: True):
    from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission

    return OperationalLiveAdmission(
        env.runtime,
        session_id="original-session",
        authorize=authorize,
        policy=env.policy,
        profile=env.profile,
    )


@pytest.mark.asyncio
async def test_reserve_and_setup_checkpoint_precede_client(op_env):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    b = create_connection_budget(
        admission(op_env), connection_id="c1", target=op_env.target
    )
    await b.reserve_round("r1")
    assert op_env.governor.status().reserved_inr_minor == 1000
    await b.before_send("setup", "setup")
    assert b.reservation.state == "dispatched"
    await b.close(teardown_confirmed=True, complete=False)
    assert op_env.governor.status().unknown_reservations == 1


@pytest.mark.asyncio
async def test_cancel_during_offthread_reserve_refunds_only_unsent(op_env, monkeypatch):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    entered, release = threading.Event(), threading.Event()
    real = op_env.governor.reserve_operational_live

    def slow(**kwargs):
        r = real(**kwargs)
        entered.set()
        release.wait(3)
        return r

    monkeypatch.setattr(op_env.governor, "reserve_operational_live", slow)
    b = create_connection_budget(
        admission(op_env), connection_id="c1", target=op_env.target
    )
    t = asyncio.create_task(b.reserve_round("r1"))
    assert await asyncio.to_thread(entered.wait, 3)
    t.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert op_env.governor.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_authority_or_price_expires_after_await_no_send(op_env):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    current = [True]
    b = create_connection_budget(
        admission(op_env, lambda: current[0]), connection_id="c1", target=op_env.target
    )
    await b.reserve_round("r1")
    current[0] = False
    with pytest.raises(PaidBudgetDenied):
        await b.before_send("setup", "setup")
    await b.close(teardown_confirmed=True, complete=False)
    assert op_env.governor.status().reserved_inr_minor == 0


def test_capture_data_handle_is_not_authorization(op_env):
    from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission

    with pytest.raises(PaidBudgetDenied):
        OperationalLiveAdmission(
            op_env.runtime,
            session_id="x",
            authorize=lambda: True,
            policy=op_env.policy,
            profile=None,
            capture_only=True,
        )
