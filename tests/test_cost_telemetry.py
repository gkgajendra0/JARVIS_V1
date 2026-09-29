from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from jarvis.hands.provider_adapters import (
    GeminiStructuredOutputClient,
    OpenAIStructuredOutputClient,
)
from jarvis.model_routing.cost import (
    CostTelemetryReader,
    ProviderCostEvent,
    ProviderCostEventStore,
    estimate_profile_usage_cost_usd,
    summarize_cost_attempts,
)
from jarvis.model_routing.models import (
    CostProfile,
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
)
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


class DummyOutput(BaseModel):
    value: str


class FakeOpenAIResponses:
    async def parse(self, **kwargs):
        response_model = kwargs["text_format"]
        return SimpleNamespace(
            output_parsed=response_model(value="ok"),
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=30,
                total_tokens=150,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
            ),
        )


class FakeOpenAIClient:
    responses = FakeOpenAIResponses()


class FakeGeminiInteractions:
    async def create(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            output_text='{"value":"ok"}',
            usage=SimpleNamespace(
                total_input_tokens=200,
                total_output_tokens=40,
                total_tokens=260,
                total_cached_tokens=50,
                total_thought_tokens=20,
                total_tool_use_tokens=0,
            ),
        )


class FakeGeminiClient:
    aio = SimpleNamespace(interactions=FakeGeminiInteractions())


@pytest.mark.asyncio
async def test_openai_structured_adapter_normalizes_provider_usage() -> None:
    client = OpenAIStructuredOutputClient(
        client=FakeOpenAIClient(),
        model="gpt-test",
    )

    result = await client.parse_with_telemetry(
        system_prompt="system",
        input_payload={"hello": "world"},
        response_model=DummyOutput,
    )

    assert result.parsed == DummyOutput(value="ok")
    assert result.usage_observed is True
    assert result.usage == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cached_input_tokens": 20,
        "reasoning_tokens": 10,
    }


@pytest.mark.asyncio
async def test_gemini_structured_adapter_normalizes_provider_usage() -> None:
    client = GeminiStructuredOutputClient(
        client=FakeGeminiClient(),
        model="gemini-test",
    )

    result = await client.parse_with_telemetry(
        system_prompt="system",
        input_payload={"hello": "world"},
        response_model=DummyOutput,
    )

    assert result.parsed == DummyOutput(value="ok")
    assert result.usage_observed is True
    assert result.usage == {
        "input_tokens": 200,
        "output_tokens": 40,
        "total_tokens": 260,
        "cached_input_tokens": 50,
        "reasoning_tokens": 20,
        "tool_use_tokens": 0,
    }


def test_cost_estimator_requires_real_usage_and_price_profile() -> None:
    profile = CostProfile(
        profile_id="test",
        version=1,
        effective_from_epoch=1.0,
        input_usd_per_million_tokens=2.0,
        output_usd_per_million_tokens=10.0,
    )

    assert estimate_profile_usage_cost_usd(
        profile,
        {"input_tokens": 1_000, "output_tokens": 200},
    ) == pytest.approx(0.004)
    assert (
        estimate_profile_usage_cost_usd(
            profile,
            {"input_tokens": 1_000},
        )
        is None
    )


def _attempt(
    attempt_id: str,
    *,
    stage: str,
    provider: str,
    model: str,
    usage: dict[str, int] | None,
    cost: float | None,
    kind: RoutingAttemptKind = RoutingAttemptKind.PRIMARY,
    failure: str | None = None,
) -> RoutingAttempt:
    return RoutingAttempt(
        attempt_id=attempt_id,
        decision_id=f"decision-{attempt_id}",
        work_id="work-1",
        target_id=f"target-{attempt_id}",
        attempt_ordinal=1,
        started_at_epoch=1.0,
        ended_at_epoch=2.0,
        latency_ms=1_000.0,
        kind=kind,
        failure_class=failure,
        provider_id=provider,
        model_id=model,
        stage_key=stage,
        usage={} if usage is None else usage,
        usage_observed=usage is not None,
        estimated_cost_usd=cost,
        response_contract_result=ResponseContractResult.VALID,
    )


def test_provider_cost_event_store_rolls_non_token_cost_into_work_total(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = WorkItem(
        request="research current API behavior",
        work_type=WorkType.RESEARCH,
        source_session_id="session-cost",
        source_turn_id="turn-cost",
    )
    work_store.create(work)
    routing_store = ModelRoutingStore(work_store)
    provider_store = ProviderCostEventStore(work_store)
    provider_store.record(
        ProviderCostEvent(
            event_id="exa-search-1",
            work_id=work.work_id,
            provider_id="exa",
            service_key="search",
            cost_kind="search_request",
            quantity=1.0,
            unit_cost_usd=0.007,
            estimated_cost_usd=0.007,
            pricing_basis="Exa public endpoint pricing verified 2026-09-29",
            occurred_at_epoch=100.0,
            stage_key="research",
        )
    )

    report = CostTelemetryReader(
        routing_store,
        provider_cost_store=provider_store,
    ).for_work(work.work_id)

    assert report.attempt_count == 0
    assert report.provider_cost_event_count == 1
    assert report.known_model_cost_usd == 0
    assert report.known_provider_cost_usd == pytest.approx(0.007)
    assert report.known_estimated_cost_usd == pytest.approx(0.007)
    assert report.estimated_total_cost_usd == pytest.approx(0.007)
    assert report.provider_cost_breakdown[0].cost_kind == "search_request"


def test_cost_report_aggregates_and_never_treats_unknown_as_zero() -> None:
    attempts = (
        _attempt(
            "1",
            stage="research",
            provider="gemini",
            model="gemini-test",
            usage={"input_tokens": 100, "output_tokens": 20},
            cost=0.001,
        ),
        _attempt(
            "2",
            stage="development",
            provider="openai",
            model="gpt-test",
            usage=None,
            cost=None,
            kind=RoutingAttemptKind.FALLBACK,
            failure="rate_limited",
        ),
    )

    report = summarize_cost_attempts(
        scope_kind="work",
        scope_id="work-1",
        attempts=attempts,
    )

    assert report.attempt_count == 2
    assert report.fallback_attempts == 1
    assert report.failed_attempts == 1
    assert report.missing_usage_attempts == 1
    assert report.unpriced_attempts == 1
    assert report.aggregate_usage == {
        "input_tokens": 100.0,
        "output_tokens": 20.0,
    }
    assert report.known_estimated_cost_usd == pytest.approx(0.001)
    assert report.estimated_total_cost_usd is None
    assert len(report.breakdown) == 2
