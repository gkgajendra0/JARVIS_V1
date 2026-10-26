"""Regressions for observable failures found by the whole-branch review."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import google.genai
import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.helpers import budget_fixture, exposure
from tests.gemini_fallback.test_hands_memory import response, shared


@pytest.mark.asyncio
@pytest.mark.parametrize("forget_at", ["free", "paid", None])
async def test_forgotten_canonical_fact_never_released_again(
    tmp_path, monkeypatch, forget_at
):
    from tests.test_memory_query_coordinator import (
        BASE,
        StaticInterpreter,
        _draft,
        _exact,
        _source,
        _worker,
    )

    from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
    from jarvis.memory.lifecycle import MemoryLifecycleService
    from jarvis.memory.provider_verified_query import (
        ProviderVerifiedMemoryQueryCoordinator,
    )
    from jarvis.memory.query_coordinator import MemoryQueryCoordinator
    from jarvis.memory.release_guard import build_memory_release_guard
    from jarvis.memory.retrieval import SemanticRetrievalService

    runtime, _env = shared(tmp_path, monkeypatch, {})
    worker = _worker(tmp_path / "canonical.db")
    lifecycle = MemoryLifecycleService(worker, clock=lambda: BASE)
    released = []
    record = await lifecycle.create(
        _draft(
            subject="Aquila", predicate="archive_destination", value="private-vault-A"
        ),
        _source("owner"),
    )

    def client(**kwargs):
        key = kwargs["api_key"]

        async def create(**request):
            released.append((key, request["input"]))
            if forget_at is not None and key.startswith(forget_at):
                assert await lifecycle.forget(record.assertion_id, _source("forget"))
            if key.startswith("free"):
                raise APIError(429, {})
            return SimpleNamespace(
                **response({"answer_type": "current_value", "directly_supported": True})
            )

        return SimpleNamespace(
            aio=SimpleNamespace(
                interactions=SimpleNamespace(
                    create=create, sdk_configuration=SimpleNamespace(retry_config=None)
                )
            )
        )

    monkeypatch.setattr(google.genai, "Client", client)
    core = MemoryQueryCoordinator(
        interpreter=StaticInterpreter(_exact()),
        retrieval=SemanticRetrievalService(worker),
    )
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=build_memory_release_guard(
            provider="gemini", model="gemini-budget-test", routing_runtime=runtime
        ),
    )
    try:
        result = await coordinator.resolve("Aquila ka archive destination kya hai?")
        if forget_at is None:
            assert result.disposition is MemoryEvidenceDisposition.RELEASE
            assert result.evidence.assertion.value == "private-vault-A"
        else:
            assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
            assert result.evidence is None
        assert [key for key, _ in released] == (
            ["free-private-canary"]
            if forget_at == "free"
            else ["free-private-canary", "paid-private-canary"]
        )
    finally:
        await worker.close()


@pytest.mark.parametrize(
    "rates",
    [(("input_tokens", 0.0),), (("input_tokens", 2.0),), (("output_tokens", 2.0),)],
)
def test_incomplete_structured_price_never_admits_or_settles_free(tmp_path, rates):
    from jarvis.model_routing.pricing import PricingUnavailable

    governor, _, target, price = budget_fixture(tmp_path / "price.db")
    profile = replace(
        price.profile,
        input_usd_per_million_tokens=None,
        output_usd_per_million_tokens=None,
        usage_rates_usd_per_million=rates,
    )
    price = replace(price, profile=profile)
    target = replace(target, cost_profile=profile)
    with pytest.raises(PricingUnavailable):
        governor.reserve(
            invocation_id="missing-output-price",
            target=target,
            exposure=exposure(),
            pricing=price,
        )
    with pytest.raises(PricingUnavailable):
        price.quote_usage({"input_tokens": 5000, "output_tokens": 5000}, now_epoch=100)
    assert governor.status().reserved_inr_minor == 0


@pytest.mark.parametrize(
    "metadata", [{"quota_period": "day"}, {"retry_after_seconds": 600.0}]
)
def test_later_ordinary_pressure_cannot_shorten_verified_deadline(metadata):
    from jarvis.model_routing.gemini import GeminiFallbackConfig
    from jarvis.model_routing.health import TargetHealthRecord, apply_gemini_pressure
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

    config = GeminiFallbackConfig(enabled=True)
    first = apply_gemini_pressure(
        TargetHealthRecord("work.gemini.free.test"),
        ProviderFailure("gemini", ProviderFailureKind.QUOTA_EXHAUSTED, **metadata),
        config=config,
        now_epoch=100,
    )
    later = apply_gemini_pressure(
        first,
        ProviderFailure("gemini", ProviderFailureKind.RATE_LIMITED),
        config=config,
        now_epoch=101,
    )
    assert later.cooldown_until_epoch >= first.cooldown_until_epoch


@pytest.mark.asyncio
async def test_work_engine_bookkeeping_cannot_repeat_unknown_paid_call(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.test_work_resume import output, work_environment

    from jarvis.model_routing.registry import ModelTargetRegistry
    from jarvis.work.brain import BrainCoordinator
    from jarvis.work.engine import WorkActionRegistry, WorkEngine
    from jarvis.work.models import WorkState, WorkType

    class PowerLoss(BaseException):
        pass

    env, router, reasoner, request = work_environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [output(), output()],
        },
    )
    # Two requests would fit; a budget denial must not hide duplicate dispatch.
    profile = replace(
        env[0].pricing.profile,
        input_usd_per_million_tokens=1,
        output_usd_per_million_tokens=1,
    )
    env[0].pricing = replace(env[0].pricing, profile=profile)
    router.target_registry = ModelTargetRegistry(
        router.adapter_registry,
        tuple(
            replace(t, cost_profile=profile) if t.cost_profile else t
            for t in router.target_registry.all()
        ),
    )

    class NoEffect:
        descriptor = request.allowed_actions[0]
        work_types = frozenset({WorkType.GENERIC})

        async def execute(self, **kwargs):
            raise AssertionError("No action should execute")

    engine = WorkEngine(
        store=router.routing_store.work_store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((NoEffect(),)),
        context_mode="off",
    )
    settle = env[2].settle

    def lost(**kwargs):
        raise PowerLoss()

    monkeypatch.setattr(env[2], "settle", lost)
    with pytest.raises(PowerLoss):
        await engine.advance(request.work.work_id)
    monkeypatch.setattr(env[2], "settle", settle)
    await engine.advance(request.work.work_id)
    assert any(
        s.kind == "routing_resource_blocker"
        for s in router.routing_store.work_store.list_steps(request.work.work_id)
    )
    result = await engine.advance(request.work.work_id)
    assert result.state is WorkState.WAITING_RESOURCE
    assert [key for key, _, _ in env[3]].count("paid-private-canary") == 1
    with router.routing_store.work_store.extension_transaction() as connection:
        states = [
            r[0]
            for r in connection.execute("SELECT state FROM paid_fallback_reservations")
        ]
    assert states == ["dispatched"]


@pytest.mark.asyncio
async def test_slow_free_recovery_keeps_one_inflight_owner_past_lease(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.helpers import scoped_request
    from tests.gemini_fallback.test_invocation import Answer, environment

    from jarvis.model_routing.eligibility import TargetHealthEligibility
    from jarvis.model_routing.health import TargetHealthRecord

    now = [160]
    gate = asyncio.Event()
    env = environment(
        tmp_path, monkeypatch, {"free-private-canary": [gate]}, clock=lambda: now[0]
    )
    free = env[1].target_registry.all()[0]
    env[1].routing_store.create_health(
        TargetHealthRecord(
            free.target_id,
            state=TargetHealthEligibility.COOLDOWN,
            consecutive_failures=1,
            cooldown_until_epoch=160,
            last_failure_kind="quota_exhausted",
            updated_at_epoch=100,
        )
    )

    async def call(identity):
        return await env[0].invoke_scoped_structured(
            router=env[1],
            request=scoped_request(
                routing_request_id=identity, scope_id="source-budget"
            ),
            system_prompt="answer",
            input_payload={"question": "fictional"},
            response_model=Answer,
            exposure=exposure(),
        )

    first = asyncio.create_task(call("first-demand"))
    try:
        for _ in range(100):
            if env[3]:
                break
            await asyncio.sleep(0)
        assert len(env[3]) == 1
        now[0] = 221
        second = await call("parallel-demand")
        assert second.parsed.answer == "ok"
        assert [key for key, _, _ in env[3]] == [
            "free-private-canary",
            "paid-private-canary",
        ]
    finally:
        gate.set()
        await first


@pytest.mark.parametrize(
    "error",
    [APIError(503, {}), TimeoutError("timeout"), ConnectionError("connection lost")],
)
def test_scoped_transient_free_error_retries_same_target_within_policy(
    tmp_path, monkeypatch, error
):
    from tests.gemini_fallback.test_invocation import environment, invoke

    env = environment(tmp_path, monkeypatch, {"free-private-canary": [error, "ok"]})
    result = invoke(env)
    assert result.parsed.answer == "ok"
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "free-private-canary",
    ]
    with env[1].routing_store.work_store.extension_transaction() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM model_scoped_routing_attempts"
            ).fetchone()[0]
            == 2
        )
    assert env[2].status().spent_inr_minor == 0


def _recovery_process(path, ready, done):
    from jarvis.model_routing.store import ModelRoutingStore
    from jarvis.work.store import SQLiteWorkStore

    store = ModelRoutingStore(SQLiteWorkStore(path))
    lease = store.claim_free_recovery(
        target_id="work.gemini.free.gemini-test",
        operation_id="child",
        now_epoch=160,
        lease_seconds=20,
    )
    assert store.start_free_recovery(lease, now_epoch=160)
    ready.set()
    done.wait(timeout=30)


def test_recovery_owner_survives_ttl_but_dead_process_does_not_strand_free(tmp_path):
    import multiprocessing

    from tests.gemini_fallback.helpers import make_router
    from tests.gemini_fallback.test_free_recovery import pressure

    _, store = make_router(tmp_path)
    target = pressure(store)
    ctx = multiprocessing.get_context("spawn")
    ready, done = ctx.Event(), ctx.Event()
    process = ctx.Process(
        target=_recovery_process, args=(str(tmp_path / "routing.db"), ready, done)
    )
    try:
        process.start()
        assert ready.wait(timeout=20)
        assert (
            store.claim_free_recovery(
                target_id=target,
                operation_id="parallel",
                now_epoch=181,
                lease_seconds=20,
            )
            is None
        )
        done.set()
        process.join(timeout=20)
        assert process.exitcode == 0
        recovered = store.claim_free_recovery(
            target_id=target,
            operation_id="after-death",
            now_epoch=181,
            lease_seconds=20,
        )
        assert recovered is not None
        assert store.start_free_recovery(recovered, now_epoch=181)
        assert store.complete_free_recovery(recovered, now_epoch=250)
        assert store.get_health(target).state.value == "healthy"
    finally:
        done.set()
        if process.is_alive():
            process.terminate()
            process.join()


@pytest.mark.asyncio
async def test_cancelled_work_recovery_releases_inflight_owner(tmp_path, monkeypatch):
    from tests.gemini_fallback.test_work_resume import work_environment

    from jarvis.model_routing.eligibility import TargetHealthEligibility
    from jarvis.model_routing.health import TargetHealthRecord

    gate = asyncio.Event()
    env, router, reasoner, request = work_environment(
        tmp_path, monkeypatch, {"free-private-canary": [gate]}
    )
    env[0]._clock = router._clock = reasoner._clock = lambda: 160
    free = router.target_registry.all()[0]
    router.routing_store.create_health(
        TargetHealthRecord(
            free.target_id,
            state=TargetHealthEligibility.COOLDOWN,
            consecutive_failures=1,
            cooldown_until_epoch=160,
            last_failure_kind="quota_exhausted",
            updated_at_epoch=100,
        )
    )
    task = asyncio.create_task(reasoner.decide(request))
    for _ in range(100):
        if env[3]:
            break
        await asyncio.sleep(0)
    assert len(env[3]) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (
        router.routing_store.claim_free_recovery(
            target_id=free.target_id,
            operation_id="next-owner",
            now_epoch=221,
            lease_seconds=20,
        )
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["close", "new-turn"])
async def test_recall_tool_rechecks_original_session_before_paid_release(
    tmp_path, monkeypatch, change
):
    from tests.test_memory_query_coordinator import (
        BASE,
        StaticInterpreter,
        _draft,
        _exact,
        _source,
        _worker,
    )

    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.memory.lifecycle import MemoryLifecycleService
    from jarvis.memory.provider_verified_query import (
        ProviderVerifiedMemoryQueryCoordinator,
    )
    from jarvis.memory.query import CanonicalMemoryReader
    from jarvis.memory.query_coordinator import MemoryQueryCoordinator
    from jarvis.memory.release_guard import build_memory_release_guard
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.memory.service import MemoryService
    from jarvis.voice.memory_tools import MemoryAgentTools

    runtime, _env = shared(tmp_path, monkeypatch, {})
    worker = _worker(tmp_path / "session-canonical.db")
    lifecycle = MemoryLifecycleService(worker, clock=lambda: BASE)
    await lifecycle.create(
        _draft(
            subject="Aquila", predicate="archive_destination", value="private-vault"
        ),
        _source("owner"),
    )
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(
        ConversationRole.USER, "Aquila ka archive destination kya hai?"
    )
    released = []

    def client(**kwargs):
        key = kwargs["api_key"]

        async def create(**request):
            released.append(key)
            if key.startswith("free"):
                if change == "close":
                    conversation.close()
                else:
                    conversation.accept_turn(
                        ConversationRole.USER, "Ab chhodo, doosra kaam karo"
                    )
                raise APIError(429, {})
            return SimpleNamespace(
                **response({"answer_type": "current_value", "directly_supported": True})
            )

        return SimpleNamespace(
            aio=SimpleNamespace(
                interactions=SimpleNamespace(
                    create=create, sdk_configuration=SimpleNamespace(retry_config=None)
                )
            )
        )

    monkeypatch.setattr(google.genai, "Client", client)
    core = MemoryQueryCoordinator(
        interpreter=StaticInterpreter(_exact()),
        retrieval=SemanticRetrievalService(worker),
    )
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=build_memory_release_guard(
            provider="gemini", model="gemini-budget-test", routing_runtime=runtime
        ),
    )
    tool = MemoryAgentTools(
        MemoryService(lifecycle, CanonicalMemoryReader(worker)),
        conversation,
        semantic_query_coordinator=coordinator,
    )
    try:
        result = await tool.semantic_recall()
        assert result["ok"] is False
        assert released == ["free-private-canary"]
        assert runtime.paid_budget.status().spent_inr_minor == 0
    finally:
        await worker.close()
