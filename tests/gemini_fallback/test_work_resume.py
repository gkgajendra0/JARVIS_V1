import asyncio
import json
from dataclasses import replace

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.test_invocation import environment

from jarvis.model_routing.invoker import StructuredOutputModelAdapter
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import ModelRouter, build_work_routing_request
from jarvis.model_routing.strategy import EngineeringStageStrategy
from jarvis.work.brain import BrainAction, BrainRequest
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.reasoner import RoutedWorkReasoner

RESULT = {
    "action": None,
    "summary": "Fictional bounded answer",
    "parameters_json": "{}",
    "goal_complete": True,
    "needs_owner": False,
    "owner_question": None,
}


def work_environment(tmp_path, monkeypatch, scripts):
    env = environment(tmp_path, monkeypatch, scripts)
    invoker, base, *_ = env
    targets = tuple(
        replace(
            t,
            target_id=t.target_id.replace("memory.extraction.", "work."),
            capabilities=("engineering_reasoning", "structured_output"),
        )
        for t in base.target_registry.all()
    )
    adapters = ModelAdapterRegistry(
        (
            base.adapter_registry.require("gemini"),
            StructuredOutputModelAdapter(adapter_id="openai", provider_id="openai"),
        )
    )
    router = ModelRouter(
        target_registry=ModelTargetRegistry(adapters, targets),
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=base.routing_store,
        clock=lambda: 100,
    )
    work = WorkItem(
        request="Answer fictional bounded task",
        work_type=WorkType.GENERIC,
        source_session_id="fictional",
        source_turn_id="turn-1",
    )
    base.routing_store.work_store.create(work)
    request = BrainRequest(
        work=work,
        recent_steps=(),
        purpose="bounded answer",
        allowed_actions=(
            BrainAction(
                name="record",
                description="fictional bounded action",
                parameter_schema={"type": "object"},
            ),
        ),
    )
    reasoner = RoutedWorkReasoner(
        router=router,
        invoker=invoker,
        primary_target_id=targets[0].target_id,
        clock=lambda: 100,
    )
    return env, router, reasoner, request


def output():
    return {
        "output_text": json.dumps(RESULT),
        "usage": {
            "total_input_tokens": 10,
            "total_output_tokens": 4,
            "total_thought_tokens": 1,
            "total_tokens": 15,
            "total_cached_tokens": 0,
            "total_tool_use_tokens": 0,
        },
    }


def test_paid_work_result_replays_without_another_provider_call(tmp_path, monkeypatch):
    env, router, reasoner, request = work_environment(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})], "paid-private-canary": [output()]},
    )
    first = asyncio.run(reasoner.decide(request))
    assert first.goal_complete
    assert len(env[3]) == 2
    restarted = RoutedWorkReasoner(
        router=router,
        invoker=env[0],
        primary_target_id=router.target_registry.all()[0].target_id,
        clock=lambda: 100,
    )
    second = asyncio.run(restarted.decide(request))
    assert second == first
    assert len(env[3]) == 2
    stored = router.routing_store.find_decision_by_request(
        build_work_routing_request(
            request, primary_target_id=router.target_registry.all()[0].target_id
        ).routing_request_id
    )
    assert len(router.routing_store.list_attempts(stored.decision.decision_id)) == 2
    assert env[2].status().spent_inr_minor == 30


def test_cancelled_paid_work_is_not_redispatched_on_resume(tmp_path, monkeypatch):
    async def run():
        waiting = asyncio.Event()
        env, router, reasoner, request = work_environment(
            tmp_path,
            monkeypatch,
            {
                "free-private-canary": [APIError(429, {})],
                "paid-private-canary": [waiting],
            },
        )
        task = asyncio.create_task(reasoner.decide(request))
        for _ in range(100):
            if len(env[3]) == 2:
                break
            await asyncio.sleep(0)
        assert len(env[3]) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        from jarvis.model_routing.router import RoutingResourceBlocked

        restarted = RoutedWorkReasoner(
            router=router,
            invoker=env[0],
            primary_target_id=router.target_registry.all()[0].target_id,
            clock=lambda: 100,
        )
        with pytest.raises(RoutingResourceBlocked):
            await restarted.decide(request)
        assert len(env[3]) == 2
        assert env[2].status().unknown_reservations == 1

    asyncio.run(run())


def test_existing_v1_request_does_not_acquire_paid_edge(tmp_path, monkeypatch):
    from jarvis.model_routing.router import build_default_work_targets

    env, router, _, request = work_environment(
        tmp_path, monkeypatch, {"free-private-canary": [output()]}
    )
    legacy = build_default_work_targets(
        configured_provider="gemini",
        configured_model="gemini-budget-test",
        adapter_registry=router.adapter_registry,
    )
    old = ModelRouter(
        target_registry=legacy.registry,
        adapter_registry=router.adapter_registry,
        strategy_registry=router.strategy_registry,
        routing_store=router.routing_store,
        credential_available=lambda _: True,
        clock=lambda: 100,
    )
    routing_request = build_work_routing_request(
        request, primary_target_id=legacy.primary_target_id
    )
    original = old.route(routing_request)
    current = ModelRouter(
        target_registry=router.target_registry,
        adapter_registry=router.adapter_registry,
        strategy_registry=router.strategy_registry,
        routing_store=router.routing_store,
        credential_available=lambda _: True,
        clock=lambda: 100,
        historical_registries={legacy.registry.digest(): legacy.registry},
    )
    reasoner = RoutedWorkReasoner(
        router=current,
        invoker=env[0],
        primary_target_id=router.target_registry.all()[0].target_id,
        clock=lambda: 100,
    )
    result = asyncio.run(reasoner.decide(request))
    assert result.goal_complete
    same = current.route(routing_request)
    assert same.decision == original.decision
    assert all(".paid." not in t for t in same.decision.ordered_target_ids)
    assert len(env[3]) == 1


def test_paid_failure_never_creates_second_paid_visit_after_usage_reconciled(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.router import RoutingResourceBlocked

    env, router, reasoner, request = work_environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [APIError(503, {})],
        },
    )
    with pytest.raises(RoutingResourceBlocked):
        asyncio.run(reasoner.decide(request))
    assert len(env[3]) == 2
    with router.routing_store.work_store.extension_transaction() as connection:
        reservation = connection.execute(
            "SELECT reservation_id FROM paid_fallback_reservations"
        ).fetchone()[0]
    env[2].settle(
        reservation_id=reservation,
        usage={"input_tokens": 0, "output_tokens": 0},
        usage_complete=True,
        event_id="synthetic-reconciled-no-charge",
    )
    with pytest.raises(RoutingResourceBlocked):
        asyncio.run(reasoner.decide(request))
    assert len(env[3]) == 2


def test_work_503_retains_same_target_retry_without_new_paid_hop(tmp_path, monkeypatch):
    env, _, reasoner, request = work_environment(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(503, {}), output()]}
    )
    result = asyncio.run(reasoner.decide(request))
    assert result.goal_complete
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "free-private-canary",
    ]


def test_v2_work_request_rejection_exposes_only_sanitized_failure(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.router import RoutingResourceBlocked

    env, _, reasoner, request = work_environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                APIError(400, {"error": {"message": "private-provider-body-canary"}})
            ]
        },
    )
    with pytest.raises(RoutingResourceBlocked) as raised:
        asyncio.run(reasoner.decide(request))
    assert "private-provider-body-canary" not in str(raised.value)
    assert len(env[3]) == 1
