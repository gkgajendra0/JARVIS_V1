import multiprocessing
from dataclasses import replace

from tests.gemini_fallback.helpers import make_router

from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.model_routing.health import TargetHealthRecord
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind


def pressure(store):
    record = TargetHealthRecord(
        target_id="work.gemini.free.gemini-test",
        state=TargetHealthEligibility.COOLDOWN,
        consecutive_failures=1,
        cooldown_until_epoch=160,
        last_failure_kind="quota_exhausted",
        updated_at_epoch=100,
    )
    store.create_health(record)
    return record.target_id


def test_expired_pressure_not_marked_healthy_by_routing_alone(tmp_path):
    router, store = make_router(tmp_path)
    target = pressure(store)
    state = router._runtime_state(now_epoch=160)
    assert state.target_health[target] is TargetHealthEligibility.HEALTHY
    assert store.get_health(target).state is TargetHealthEligibility.COOLDOWN


def test_no_probe_before_demand_one_lease_and_real_success(tmp_path):
    _, store = make_router(tmp_path)
    target = pressure(store)
    assert (
        store.claim_free_recovery(
            target_id=target, operation_id="early", now_epoch=159, lease_seconds=20
        )
        is None
    )
    lease = store.claim_free_recovery(
        target_id=target, operation_id="actual-demand", now_epoch=160, lease_seconds=20
    )
    assert lease is not None
    assert (
        store.claim_free_recovery(
            target_id=target, operation_id="parallel", now_epoch=160, lease_seconds=20
        )
        is None
    )
    assert store.get_health(target).state is TargetHealthEligibility.COOLDOWN
    assert store.complete_free_recovery(lease, now_epoch=161)
    assert store.get_health(target).state is TargetHealthEligibility.HEALTHY
    assert not store.complete_free_recovery(lease, now_epoch=162)


def test_expired_holder_cannot_release_or_complete_replacement(tmp_path):
    _, store = make_router(tmp_path)
    target = pressure(store)
    old = store.claim_free_recovery(
        target_id=target, operation_id="old", now_epoch=160, lease_seconds=20
    )
    new = store.claim_free_recovery(
        target_id=target, operation_id="new", now_epoch=180, lease_seconds=20
    )
    assert new.version > old.version
    assert not store.release_free_recovery(old)
    assert not store.complete_free_recovery(old, now_epoch=181)
    assert not store.release_free_recovery(replace(new, operation_id="wrong-owner"))
    assert store.release_free_recovery(new)


def test_late_success_cannot_clear_new_pressure(tmp_path):
    router, store = make_router(tmp_path)
    target = pressure(store)
    lease = store.claim_free_recovery(
        target_id=target, operation_id="first", now_epoch=160, lease_seconds=20
    )
    store.record_pressure(
        target=router.target_registry.all()[0],
        failure=ProviderFailure("gemini", ProviderFailureKind.RATE_LIMITED),
        config=GeminiFallbackConfig(enabled=True),
        now_epoch=161,
    )
    assert not store.complete_free_recovery(lease, now_epoch=162)
    assert store.get_health(target).cooldown_until_epoch == 281


def _claim(path, gate, queue, operation):
    from jarvis.model_routing.store import ModelRoutingStore
    from jarvis.work.store import SQLiteWorkStore

    store = ModelRoutingStore(SQLiteWorkStore(path))
    gate.wait(timeout=20)
    lease = store.claim_free_recovery(
        target_id="work.gemini.free.gemini-test",
        operation_id=operation,
        now_epoch=160,
        lease_seconds=20,
    )
    queue.put(lease is not None)


def test_recovery_claim_is_cross_process_exclusive(tmp_path):
    _, store = make_router(tmp_path)
    pressure(store)
    assert callable(getattr(store, "claim_free_recovery", None))
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Barrier(2)
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_claim, args=(str(tmp_path / "routing.db"), gate, queue, str(i))
        )
        for i in range(2)
    ]
    try:
        for proc in processes:
            proc.start()
        values = [queue.get(timeout=30) for _ in processes]
        for proc in processes:
            proc.join(timeout=30)
            assert proc.exitcode == 0
        assert sorted(values) == [False, True]
    finally:
        for proc in processes:
            if proc.is_alive():
                proc.terminate()
                proc.join()
        queue.close()
        queue.join_thread()
