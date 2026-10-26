import asyncio
import multiprocessing
from dataclasses import replace

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.helpers import budget_fixture, exposure
from tests.gemini_fallback.test_hands_memory import response, shared
from tests.gemini_fallback.test_invocation import Answer
from tests.gemini_fallback.test_work_resume import work_environment

from jarvis.ai_provider import gemini_credential_ref
from jarvis.hands.provider_adapters import RoutedStructuredOutputClient
from jarvis.model_routing.budget import PaidBudgetDenied, read_paid_cost_records
from jarvis.model_routing.invoker import RoutedInferenceFailure


@pytest.mark.asyncio
async def test_paid_authentication_failure_disables_credential_across_scoped_lanes(
    tmp_path, monkeypatch, caplog
):
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [
                APIError(401, {"error": {"message": "secret-private-canary"}})
            ],
        },
    )
    client = RoutedStructuredOutputClient(
        routing_runtime=runtime, role="hands", model="gemini-budget-test"
    )
    with pytest.raises(RoutedInferenceFailure):
        await client.parse(
            system_prompt="fictional", input_payload={}, response_model=Answer
        )
    assert runtime.store.credential_blocked(gemini_credential_ref("paid"))
    assert not runtime.store.credential_blocked(gemini_credential_ref("free"))
    assert len(env[3]) == 2
    assert "secret-private-canary" not in caplog.text
    assert "paid-private-canary" not in caplog.text


def test_paid_work_authentication_failure_disables_same_credential_scope(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.router import RoutingResourceBlocked

    env, router, reasoner, request = work_environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [APIError(401, {})],
        },
    )
    with pytest.raises(RoutingResourceBlocked):
        asyncio.run(reasoner.decide(request))
    assert router.routing_store.credential_blocked(gemini_credential_ref("paid"))
    assert len(env[3]) == 2


@pytest.mark.asyncio
async def test_paid_balance_failure_still_allows_demand_driven_free_recovery(
    tmp_path, monkeypatch
):
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                APIError(429, {}),
                response({"answer": "free recovered"}),
            ],
            "paid-private-canary": [APIError(402, {})],
        },
    )
    client = RoutedStructuredOutputClient(
        routing_runtime=runtime, role="hands", model="gemini-budget-test"
    )
    with pytest.raises(RoutedInferenceFailure):
        await client.parse(
            system_prompt="fictional", input_payload={}, response_model=Answer
        )
    assert runtime.store.credential_blocked(gemini_credential_ref("paid"))
    runtime.clock = lambda: 200
    runtime.invoker._clock = runtime.clock
    runtime.paid_budget.clock = runtime.clock
    client.router._clock = runtime.clock
    answer = await client.parse(
        system_prompt="new fictional request", input_payload={}, response_model=Answer
    )
    assert answer.answer == "free recovered"
    assert [item[0] for item in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
        "free-private-canary",
    ]
    assert runtime.paid_budget.status().unknown_reservations == 1


def _lane_reserve(path, role, barrier, results):
    governor, _, target, price = budget_fixture(path)
    target = replace(target, target_id=f"{role}.gemini.paid.gemini-budget-test")
    scope = "work" if role == "work" else ("hands" if role == "hands" else "memory")
    bounded = replace(exposure(), scope_kind=scope, scope_id=role)
    barrier.wait(timeout=30)
    try:
        reservation = governor.reserve(
            invocation_id=f"{role}-invocation",
            target=target,
            exposure=bounded,
            pricing=price,
        )
        governor.mark_dispatched(reservation.reservation_id)
    except PaidBudgetDenied:
        results.put((role, "denied"))
    else:
        results.put((role, "reserved"))


def test_work_hands_and_memory_processes_compete_for_one_real_budget(tmp_path):
    from jarvis.voice.gemini_budget import GeminiLiveBudget

    path = tmp_path / "shared.db"
    budget_fixture(path)
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(3), ctx.Queue()
    children = [
        ctx.Process(target=_lane_reserve, args=(path, role, barrier, results))
        for role in ("work", "hands", "memory.extraction")
    ]
    for child in children:
        child.start()
    try:
        outcomes = [results.get(timeout=45) for _ in children]
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
        assert sorted(result for _, result in outcomes) == [
            "denied",
            "denied",
            "reserved",
        ]
        governor, store, _, _ = budget_fixture(path)
        assert governor.status().reserved_inr_minor == 20000
        records = read_paid_cost_records(store)
        assert len(records) == 1
        assert records[0].scope_kind in {"work", "hands", "memory"}
        assert not GeminiLiveBudget.available  # Paid Live is excluded, not fake-funded.
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
        results.close()


