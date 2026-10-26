import asyncio
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

import pytest
from tests.gemini_live.test_budget import live_env, reserve
from tests.gemini_live.test_contract import raw_usage

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown


def crash_boundary(root, stage):
    async def run():
        env = live_env(root)
        lease = await reserve(env)
        if stage != "reserved":
            await lease.mark_dispatched()
        if stage == "settled":
            lease.observe("final", raw_usage())
            await lease.finish(complete=True)
        os._exit(17)

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["reserved", "dispatched", "settled"])
def test_controlled_live_process_death_preserves_one_shot_durable_boundary(
    tmp_path, stage
):
    live_env(tmp_path)
    child = multiprocessing.get_context("spawn").Process(
        target=crash_boundary, args=(tmp_path, stage)
    )
    child.start()
    try:
        child.join(30)
        assert child.exitcode == 17
        env = live_env(tmp_path)
        if stage == "reserved":
            lease = asyncio.run(reserve(env))
            asyncio.run(lease.cancel_unsent())
            assert env[1].paid_budget.status().reserved_inr_minor == 0
        else:
            with pytest.raises(PaidOutcomeUnknown):
                asyncio.run(reserve(env))
            status = env[1].paid_budget.status()
            assert status.spent_inr_minor == (1 if stage == "settled" else 0)
            assert status.reserved_inr_minor == (0 if stage == "settled" else 3993)
    finally:
        if child.is_alive():
            child.terminate()
        child.join(10)


def contend_live(args):
    root, trigger = args

    async def run():
        try:
            await reserve(live_env(root), trigger)
        except PaidBudgetDenied:
            return "denied"
        return "admitted"

    return asyncio.run(run())


def test_independent_live_processes_share_remaining_work_ceiling(tmp_path):
    from tests.gemini_fallback.helpers import budget_fixture, exposure

    governor, _, target, price = budget_fixture(tmp_path / "routing.db")
    governor.reserve(
        invocation_id="durable-work", target=target, exposure=exposure(), pricing=price
    )
    live_env(tmp_path)
    with ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn")
    ) as workers:
        results = list(
            workers.map(contend_live, [(tmp_path, str(n)) for n in range(5)])
        )
    assert results.count("admitted") == 3 and results.count("denied") == 2
    assert governor.status().reserved_inr_minor == 31979
