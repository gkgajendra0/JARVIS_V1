from dataclasses import replace

import pytest

from jarvis.model_routing.budget import PaidBudgetDenied

from .test_governor import checkpoint, reserve


def test_orphan_or_pid_reuse_blocks_new_paid(op_env):
    from jarvis.model_routing.process_identity import (
        current_process_identity,
        process_identity_alive,
    )

    p = current_process_identity()
    assert process_identity_alive(p) is True
    assert process_identity_alive(replace(p, started_at=p.started_at - 1)) is False
    r = reserve(op_env)
    checkpoint(op_env, r)
    with op_env.store.work_store.extension_transaction() as c:
        row = c.execute(
            "SELECT operational_json FROM paid_fallback_reservations WHERE reservation_id=?",
            (r.reservation_id,),
        ).fetchone()
        data = op_env.store.work_store.decode_extension_json(row[0])
        data["owner"]["started_at"] -= 1
        c.execute(
            "UPDATE paid_fallback_reservations SET operational_json=? WHERE reservation_id=?",
            (op_env.store.work_store.encode_extension_json(data), r.reservation_id),
        )
    assert op_env.governor.recover_operational_live_owners() == (r.reservation_id,)
    assert op_env.governor.status().unknown_reservations == 1
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="new")


# Spawn imports the test module with a clean interpreter; all money lives in the same SQLite file.
def _reserve_in_process(directory, output):
    from pathlib import Path
    from types import SimpleNamespace

    from tests.gemini_live.test_budget import live_env

    from .helpers import policy, profile

    _, runtime, target, price = live_env(Path(directory))
    env = SimpleNamespace(
        governor=runtime.paid_budget,
        target=target,
        price=price,
        policy=policy(),
        profile=profile(),
    )
    try:
        r = reserve(env, invocation_id="child")
        checkpoint(env, r)
        output.put(("reserved", r.reserved_inr_minor))
    except PaidBudgetDenied:
        output.put(("denied", 0))


def test_real_process_death_retains_hold_and_blocks_structured_and_live(
    op_env, tmp_path
):
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    output = ctx.Queue()
    child = ctx.Process(target=_reserve_in_process, args=(str(tmp_path), output))
    child.start()
    child.join(45)
    if child.is_alive():
        child.terminate()
        child.join(5)
        pytest.fail("Offline reservation child failed to exit")
    assert child.exitcode == 0
    assert output.get(timeout=5) == ("reserved", 1000)
    recovered = op_env.governor.recover_operational_live_owners()
    assert len(recovered) == 1
    assert op_env.governor.status().unknown_reservations == 1
    with pytest.raises(PaidBudgetDenied):
        reserve(op_env, invocation_id="after-crash")
    from tests.gemini_fallback.helpers import budget_fixture, exposure

    _, _, target, price = budget_fixture(op_env.store.work_store.path)
    with pytest.raises(PaidBudgetDenied):
        op_env.governor.reserve(
            invocation_id="structured-after-crash",
            target=target,
            pricing=price,
            exposure=exposure(1, 1),
        )
    output.close()
    output.join_thread()
