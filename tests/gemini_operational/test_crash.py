"""Kill actual updated writers at durable connection boundaries, never providers."""

import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.gemini_live.test_budget import live_env

from jarvis.model_routing.budget import PaidBudgetDenied

from .helpers import policy, profile
from .test_governor import checkpoint, finish, observe, reserve


def _crash_writer(directory, stage, output, hold):
    _, runtime, target, price = live_env(Path(directory))
    env = SimpleNamespace(
        governor=runtime.paid_budget,
        target=target,
        price=price,
        policy=policy(),
        profile=profile(),
    )
    r = reserve(env)
    if stage != "reserved":
        checkpoint(env, r)
    if stage in {"partial", "terminal", "closed"}:
        observe(env, r, tokens=100, complete=stage != "partial")
    if stage == "closed":
        finish(env, r, complete=False)
    output.send(r.reservation_id)
    hold.wait(45)


@pytest.mark.parametrize(
    "stage", ["reserved", "dispatched", "partial", "terminal", "closed"]
)
def test_killed_writer_never_refunds_unconfirmed_paid_exposure(op_env, tmp_path, stage):
    ctx = multiprocessing.get_context("spawn")
    parent, child_end = ctx.Pipe(duplex=False)
    hold = ctx.Event()
    child = ctx.Process(
        target=_crash_writer, args=(str(tmp_path), stage, child_end, hold)
    )
    child.start()
    try:
        assert parent.poll(40), "Child failed before durable checkpoint"
        parent.recv()
        child.terminate()
        child.join(5)
        assert not child.is_alive()
        op_env.governor.recover_operational_live_owners()
        s = op_env.governor.status()
        assert s.unknown_reservations == 1
        assert s.spent_inr_minor + s.reserved_inr_minor == 1000
        with pytest.raises(PaidBudgetDenied):
            reserve(op_env, invocation_id="restart-attempt")
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        parent.close()
        child_end.close()
