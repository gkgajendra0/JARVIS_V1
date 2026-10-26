import multiprocessing
from pathlib import Path
from types import SimpleNamespace

from tests.gemini_fallback.helpers import budget_fixture, exposure
from tests.gemini_live.test_budget import live_env

from jarvis.model_routing.budget import PaidBudgetDenied

from .helpers import policy, profile
from .test_governor import checkpoint, reserve


def _contender(directory, name, pipe, start, hold):
    _, runtime, target, price = live_env(Path(directory))
    e = SimpleNamespace(
        governor=runtime.paid_budget,
        target=target,
        price=price,
        policy=policy(),
        profile=profile(),
    )
    pipe.send("ready")
    assert start.wait(40)
    try:
        r = reserve(e, invocation_id=name)
        checkpoint(e, r)
        pipe.send("admitted")
    except PaidBudgetDenied:
        pipe.send("denied")
    assert hold.wait(40)


def test_updated_processes_share_one_live_parent_and_structured_ceiling(
    op_env, tmp_path
):
    _, _, target, price = budget_fixture(op_env.store.work_store.path)
    op_env.governor.reserve(
        invocation_id="durable-work",
        target=target,
        pricing=price,
        exposure=exposure(8500, 8500),
    )
    ctx = multiprocessing.get_context("spawn")
    start, hold = ctx.Event(), ctx.Event()
    children, pipes = [], []
    try:
        for name in ("first", "second"):
            parent, child_end = ctx.Pipe(duplex=False)
            child = ctx.Process(
                target=_contender, args=(str(tmp_path), name, child_end, start, hold)
            )
            children.append(child)
            pipes.extend((parent, child_end))
            child.start()
            assert parent.poll(30) and parent.recv() == "ready"
        start.set()
        outcomes = []
        for pipe in pipes[::2]:
            assert pipe.poll(30)
            outcomes.append(pipe.recv())
        assert sorted(outcomes) == ["admitted", "denied"]
        status = op_env.governor.status()
        assert status.spent_inr_minor + status.reserved_inr_minor == 35000
        hold.set()
        for child in children:
            child.join(10)
            assert child.exitcode == 0
    finally:
        start.set()
        hold.set()
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(5)
        for pipe in pipes:
            pipe.close()
