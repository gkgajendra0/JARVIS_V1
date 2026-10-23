import asyncio
from dataclasses import replace
from types import SimpleNamespace

import google.genai
import pytest
from google.genai.errors import APIError
from pydantic import BaseModel
from tests.gemini_fallback.helpers import (
    Strategy,
    budget_fixture,
    exposure,
    scoped_request,
)

from jarvis.hands.provider_adapters import build_structured_output_client
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.invoker import (
    ModelInvoker,
    RoutedInferenceFailure,
    StructuredOutputModelAdapter,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import ModelRouter


class Answer(BaseModel):
    answer: str


def environment(
    tmp_path, monkeypatch, scripts, *, pricing_enabled=True, clock=lambda: 100
):
    budget, store, paid, price = budget_fixture(tmp_path / "routing.db")
    free = replace(
        paid,
        target_id=paid.target_id.replace(".paid.", ".free."),
        credential_ref="GOOGLE_API_KEY",
        cost_profile=None,
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "free-private-canary")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-private-canary")
    calls = []
    builds = []

    def client(**kwargs):
        key = kwargs["api_key"]
        builds.append(kwargs)

        async def create(**request):
            calls.append((key, request, budget.status()))
            values = scripts.setdefault(key, [])
            value = values.pop(0) if values else "ok"
            if callable(value):
                value = value(request)
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, asyncio.Event):
                await value.wait()
            if isinstance(value, dict):
                return SimpleNamespace(**value)
            return SimpleNamespace(
                output_text='{"answer":"ok"}',
                usage=SimpleNamespace(
                    total_input_tokens=10,
                    total_output_tokens=4,
                    total_thought_tokens=1,
                    total_tokens=15,
                    total_cached_tokens=0,
                    total_tool_use_tokens=0,
                ),
            )

        return SimpleNamespace(
            aio=SimpleNamespace(
                interactions=SimpleNamespace(
                    create=create,
                    sdk_configuration=SimpleNamespace(retry_config="synthetic-default"),
                )
            )
        )

    monkeypatch.setattr(google.genai, "Client", client)
    adapters = ModelAdapterRegistry(
        (StructuredOutputModelAdapter(adapter_id="gemini", provider_id="gemini"),)
    )
    router = ModelRouter(
        target_registry=ModelTargetRegistry(adapters, (free, paid)),
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((Strategy(),)),
        routing_store=store,
        clock=clock,
    )
    invoker = ModelInvoker(
        adapters,
        paid_budget=budget,
        pricing=price if pricing_enabled else None,
        clock=clock,
    )
    return invoker, router, budget, calls, builds


def invoke(env, *, request=None, bound=None):
    invoker, router, *_ = env
    return asyncio.run(
        invoker.invoke_scoped_structured(
            router=router,
            request=request or scoped_request(scope_id="source-budget"),
            system_prompt="answer",
            input_payload={"question": "fictional"},
            response_model=Answer,
            exposure=bound or exposure(),
        )
    )


def test_free_success_never_touches_paid(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch, {})
    result = invoke(env)
    assert result.parsed.answer == "ok"
    assert [key for key, _, _ in env[3]] == ["free-private-canary"]
    assert env[2].status().spent_inr_minor == 0
    assert "generation_config" not in env[3][0][1]


def test_quota_falls_to_paid_once_reserved_before_send_and_settles_thinking(
    tmp_path, monkeypatch, caplog
):
    env = environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                APIError(429, {"error": {"message": "quota exceeded"}})
            ]
        },
    )
    result = invoke(env)
    assert result.parsed.answer == "ok"
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
    ]
    assert env[3][1][2].reserved_inr_minor == 20000
    assert env[3][1][1]["generation_config"]["max_output_tokens"] == 5000
    assert all(c["http_options"]["retry_options"]["attempts"] == 0 for c in env[4])
    assert env[2].status().spent_inr_minor == 30
    decision = env[1].routing_store.find_scoped_decision_by_request("scope-request-1")
    attempts = env[1].routing_store.list_scoped_attempts(decision.decision.decision_id)
    assert [a.failure_class for a in attempts] == ["quota_exhausted", None]
    assert attempts[1].usage["reasoning_tokens"] == 1
    assert attempts[0].correlation_key != attempts[1].correlation_key
    assert "private-canary" not in caplog.text
    with env[1].routing_store.work_store.extension_transaction() as connection:
        for table in [
            "model_scoped_routing_attempts",
            "model_scoped_routing_decisions",
            "paid_fallback_reservations",
        ]:
            assert "private-canary" not in str(
                [tuple(r) for r in connection.execute("SELECT * FROM " + table)]
            )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 503])
