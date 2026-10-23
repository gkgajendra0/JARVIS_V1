import asyncio

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.helpers import exposure, scoped_request
from tests.gemini_fallback.test_invocation import Answer, environment, invoke

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.invoker import ModelInvocationContext


def test_repeated_scoped_request_is_not_dispatched_again(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch, {})
    invoke(env)
    with pytest.raises(PaidOutcomeUnknown):
        invoke(env)
    assert len(env[3]) == 1


def test_cancelled_paid_call_holds_reservation_and_blocks_replay(tmp_path, monkeypatch):
    async def run():
        waiting = asyncio.Event()
        env = environment(
            tmp_path,
            monkeypatch,
            {
                "free-private-canary": [APIError(429, {})],
                "paid-private-canary": [waiting],
            },
        )
        task = asyncio.create_task(
            env[0].invoke_scoped_structured(
                router=env[1],
                request=scoped_request(scope_id="source-budget"),
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                exposure=exposure(),
            )
        )
        for _ in range(100):
            if len(env[3]) == 2:
                break
            await asyncio.sleep(0)
        assert len(env[3]) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert env[2].status().unknown_reservations == 1
        assert env[2].status().reserved_inr_minor == 20000
        with pytest.raises(PaidOutcomeUnknown):
            await env[0].invoke_scoped_structured(
                router=env[1],
                request=scoped_request(scope_id="source-budget"),
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                exposure=exposure(),
            )
        assert len(env[3]) == 2

    asyncio.run(run())


def test_concurrent_same_source_has_one_real_dispatch(tmp_path, monkeypatch):
    async def run():
        waiting = asyncio.Event()
        env = environment(tmp_path, monkeypatch, {"free-private-canary": [waiting]})

        async def call():
            return await env[0].invoke_scoped_structured(
                router=env[1],
                request=scoped_request(scope_id="source-budget"),
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                exposure=exposure(),
            )

        first = asyncio.create_task(call())
        for _ in range(100):
            if env[3]:
                break
            await asyncio.sleep(0)
        with pytest.raises(PaidOutcomeUnknown):
            await call()
        waiting.set()
        assert (await first).parsed.answer == "ok"
        assert len(env[3]) == 1

    asyncio.run(run())


def test_direct_work_invocation_cannot_bypass_paid_governor(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch, {})
    target = env[1].target_registry.all()[1]
    context = ModelInvocationContext(
        work_id="work-1",
        routing_request_id="request-1",
        decision_id="decision-1",
        attempt_id="attempt-1",
        correlation_key="correlation-1",
    )
    with pytest.raises(PaidBudgetDenied):
        asyncio.run(
            env[0].invoke_structured(
                target=target,
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                request_context=context,
            )
        )
    assert len(env[3]) == 0


def test_scope_and_exposure_identity_must_match(tmp_path, monkeypatch):
    env = environment(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(429, {})]}
    )
    with pytest.raises(ValueError):
        invoke(env, request=scoped_request(scope_id="another-source"))
    assert env[3] == []


def test_factory_typeerror_is_not_retried(tmp_path, monkeypatch):
    from jarvis.model_routing.invoker import StructuredOutputModelAdapter

    env = environment(tmp_path, monkeypatch, {})
    target = env[1].target_registry.all()[0]
    calls = []

    def broken(provider, model):
        calls.append((provider, model))
        raise TypeError("internal construction failure")

    adapter = StructuredOutputModelAdapter(
        adapter_id="gemini", provider_id="gemini", client_factory=broken
    )
    with pytest.raises(TypeError, match="internal construction failure"):
        adapter._client_for(target)
    assert len(calls) == 1


def test_configured_chatgpt_plan_then_free_then_paid_has_three_visits(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from tests.gemini_fallback.helpers import Strategy

    from jarvis.chatgpt_plan import ChatGPTPlanError
    from jarvis.model_routing.invoker import ModelInvoker
    from jarvis.model_routing.registry import (
        ModelAdapterRegistry,
        ModelTargetRegistry,
        RoutingStrategyRegistry,
    )
    from jarvis.model_routing.router import ModelRouter

    env = environment(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(429, {})]}
    )
    free, paid = env[1].target_registry.all()
    calls = []

    class PlanAdapter:
        adapter_id = "chatgpt_plan"

        async def invoke_structured(self, **kwargs):
            calls.append(kwargs["target"].target_id)
            raise ChatGPTPlanError("synthetic disconnected plan")

    plan = replace(
        free,
        target_id="memory.extraction.chatgpt_plan.primary",
        provider_id="chatgpt_plan",
        adapter_id="chatgpt_plan",
        model_id="gpt-test",
        credential_ref=None,
    )
    adapters = ModelAdapterRegistry(
        (env[1].adapter_registry.require("gemini"), PlanAdapter())
    )
    router = ModelRouter(
        target_registry=ModelTargetRegistry(adapters, (plan, free, paid)),
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((Strategy(),)),
        routing_store=env[1].routing_store,
        credential_available=lambda _: True,
        clock=lambda: 100,
        fallback_budget=2,
    )
    invoker = ModelInvoker(
        adapters, paid_budget=env[2], pricing=env[0].pricing, clock=lambda: 100
    )
    result = invoke((invoker, router, *env[2:]))
    assert result.parsed.answer == "ok"
    assert len(calls) == 1
    assert len(env[3]) == 2
    saved = router.routing_store.find_scoped_decision_by_request("scope-request-1")
    attempts = router.routing_store.list_scoped_attempts(saved.decision.decision_id)
    assert [a.provider_id for a in attempts] == ["chatgpt_plan", "gemini", "gemini"]


def test_direct_work_paid_call_is_bounded_settled_and_never_redispatched(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.gemini import GeminiFallbackConfig
    from jarvis.model_routing.pricing import PaidExposure
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

    env = environment(tmp_path, monkeypatch, {})
    free, paid = env[1].target_registry.all()
    env[1].routing_store.record_pressure(
        target=free,
        failure=ProviderFailure("gemini", ProviderFailureKind.RATE_LIMITED),
        config=GeminiFallbackConfig(enabled=True),
        now_epoch=100,
    )
    context = ModelInvocationContext(
        work_id="work-1",
        routing_request_id="request-1",
        decision_id="decision-1",
        attempt_id="attempt-1",
        correlation_key="correlation-1",
    )
    bound = PaidExposure(
        usage_bounds={"input_tokens": 5000, "output_tokens": 5000},
        scope_kind="work",
        scope_id="work-1",
    )

    async def call():
        return await env[0].invoke_structured(
            target=paid,
            system_prompt="answer",
            input_payload={},
            response_model=Answer,
            request_context=context,
            exposure=bound,
        )

    assert asyncio.run(call()).answer == "ok"
    with pytest.raises(PaidOutcomeUnknown):
        asyncio.run(call())
    assert len(env[3]) == 1
    assert env[3][0][0] == "paid-private-canary"
    assert env[2].status().spent_inr_minor == 30
