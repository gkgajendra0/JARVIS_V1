import pytest

from .helpers import usage
from .test_admission import admission


@pytest.mark.asyncio
async def test_two_tools_share_one_allowance_but_three_permits(op_env):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    b = create_connection_budget(
        admission(op_env), connection_id="c1", target=op_env.target
    )
    await b.reserve_round("r1")
    await b.before_send("setup", "setup")
    await b.before_send("initial", "initial")
    for i in (1, 2, 3):
        await b.observe(
            str(i), usage(), sequence=i, turn_complete=True, last_output_sequence=i
        )
        await b.finish_round("r" + str(i), complete=True)
        if i < 3:
            await b.reserve_round("r" + str(i + 1))
            await b.before_send(
                "tool", "tool" + str(i), tool_call_ids=("call" + str(i),)
            )
    assert op_env.governor.status().spent_inr_minor == 1
    assert op_env.governor.status().reserved_inr_minor == 999
    from jarvis.model_routing.budget import PaidBudgetDenied

    with pytest.raises(PaidBudgetDenied):
        await b.reserve_round("r4")
        await b.before_send("tool", "tool3", tool_call_ids=("call3",))
    await b.close(teardown_confirmed=True, complete=True)
    assert op_env.governor.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_frame_path_does_no_disk_work(op_env, monkeypatch):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    b = create_connection_budget(
        admission(op_env), connection_id="c1", target=op_env.target
    )
    await b.reserve_round("r1")
    await b.before_send("setup", "setup")
    await b.before_send("initial", "initial")

    def denied(*a, **k):
        raise AssertionError("frame path did I/O")

    with monkeypatch.context() as m:
        m.setattr(op_env.store.work_store, "extension_transaction", denied)
        for _ in range(1000):
            assert b.allow_frame(samples=320, sample_rate=16000)
        assert not b.allow_frame(samples=1, sample_rate=16000)
    await b.close(teardown_confirmed=True, complete=False)


@pytest.mark.asyncio
async def test_strict_lifecycle_keeps_existing_reservations(tmp_path):
    from tests.gemini_live.test_budget import live_env
    from tests.gemini_live.test_contract import raw_usage

    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    a, r, t, _ = live_env(tmp_path)
    b = create_connection_budget(a, connection_id="strict-c", target=t)
    await b.reserve_round("r1")
    await b.before_send("setup", "setup")
    assert r.paid_budget.status().reserved_inr_minor == 3993
    await b.observe(
        "usage", raw_usage(), sequence=1, turn_complete=True, last_output_sequence=1
    )
    await b.finish_round("r1", complete=True)
    assert r.paid_budget.status().reserved_inr_minor == 0
