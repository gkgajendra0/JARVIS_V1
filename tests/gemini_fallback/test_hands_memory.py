import asyncio
import json

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.test_invocation import environment
from tests.learning.test_extractors import source

from jarvis.model_routing.gemini import GeminiFallbackConfig


def response(payload):
    return {
        "output_text": json.dumps(payload, ensure_ascii=False),
        "usage": {
            "total_input_tokens": 10,
            "total_output_tokens": 4,
            "total_thought_tokens": 1,
            "total_tokens": 15,
        },
    }


def shared(tmp_path, monkeypatch, scripts):
    from jarvis.model_routing.runtime import build_routing_runtime

    env = environment(tmp_path, monkeypatch, scripts)
    path = tmp_path / "price.json"
    path.write_text(json.dumps(env[0].pricing.to_payload()), encoding="utf-8")
    runtime = build_routing_runtime(
        work_store=env[1].routing_store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(enabled=True, pricing_path=path),
        clock=lambda: 100,
    )
    return runtime, env


@pytest.mark.parametrize("status", [429, 503])
def test_hands_fallback_after_action_does_not_execute_it_twice(
    tmp_path, monkeypatch, status
):
    from tests.test_hands_orchestrator import (
        FakeCatalog,
        RecordingExecutor,
        runtime_for,
    )

    from jarvis.hands.orchestrator import HandsOrchestrator
    from jarvis.hands.planner import build_hands_planner

    action = {
        "actions": [
            {
                "operation": "open_app",
                "parameters": {"app": "Calculator"},
                "evidence": "Open Calculator",
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
                APIError(status, {}),
            ],
            "paid-private-canary": [response({"actions": [], "goal_complete": True})],
        },
    )
    planner = build_hands_planner(
        provider="gemini", model="gemini-budget-test", routing_runtime=runtime
    )
    executor = RecordingExecutor(("open_app",))
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )
    result = asyncio.run(
        orchestrator.execute_goal(session_id="fictional-hands", goal="Open Calculator")
    )
    assert result["ok"]
    assert len(executor.calls) == 1
    assert [key for key, _, _ in env[3]] == ["free-private-canary"] * 3 + [
        "paid-private-canary"
    ]


def test_automatic_learning_extraction_and_resolution_keep_canonical_contracts(
    tmp_path, monkeypatch
):
    from jarvis.memory.learning_contracts import LearningCatalog, LearningCatalogEntry
    from jarvis.memory.learning_extractors import build_learning_adapters

    s = source("I own a City")
    proposal = {
        "candidates": [
            {
                "category": "owned_item",
                "kind": "vehicle",
                "intent": "new",
                "label": "City",
                "value": "City",
                "state": "owned",
                "evidence": [{"turn_id": s.turn_id, "quote": "City"}],
            }
        ]
    }
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {}), APIError(429, {})],
            "paid-private-canary": [
                response(proposal),
                response(
                    {
                        "resolutions": [
                            {
                                "candidate_index": 0,
                                "decision": "duplicate",
                                "target_id": "known-city",
                            }
                        ]
                    }
                ),
            ],
        },
    )
    adapter, resolver = build_learning_adapters(
        "gemini", "gemini-budget-test", routing_runtime=runtime
    )

    async def run():
        batch = await adapter.extract(s)
        assert batch.candidates[0].value == "City"
        catalog = LearningCatalog(
            entries=[
                LearningCatalogEntry(
                    assertion_id="known-city",
                    category="owned_item",
                    kind="vehicle",
                    predicate="owned_item_city",
                    text="City",
                    value="City",
                )
            ]
        )
        result = await resolver.resolve(s, batch, catalog)
        assert result.resolutions[0].target_id == "known-city"
        await adapter.close()

    asyncio.run(run())
    assert all(
        request["generation_config"]["max_output_tokens"] == 4096
        for _, request, _ in env[3]
    )
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
        "free-private-canary",
        "paid-private-canary",
    ]


def test_learning_retains_typed_failure_without_public_provider_body(
    tmp_path, monkeypatch
):
    from jarvis.memory.learning_extractors import build_learning_adapters

    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                APIError(401, {"error": {"message": "private-error-canary"}})
            ]
        },
    )
    adapter, _ = build_learning_adapters(
        "gemini", "gemini-budget-test", routing_runtime=runtime
    )
    with pytest.raises(RuntimeError, match="learning_provider_unavailable") as raised:
        asyncio.run(adapter.extract(source("I own a City")))
    assert adapter.last_provider_failure.kind.value == "authentication_failed"
    assert "private-error-canary" not in str(raised.value)
    assert len(env[3]) == 1