@pytest.mark.asyncio
async def test_new_request_rechecks_plan_availability_before_using_free_without_paid_probe(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from jarvis.model_routing.runtime import build_routing_runtime

    seed, env = shared(
        tmp_path, monkeypatch, {"free-private-canary": [response({"answer": "free"})]}
    )

    class Plan:
        connected = True
        calls = 0

        def is_connected(self):
            return self.connected

        def invoke_structured(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                output_text='{"answer":"plan"}', usage={}, usage_observed=False
            )

    plan = Plan()
    runtime = build_routing_runtime(
        work_store=seed.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=seed.config,
        chatgpt_plan_session=plan,
        chatgpt_plan_model="gpt-test",
        clock=lambda: 100,
    )
    client = RoutedStructuredOutputClient(
        routing_runtime=runtime,
        role="hands",
        model="gemini-budget-test",
        chatgpt_plan_model="gpt-test",
    )
    first = await client.parse(
        system_prompt="fictional", input_payload={}, response_model=Answer
    )
    assert first.answer == "plan" and plan.calls == 1 and env[3] == []
    plan.connected = False
    second = await client.parse(
        system_prompt="new fictional request", input_payload={}, response_model=Answer
    )
    assert second.answer == "free" and plan.calls == 1
    assert [item[0] for item in env[3]] == ["free-private-canary"]


@pytest.mark.asyncio
async def test_durable_work_rechecks_disconnected_plan_before_first_dispatch(
    tmp_path, monkeypatch
):
    import json

    from tests.gemini_fallback.test_work_resume import output

    from jarvis.model_routing.router import build_work_routing_request
    from jarvis.model_routing.runtime import build_routing_runtime
    from jarvis.work.reasoner import RoutedWorkReasoner

    env, _, _, request = work_environment(
        tmp_path, monkeypatch, {"free-private-canary": [output()]}
    )
    path = tmp_path / "plan-prices.json"
    path.write_text(json.dumps(env[0].pricing.to_payload()), encoding="utf-8")

    class Plan:
        connected = True
        calls = 0

        def is_connected(self):
            return self.connected

        def invoke_structured(self, **kwargs):
            self.calls += 1
            raise AssertionError("Disconnected plan was invoked")

    plan = Plan()
    config = replace(env[2].config, pricing_path=path)
    runtime = build_routing_runtime(
        work_store=env[1].routing_store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=config,
        chatgpt_plan_session=plan,
        chatgpt_plan_model="gpt-test",
        clock=lambda: 100,
    )
    selected = runtime.router.route(
        build_work_routing_request(request, primary_target_id=runtime.primary_target_id)
    )
    assert selected.target.provider_id == "chatgpt_plan"
    plan.connected = False
    reasoner = RoutedWorkReasoner(
        router=runtime.router,
        invoker=runtime.invoker,
        primary_target_id=runtime.primary_target_id,
        clock=lambda: 100,
    )
    assert (await reasoner.decide(request)).goal_complete
    assert plan.calls == 0
    assert [item[0] for item in env[3]] == ["free-private-canary"]


@pytest.mark.parametrize("confirmed", [True, False])
@pytest.mark.asyncio
async def test_fallback_never_reexecutes_confirmed_or_unconfirmed_clipboard_write(
    tmp_path, monkeypatch, confirmed
):
    from tests.test_hands_orchestrator import (
        FakeCatalog,
        RecordingExecutor,
        runtime_for,
    )

    from jarvis.capabilities.models import CapabilityStatus
    from jarvis.hands.orchestrator import HandsOrchestrator
    from jarvis.hands.planner import build_hands_planner

    operation = "set_clipboard_text"
    action = {
        "actions": [
            {
                "operation": operation,
                "parameters": {"text": "fictional-alpha"},
                "evidence": "Set clipboard text to fictional-alpha",
            }
        ],
        "goal_complete": False,
    }
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                response({"group_indices": [0]}),
                response(action),
                APIError(429, {}),
            ],
            "paid-private-canary": [response({"actions": [], "goal_complete": True})],
        },
    )

    class Executor(RecordingExecutor):
        writes = 0

        def execute(self, prepared):
            self.writes += 1
            return super().execute(prepared)

    executor = Executor(
        (operation,),
        statuses={
            operation: CapabilityStatus.SUCCEEDED
            if confirmed
            else CapabilityStatus.FAILED
        },
    )
    planner = build_hands_planner(
        provider="gemini", model="gemini-budget-test", routing_runtime=runtime
    )
    hands = HandsOrchestrator(runtime_for(executor), planner, app_catalog=FakeCatalog())
    result = await hands.execute_goal(
        session_id="fictional-write", goal="Set clipboard text to fictional-alpha"
    )
    assert executor.writes == 1
    assert len(executor.calls) == 1
    if confirmed:
        assert result["ok"]
        assert sum(key == "paid-private-canary" for key, _, _ in env[3]) == 1
    else:
        assert not result["ok"]