def test_nonquota_failure_does_not_send_paid(tmp_path, monkeypatch, status):
    env = environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [
                APIError(status, {"error": {"message": "model unavailable"}})
            ]
        },
    )
    with pytest.raises(RoutedInferenceFailure):
        invoke(env)
    assert [key for key, _, _ in env[3]] == ["free-private-canary"]


@pytest.mark.parametrize("status", [401, 402, 429, 503])
def test_paid_failure_terminates_without_repeat(tmp_path, monkeypatch, status):
    env = environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [APIError(status, {})],
        },
    )
    with pytest.raises(RoutedInferenceFailure):
        invoke(env)
    assert len(env[3]) == 2
    assert env[2].status().unknown_reservations == 1
    if status == 402:
        assert env[1].routing_store.credential_blocked("JARVIS_GEMINI_PAID_API_KEY")


def test_missing_price_blocks_paid_before_send(tmp_path, monkeypatch):
    env = environment(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})]},
        pricing_enabled=False,
    )
    with pytest.raises(PaidBudgetDenied):
        invoke(env)
    assert len(env[3]) == 1


def test_understated_input_bound_blocks_paid(tmp_path, monkeypatch):
    env = environment(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(429, {})]}
    )
    with pytest.raises(PaidBudgetDenied):
        invoke(env, bound=exposure(input_tokens=1))
    assert len(env[3]) == 1


def test_explicit_paid_builder_uses_paid_key_without_global_mutation(monkeypatch):
    captured = []
    monkeypatch.setenv("GOOGLE_API_KEY", "free-private-canary")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-private-canary")
    monkeypatch.setattr(
        google.genai,
        "Client",
        lambda **kwargs: (
            captured.append(kwargs)
            or SimpleNamespace(
                aio=SimpleNamespace(
                    interactions=SimpleNamespace(
                        create=lambda **_: None,
                        sdk_configuration=SimpleNamespace(
                            retry_config="synthetic-default"
                        ),
                    )
                )
            )
        ),
    )
    build_structured_output_client(
        provider="gemini",
        model="gemini-test",
        credential_ref="JARVIS_GEMINI_PAID_API_KEY",
        provider_retries=False,
        max_output_tokens=200,
    )
    import os

    assert captured[0]["api_key"] == "paid-private-canary"
    assert os.environ["GOOGLE_API_KEY"] == "free-private-canary"


def test_new_requests_use_paid_during_cooldown_then_recover_free_on_demand(
    tmp_path, monkeypatch
):
    now = [100]
    env = environment(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})]},
        clock=lambda: now[0],
    )
    invoke(env)
    now[0] = 159
    invoke(
        env, request=scoped_request(routing_request_id="r2", scope_id="source-budget")
    )
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "paid-private-canary",
        "paid-private-canary",
    ]
    now[0] = 160
    invoke(
        env, request=scoped_request(routing_request_id="r3", scope_id="source-budget")
    )
    invoke(
        env, request=scoped_request(routing_request_id="r4", scope_id="source-budget")
    )
    assert [key for key, _, _ in env[3]][-2:] == [
        "free-private-canary",
        "free-private-canary",
    ]
    assert env[2].status().spent_inr_minor == 60


def test_missing_paid_key_does_not_send_or_hold_unsent_reservation(
    tmp_path, monkeypatch
):
    env = environment(
        tmp_path, monkeypatch, {"free-private-canary": [APIError(429, {})]}
    )
    monkeypatch.delenv("JARVIS_GEMINI_PAID_API_KEY")
    with pytest.raises(PaidBudgetDenied):
        invoke(env)
    assert len(env[3]) == 1
    assert env[2].status().reserved_inr_minor == 0


def test_key_rotation_invalidates_cached_free_client(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch, {})
    invoke(env)
    monkeypatch.setenv("GOOGLE_API_KEY", "rotated-private-canary")
    invoke(
        env,
        request=scoped_request(routing_request_id="rotated", scope_id="source-budget"),
    )
    assert [key for key, _, _ in env[3]] == [
        "free-private-canary",
        "rotated-private-canary",
    ]


def test_no_paid_admission_does_not_mark_paid_provider_unhealthy(tmp_path, monkeypatch):
    env = environment(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})]},
        pricing_enabled=False,
    )
    with pytest.raises(PaidBudgetDenied):
        invoke(env)
    assert (
        env[1].routing_store.get_health(env[1].target_registry.all()[1].target_id)
        is None
    )


def test_legacy_target_without_credential_reference_keeps_provider_default(
    tmp_path, monkeypatch
):
    env = environment(tmp_path, monkeypatch, {})
    legacy = replace(
        env[1].target_registry.all()[0], credential_ref=None, registry_version=1
    )
    adapter = env[1].adapter_registry.require("gemini")
    client = adapter._client_for(legacy)
    assert client.provider_name == "gemini"
    assert env[4][0]["api_key"] == "free-private-canary"