def test_semantic_recall_uses_existing_materialization_after_fallback(
    tmp_path, monkeypatch
):
    from jarvis.memory.query_interpreters import build_memory_query_interpreter
    from jarvis.memory.query_plan import MemoryFacetCatalog, MemoryFacetKey

    payload = {
        "intent": "exact_fact",
        "facet_index": 0,
        "subject_reference": "my",
        "requested_relation": "vehicle",
        "temporal_scope": "current",
        "as_of_text": None,
    }
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [response(payload)],
        },
    )
    interpreter = build_memory_query_interpreter(
        provider="gemini", model="gemini-budget-test", routing_runtime=runtime
    )
    catalog = MemoryFacetCatalog((MemoryFacetKey("owner", "self", "owned_vehicle"),))
    result = asyncio.run(
        interpreter.interpret(text="What is my vehicle?", catalog=catalog)
    )
    assert result.predicate == "owned_vehicle"
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
    ]


def test_candidate_extraction_uses_same_bounded_inference_only_path(
    tmp_path, monkeypatch
):
    from jarvis.memory.extractors import build_memory_candidate_extractor

    payload = {
        "intent": "candidate",
        "candidate_type": "fact",
        "durable_candidate": True,
        "subject": "self",
        "predicate": "owned_vehicle",
        "value": "City",
        "temporal_hint": None,
        "sensitivity": "normal",
        "confidence": 0.9,
    }
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [response(payload)],
        },
    )
    extractor = build_memory_candidate_extractor(
        provider="gemini", model="gemini-budget-test", routing_runtime=runtime
    )
    result = asyncio.run(extractor.extract(text="I own a City"))
    assert result.value == "City"
    assert len(env[3]) == 2


def test_conservative_paid_bound_does_not_replace_free_context_estimate(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.test_invocation import Answer

    from jarvis.hands.provider_adapters import RoutedStructuredOutputClient

    runtime, env = shared(tmp_path, monkeypatch, {})
    client = RoutedStructuredOutputClient(
        routing_runtime=runtime,
        role="hands",
        model="gemini-budget-test",
        max_output_tokens=4096,
    )
    result = asyncio.run(
        client.parse(
            system_prompt="answer",
            input_payload={"fictional_context": "x" * 35000},
            response_model=Answer,
        )
    )
    assert result.answer == "ok"
    assert [key for key, _, _ in env[3]] == ["free-private-canary"]


def test_hands_configured_chatgpt_plan_keeps_priority_and_identity(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from jarvis.hands.planner import HandsRouteGroup, build_hands_planner
    from jarvis.hands.registry import HandsCapabilityRegistry
    from jarvis.model_routing.runtime import build_routing_runtime

    runtime, env = shared(tmp_path, monkeypatch, {})
    calls = []

    class Connected:
        def is_connected(self):
            return True

        def invoke_structured(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text='{"group_indices":[0]}', usage={}, usage_observed=False
            )

    configured = build_routing_runtime(
        work_store=runtime.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=runtime.config,
        chatgpt_plan_session=Connected(),
        chatgpt_plan_model="gpt-test",
        clock=lambda: 100,
    )
    planner = build_hands_planner(
        provider="gemini",
        model="gemini-budget-test",
        routing_runtime=configured,
        chatgpt_plan_enabled=True,
        chatgpt_plan_model="gpt-test",
    )
    operation = HandsCapabilityRegistry.default().operation("open_app")
    result = asyncio.run(
        planner.route(
            goal="Open Calculator",
            recent_user_turns=(),
            route_groups=(HandsRouteGroup("app_lifecycle", "apps", (operation,)),),
        )
    )
    assert result == ("app_lifecycle",)
    assert len(calls) == 1
    assert env[3] == []
    assert planner.provider_name == "chatgpt_plan"
    assert planner.model_name == "gpt-test"


@pytest.mark.asyncio
async def test_memory_release_verifier_uses_same_governor_after_free_quota(
    tmp_path, monkeypatch
):
    from tests.test_memory_provider_release_guard import _record

    from jarvis.memory.release_guard import build_memory_release_guard

    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [
                response({"answer_type": "current_value", "directly_supported": True})
            ],
        },
    )
    guard = build_memory_release_guard(
        provider="gemini", model="gemini-budget-test", routing_runtime=runtime
    )

    async def current():
        return None

    judgement = await guard.evaluate_current(
        text="What vehicle do I have?", evidence=_record(), before_dispatch=current
    )
    assert judgement.allows_release
    assert guard._client.runtime is runtime
    assert [call[0] for call in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
    ]
    assert runtime.paid_budget.status().spent_inr_minor > 0
