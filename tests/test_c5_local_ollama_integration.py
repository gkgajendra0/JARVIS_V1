from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from jarvis.model_routing.eligibility import EligibilityPolicy
from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingRequest,
)
from jarvis.model_routing.ollama import (
    C5_LOCAL_TARGET_ID,
    OllamaStructuredOutputAdapter,
    _normalize_loopback_endpoint,
    build_c5_local_target_registry,
)
from jarvis.model_routing.registry import RoutingStrategyRegistry
from jarvis.model_routing.router import ModelRouter, build_default_work_targets
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.model_routing.strategy import EngineeringStageStrategy
from jarvis.work.store import SQLiteWorkStore


class LocalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str


def _local_target(**overrides: object) -> ModelTarget:
    values: dict[str, object] = {
        "target_id": "local.ollama.qwen3_5_4b.c5",
        "adapter_id": "ollama",
        "provider_id": "ollama",
        "model_id": "qwen3.5:4b",
        "locality": ModelLocality.LOCAL,
        "capabilities": (
            "bounded_planning",
            "classification_extraction",
            "summarization",
            "structured_output",
        ),
        "roles": ("efficient", "bounded_decision"),
        "max_context_tokens": 4096,
        "supports_structured_output": True,
        "supports_tools": False,
        "supports_streaming": False,
        "latency_class": "fast",
        "benchmark_status": BenchmarkStatus.ACCEPTED,
        "registry_version": 1,
        "endpoint_ref": "http://127.0.0.1:11434",
        "credential_ref": None,
    }
    values.update(overrides)
    return ModelTarget(**values)


def _context() -> ModelInvocationContext:
    return ModelInvocationContext(
        work_id="work-local",
        routing_request_id="route-local",
        decision_id="decision-local",
        attempt_id="attempt-local",
        correlation_key="corr-local",
    )


@pytest.mark.asyncio
async def test_ollama_adapter_uses_admitted_fast_profile_and_normalizes_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, payload, *, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {
            "message": {"content": '{"decision":"local"}'},
            "prompt_eval_count": 120,
            "eval_count": 12,
        }

    monkeypatch.setattr(
        "jarvis.model_routing.ollama._post_json",
        fake_post,
    )
    adapter = OllamaStructuredOutputAdapter()
    target = _local_target()

    result = await adapter.invoke_structured_with_telemetry(
        target=target,
        system_prompt="Classify the bounded request",
        input_payload={"task": "summarize"},
        response_model=LocalDecision,
        request_context=_context(),
    )

    assert result.parsed == LocalDecision(decision="local")
    assert result.usage_observed is True
    assert result.usage == {
        "input_tokens": 120,
        "output_tokens": 12,
        "total_tokens": 132,
    }
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen3.5:4b"
    assert payload["think"] is False
    assert payload["keep_alive"] == "5m"
    assert payload["stream"] is False
    assert payload["options"] == {
        "temperature": 0,
        "num_ctx": 4096,
        "num_predict": 256,
    }
    assert payload["format"] == LocalDecision.model_json_schema()


@pytest.mark.asyncio
async def test_ollama_adapter_rejects_non_local_target() -> None:
    adapter = OllamaStructuredOutputAdapter()
    target = _local_target(
        locality=ModelLocality.CLOUD,
        endpoint_ref="http://127.0.0.1:11434",
    )

    with pytest.raises(ValueError, match="must be local"):
        await adapter.invoke_structured(
            target=target,
            system_prompt="system",
            input_payload={},
            response_model=LocalDecision,
            request_context=_context(),
        )


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://example.com:11434",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
    ),
)
def test_ollama_endpoint_is_fail_closed_to_loopback(endpoint: str) -> None:
    with pytest.raises(ValueError):
        _normalize_loopback_endpoint(endpoint)


def test_default_adapter_registry_contains_ollama_without_cloud_credentials() -> None:
    registry = build_default_model_adapter_registry()

    assert registry.contains("gemini")
    assert registry.contains("openai")
    assert registry.contains("ollama")
    assert isinstance(registry.require("ollama"), OllamaStructuredOutputAdapter)


def test_c5_local_target_registry_exposes_only_admitted_capabilities() -> None:
    adapters = build_default_model_adapter_registry()
    targets = build_c5_local_target_registry(adapters)

    local = targets.require(C5_LOCAL_TARGET_ID)

    assert local.locality is ModelLocality.LOCAL
    assert local.model_id == "qwen3.5:4b"
    assert local.benchmark_status is BenchmarkStatus.ACCEPTED
    assert local.capabilities == (
        "bounded_planning",
        "classification_extraction",
        "summarization",
        "structured_output",
    )
    assert "engineering_reasoning" not in local.capabilities
    assert local.credential_ref is None
    assert local.cost_profile is not None
    assert local.cost_profile.input_usd_per_million_tokens == 0.0
    assert local.cost_profile.output_usd_per_million_tokens == 0.0


def test_existing_work_target_registry_stays_unchanged_by_c5_local_target(
    tmp_path: Path,
) -> None:
    adapters = build_default_model_adapter_registry()
    targets = build_default_work_targets(
        configured_provider="gemini",
        configured_model=None,
        adapter_registry=adapters,
    )

    assert {target.target_id for target in targets.registry.all()} == {
        "work.gemini.default",
        "work.openai.default",
    }

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    router = ModelRouter(
        target_registry=targets.registry,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=ModelRoutingStore(store),
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda _target: True,
        clock=lambda: 100.0,
    )
    request = RoutingRequest(
        routing_request_id="route-engineering",
        work_id="work-engineering",
        task_kind="development",
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=(
            "engineering_reasoning",
            "structured_output",
        ),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=1000,
        evidence_size_class=EvidenceSizeClass.SMALL,
        recent_progress_signals=(),
        recent_failure_signals=(),
        latency_preference="balanced",
        cost_preference="balanced",
        routing_features={"affinity_target_id": "work.gemini.default"},
    )

    selection = router.route(request)

    assert selection.target.target_id == "work.gemini.default"
    assert selection.decision.ordered_target_ids == (
        "work.gemini.default",
        "work.openai.default",
    )


@pytest.mark.asyncio
async def test_local_target_invokes_through_existing_model_invoker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url, payload, *, timeout):
        del url, payload, timeout
        return {"message": {"content": '{"decision":"local"}'}}

    monkeypatch.setattr(
        "jarvis.model_routing.ollama._post_json",
        fake_post,
    )
    registry = build_default_model_adapter_registry()
    invoker = ModelInvoker(registry)

    result = await invoker.invoke_structured(
        target=_local_target(),
        system_prompt="system",
        input_payload={"task": "bounded"},
        response_model=LocalDecision,
        request_context=_context(),
    )

    assert result == LocalDecision(decision="local")
