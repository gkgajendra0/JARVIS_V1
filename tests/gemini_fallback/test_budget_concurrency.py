import multiprocessing

from .helpers import budget_fixture, exposure


def _reserve_worker(path, barrier, results):
    from jarvis.model_routing.budget import PaidBudgetDenied

    governor, _, target, price = budget_fixture(path)
    barrier.wait(timeout=30)
    try:
        governor.reserve(
            invocation_id=str(multiprocessing.current_process().pid),
            target=target,
            exposure=exposure(),
            pricing=price,
        )
        results.put("reserved")
    except PaidBudgetDenied:
        results.put("denied")


def test_real_processes_cannot_overspend_shared_ceiling(tmp_path):
    path = tmp_path / "cost.db"
    budget_fixture(path)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    children = [
        ctx.Process(target=_reserve_worker, args=(path, barrier, results))
        for _ in range(2)
    ]
    for child in children:
        child.start()
    try:
        outcomes = [results.get(timeout=45) for _ in children]
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
        assert sorted(outcomes) == ["denied", "reserved"]
        governor, _, _, _ = budget_fixture(path)
        assert governor.status().reserved_inr_minor == 20000
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
        results.close()
