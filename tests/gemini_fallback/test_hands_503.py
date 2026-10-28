import asyncio
import hashlib
from dataclasses import replace

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.test_hands_memory import shared
from tests.gemini_fallback.test_invocation import Answer

from jarvis.hands.provider_adapters import RoutedStructuredOutputClient
from jarvis.model_routing.invoker import RoutedInferenceFailure


def client_for(runtime):
    return RoutedStructuredOutputClient(
        routing_runtime=runtime, role="hands", model="gemini-budget-test"
    )


def test_hands_503_tries_paid_once_then_next_request_starts_free(tmp_path, monkeypatch):
    runtime, env = shared(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(503, {})]}
    )
    client = client_for(runtime)

    async def run():
        for operation in ("first", "next"):
            result = await client.parse(
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                scope_id="hands-test",
                operation_id=operation,
            )
            assert result.answer == "ok"

    asyncio.run(run())
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
        "free-private-canary",
    ]
    free = client.router.target_registry.all()[0]
    assert runtime.store.get_health(free.target_id) is None


def test_hands_paid_503_stops_without_retry_or_replay(tmp_path, monkeypatch):
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(503, {})],
            "paid-private-canary": [APIError(503, {})],
        },
    )
    client = client_for(runtime)
    with pytest.raises(RoutedInferenceFailure):
        asyncio.run(
            client.parse(
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                scope_id="hands-test",
                operation_id="once",
            )
        )
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
    ]


def test_recorded_hands_502_does_not_admit_direct_paid_call(tmp_path, monkeypatch):
    from jarvis.model_routing.budget import PaidBudgetDenied
    from jarvis.model_routing.invoker import ScopedModelInvocationContext
    from jarvis.model_routing.pricing import PaidExposure

    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(502, {}), APIError(502, {})],
        },
    )
    client = client_for(runtime)
    with pytest.raises(RoutedInferenceFailure):
        asyncio.run(
            client.parse(
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                scope_id="hands-test",
                operation_id="once",
            )
        )
    request_id = (
        "inference:" + hashlib.sha256(b"hands|hands-test|once|hands").hexdigest()
    )
    saved = runtime.store.find_scoped_decision_by_request(request_id)
    attempts = runtime.store.list_scoped_attempts(saved.decision.decision_id)
    assert attempts[-1].failure_class == "service_unavailable"
    attempt_id = f"{saved.decision.decision_id}:{len(attempts) + 1}"
    context = ScopedModelInvocationContext(
        "hands",
        "hands-test",
        request_id,
        saved.decision.decision_id,
        attempt_id,
        attempt_id,
    )
    paid = client.router.target_registry.all()[1]
    with pytest.raises(PaidBudgetDenied):
        asyncio.run(
            runtime.invoker.invoke_structured_with_telemetry(
                target=paid,
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
                request_context=context,
                exposure=PaidExposure(
                    usage_bounds={"input_tokens": 5000, "output_tokens": 4096},
                    scope_kind="hands",
                    scope_id="hands-test",
                ),
            )
        )
    assert [key for key, _, _ in env[3]] == ["free-private-canary"] * 2


def test_hands_503_with_fallback_disabled_keeps_free_retry(tmp_path, monkeypatch):
    runtime, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(503, {}), APIError(503, {})],
        },
    )
    runtime.config = replace(runtime.config, enabled=False)
    client = client_for(runtime)
    with pytest.raises(RoutedInferenceFailure):
        asyncio.run(
            client.parse(
                system_prompt="answer",
                input_payload={},
                response_model=Answer,
            )
        )
    assert [key for key, _, _ in env[3]] == ["free-private-canary"] * 2


def test_hands_503_success_is_not_replayed_for_same_operation(tmp_path, monkeypatch):
    from jarvis.model_routing.budget import PaidOutcomeUnknown

    runtime, env = shared(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(503, {})]}
    )
    client = client_for(runtime)

    async def run():
        kwargs = {
            "system_prompt": "answer",
            "input_payload": {},
            "response_model": Answer,
            "scope_id": "hands-test",
            "operation_id": "once",
        }
        assert (await client.parse(**kwargs)).answer == "ok"
        with pytest.raises(PaidOutcomeUnknown):
            await client.parse(**kwargs)

    asyncio.run(run())
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
    ]
