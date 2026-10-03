import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from jarvis.chatgpt_plan import ChatGPTPlanHTTPError
from jarvis.hands.provider_adapters import StructuredOutputTelemetry
from jarvis.model_routing.cost import CostTelemetryReader
from jarvis.model_routing.eligibility import EligibilityPolicy
from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    StructuredOutputModelAdapter,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    CostProfile,
    ModelLocality,
    ModelTarget,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import (
    ModelRouter,
    RoutingResourceBlocked,
    build_work_routing_request,
)
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.model_routing.strategy import EngineeringStageStrategy
from jarvis.provider_circuit import BackgroundProviderCircuitRegistry
from jarvis.work.brain import (
    BrainAction,
    BrainCoordinator,
    BrainPreempted,
    BrainRequest,
    InteractiveBrainGate,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.reasoner import (
    _SYSTEM_PROMPT,
    _WorkDecisionModel,
    RoutedWorkReasoner,
    evaluate_structured_work_request,
)
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore


class DummyResponse(BaseModel):
    value: str


def _schema_nodes(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _schema_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _schema_nodes(nested)


def test_work_decision_schema_is_strict_output_compatible() -> None:
    schema = _WorkDecisionModel.model_json_schema()

    for node in _schema_nodes(schema):
        assert "default" not in node
        if node.get("type") != "object":
            continue
        assert node.get("additionalProperties") is False
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert set(node.get("required", ())) == set(properties)


def test_work_reasoner_never_uses_owner_as_execution_fallback() -> None:
    normalized = " ".join(_SYSTEM_PROMPT.split())

    assert (
        "Owner input is a constitutional boundary, not an execution tool" in normalized
    )
    assert "open an app, click, search, inspect a UI, run a command" in normalized
    assert "A missing automation capability remains a capability gap" in normalized
    assert "owner labor must not be used as a substitute" in normalized


class FakeStructuredClient:
    def __init__(self, *, provider: str, model: str) -> None:
        self.provider_name = provider
        self.model_name = model
        self.calls = []

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
    ) -> BaseModel:
        self.calls.append((system_prompt, input_payload, response_model))
        return response_model(value="ok")


class FakeWorkDecisionClient:
    provider_name = "fake"
    model_name = "fake-work-model"

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        assert system_prompt == _SYSTEM_PROMPT
        assert input_payload["work"]["type"] == "development"
        return StructuredOutputTelemetry(
            parsed=response_model(
                action="do_step",
                summary="Execute the bounded step.",
                parameters_json='{"value":1}',
                goal_complete=False,
                needs_owner=False,
                owner_question=None,
            ),
            usage={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
            usage_observed=True,
            latency_ms=12.5,
        )


@pytest.mark.asyncio
async def test_structured_work_evaluator_does_not_execute_or_route(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "evaluator.sqlite")
    work = _work(store)
    request = _brain_request(work)

    decision, telemetry = await evaluate_structured_work_request(
        FakeWorkDecisionClient(),
        request,
    )

    assert decision.action == "do_step"
    assert decision.parameters == {"value": 1}
    assert decision.goal_complete is False
    assert decision.needs_owner is False
    assert telemetry.usage["total_tokens"] == 50
    assert store.list_steps(work.work_id) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["gemini", "openai"])
async def test_existing_provider_clients_work_through_model_adapter(
    provider: str,
) -> None:
    clients: list[FakeStructuredClient] = []

    def factory(provider_id: str, model_id: str):
        client = FakeStructuredClient(provider=provider_id, model=model_id)
        clients.append(client)
        return client

    adapter = StructuredOutputModelAdapter(
        adapter_id=provider,
        provider_id=provider,
        client_factory=factory,
    )
    registry = ModelAdapterRegistry((adapter,))
    invoker = ModelInvoker(registry)
    target = _target(
        "target-a",
        adapter_id=provider,
        provider_id=provider,
        model_id=f"{provider}-model",
    )
    context = ModelInvocationContext(
        work_id="work-1",
        routing_request_id="route-1",
        decision_id="decision-1",
        attempt_id="attempt-1",
        correlation_key="corr-1",
    )

    result = await invoker.invoke_structured(
        target=target,
        system_prompt="system",
        input_payload={"hello": "world"},
        response_model=DummyResponse,
        request_context=context,
    )

    assert result == DummyResponse(value="ok")
    assert len(clients) == 1
    assert len(clients[0].calls) == 1


def _target(
    target_id: str,
    *,
    adapter_id: str = "fake",
    provider_id: str = "fake",
    model_id: str = "fake-model",
    cost_profile: CostProfile | None = None,
) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id=adapter_id,
        provider_id=provider_id,
        model_id=model_id,
        locality=ModelLocality.LOCAL,
        capabilities=("engineering_reasoning", "structured_output"),
        roles=("efficient", "capable"),
        max_context_tokens=32_000,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="standard",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
        credential_ref=None,
        cost_profile=cost_profile,
    )


def _work(store: SQLiteWorkStore) -> WorkItem:
    work = WorkItem(
        request="Perform a bounded engineering step",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-route",
        source_turn_id="turn-route",
    )
    store.create(work)
    return work


def _brain_request(work: WorkItem) -> BrainRequest:
    return BrainRequest(
        work=work,
        recent_steps=(),
        purpose="Choose the next bounded step",
        allowed_actions=(
            BrainAction(
                name="do_step",
                description="Execute one bounded step",
                parameter_schema={"type": "object"},
            ),
        ),
    )


class ReasoningAdapter:
    adapter_id = "fake"

    def __init__(
        self,
        *,
        routing_store: ModelRoutingStore | None = None,
        block: asyncio.Event | None = None,
        error: Exception | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.routing_store = routing_store
        self.block = block
        self.error = error
        self.usage = usage
        self.calls: list[ModelInvocationContext] = []

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> BaseModel:
        result = await self.invoke_structured_with_telemetry(
            target=target,
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
            request_context=request_context,
        )
        return result.parsed

    async def invoke_structured_with_telemetry(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> StructuredOutputTelemetry:
        del target, system_prompt, input_payload
        self.calls.append(request_context)
        if self.routing_store is not None:
            persisted = self.routing_store.get_decision(request_context.decision_id)
            assert persisted is not None
        if self.error is not None:
            raise self.error
        if self.block is not None:
            await self.block.wait()
        parsed = response_model(
            action="do_step",
            summary="Execute bounded step",
            parameters_json="{}",
            goal_complete=False,
            needs_owner=False,
            owner_question=None,
        )
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage={} if self.usage is None else self.usage,
            usage_observed=self.usage is not None,
            latency_ms=1.0,
        )


def _routed_reasoner(
    tmp_path: Path,
    *,
    adapter: ReasoningAdapter | None = None,
    provider_id: str = "fake",
    cost_profile: CostProfile | None = None,
    resources: ResourceLeaseManager | None = None,
) -> tuple[
    SQLiteWorkStore,
    ModelRoutingStore,
    RoutedWorkReasoner,
    ReasoningAdapter,
]:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    selected_adapter = adapter or ReasoningAdapter(routing_store=routing_store)
    selected_adapter.routing_store = routing_store
    adapters = ModelAdapterRegistry((selected_adapter,))
    targets = ModelTargetRegistry(
        adapters,
        (
            _target(
                "work.fake.default",
                adapter_id="fake",
                provider_id=provider_id,
                cost_profile=cost_profile,
            ),
        ),
    )
    router = ModelRouter(
        target_registry=targets,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda target: True,
        clock=lambda: 100.0,
    )
    reasoner = RoutedWorkReasoner(
        router=router,
        invoker=ModelInvoker(adapters),
        primary_target_id="work.fake.default",
        clock=lambda: 101.0,
        resources=resources,
        resource_keys=(() if resources is None else ("provider_api",)),
    )
    return work_store, routing_store, reasoner, selected_adapter


@pytest.mark.asyncio
async def test_shared_provider_resource_serializes_parallel_reasoning(
    tmp_path: Path,
) -> None:
    class ConcurrencyAdapter(ReasoningAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0

        async def invoke_structured_with_telemetry(
            self,
            *,
            target: ModelTarget,
            system_prompt: str,
            input_payload: dict,
            response_model: type[BaseModel],
            request_context: ModelInvocationContext,
        ) -> StructuredOutputTelemetry:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().invoke_structured_with_telemetry(
                    target=target,
                    system_prompt=system_prompt,
                    input_payload=input_payload,
                    response_model=response_model,
                    request_context=request_context,
                )
            finally:
                self.active -= 1

    resources = ResourceLeaseManager({"provider_api": 1})
    adapter = ConcurrencyAdapter()
    work_store, _, reasoner, _ = _routed_reasoner(
        tmp_path,
        adapter=adapter,
        resources=resources,
    )
    first = _work(work_store)
    second = WorkItem(
        request="Perform another bounded engineering step",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-route",
        source_turn_id="turn-route-2",
    )
    work_store.create(second)

    await asyncio.gather(
        reasoner.decide(_brain_request(first)),
        reasoner.decide(_brain_request(second)),
    )

    assert len(adapter.calls) == 2
    assert adapter.max_active == 1


@pytest.mark.asyncio
async def test_router_persists_decision_before_provider_invocation(
    tmp_path: Path,
) -> None:
    work_store, routing_store, reasoner, adapter = _routed_reasoner(tmp_path)
    work = _work(work_store)
    request = _brain_request(work)
    expected_route = build_work_routing_request(
        request,
        primary_target_id="work.fake.default",
    )

    decision = await reasoner.decide(request)

    assert decision.action == "do_step"
    assert decision.parameters == {}
    assert len(adapter.calls) == 1
    persisted = routing_store.find_decision_by_request(
        expected_route.routing_request_id
    )
    assert persisted is not None
    attempts = routing_store.list_attempts(persisted.decision.decision_id)
    assert len(attempts) == 1
    assert attempts[0].target_id == "work.fake.default"


@pytest.mark.asyncio
async def test_routed_work_persists_usage_and_cost_telemetry(
    tmp_path: Path,
) -> None:
    usage = {
        "input_tokens": 1_000,
        "output_tokens": 200,
        "total_tokens": 1_200,
        "cached_input_tokens": 100,
        "reasoning_tokens": 50,
    }
    adapter = ReasoningAdapter(usage=usage)
    profile = CostProfile(
        profile_id="fake-2026-09",
        version=1,
        effective_from_epoch=1.0,
        input_usd_per_million_tokens=2.0,
        output_usd_per_million_tokens=10.0,
    )
    work_store, routing_store, reasoner, _ = _routed_reasoner(
        tmp_path,
        adapter=adapter,
        provider_id="openai",
        cost_profile=profile,
    )
    work = _work(work_store)

    await reasoner.decide(_brain_request(work))

    attempts = routing_store.list_attempts_for_work(work.work_id)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.provider_id == "openai"
    assert attempt.model_id == "fake-model"
    assert attempt.stage_key == "development"
    assert attempt.usage_observed is True
    assert attempt.usage["input_tokens"] == 1_000
    assert attempt.usage["output_tokens"] == 200
    report = CostTelemetryReader(routing_store).for_work(work.work_id)
    assert report.attempt_count == 1
    assert report.missing_usage_attempts == 0
    assert report.unpriced_attempts == 0
    assert report.estimated_total_cost_usd == pytest.approx(0.004)
    assert report.breakdown[0].stage_key == "development"


@pytest.mark.asyncio
async def test_same_reasoning_cycle_reuses_one_route_decision(
    tmp_path: Path,
) -> None:
    work_store, routing_store, reasoner, adapter = _routed_reasoner(tmp_path)
    work = _work(work_store)
    request = _brain_request(work)
    route_request = build_work_routing_request(
        request,
        primary_target_id="work.fake.default",
    )

    await reasoner.decide(request)
    first = routing_store.find_decision_by_request(route_request.routing_request_id)
    assert first is not None

    await reasoner.decide(request)
    second = routing_store.find_decision_by_request(route_request.routing_request_id)
    assert second is not None
    assert second.decision.decision_id == first.decision.decision_id

    with work_store.extension_transaction() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) FROM model_routing_decisions
            WHERE routing_request_id = ?
            """,
            (route_request.routing_request_id,),
        ).fetchone()[0]
    assert count == 1
    assert len(adapter.calls) == 2
    assert len(routing_store.list_attempts(first.decision.decision_id)) == 2


@pytest.mark.asyncio
async def test_model_invoker_never_selects_a_different_target() -> None:
    called: list[str] = []

    class TargetEchoAdapter:
        adapter_id = "fake"

        async def invoke_structured(
            self,
            *,
            target: ModelTarget,
            system_prompt: str,
            input_payload: dict,
            response_model: type[BaseModel],
            request_context: ModelInvocationContext,
        ) -> BaseModel:
            del system_prompt, input_payload, request_context
            called.append(target.target_id)
            return response_model(value=target.target_id)

    invoker = ModelInvoker(ModelAdapterRegistry((TargetEchoAdapter(),)))
    selected = _target("selected")
    result = await invoker.invoke_structured(
        target=selected,
        system_prompt="system",
        input_payload={},
        response_model=DummyResponse,
        request_context=ModelInvocationContext(
            work_id="work-1",
            routing_request_id="route-1",
            decision_id="decision-1",
            attempt_id="attempt-1",
            correlation_key="corr-1",
        ),
    )

    assert called == ["selected"]
    assert result.value == "selected"


@pytest.mark.asyncio
async def test_interactive_voice_still_preempts_routed_background_reasoning(
    tmp_path: Path,
) -> None:
    blocker = asyncio.Event()
    adapter = ReasoningAdapter(block=blocker)
    work_store, _, reasoner, _ = _routed_reasoner(
        tmp_path,
        adapter=adapter,
    )
    work = _work(work_store)
    request = _brain_request(work)
    gate = InteractiveBrainGate()
    brain = BrainCoordinator(reasoner, interactive_gate=gate)

    task = asyncio.create_task(brain.decide(request))
    for _ in range(100):
        if adapter.calls:
            break
        await asyncio.sleep(0.001)
    assert adapter.calls

    gate.set_interactive_active(True)
    with pytest.raises(BrainPreempted):
        await task


@pytest.mark.asyncio
async def test_chatgpt_plan_subscription_limit_falls_back_to_paid_provider(
    tmp_path: Path,
) -> None:
    class PlanAdapter(ReasoningAdapter):
        adapter_id = "chatgpt_plan"

    class GeminiAdapter(ReasoningAdapter):
        adapter_id = "gemini"

    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    plan_adapter = PlanAdapter(
        routing_store=routing_store,
        error=ChatGPTPlanHTTPError(
            (
                "The ChatGPT user has reached their Subscription Sharing usage "
                "limit. Ask the user to try again after their usage limit resets "
                "or use an API key instead."
            ),
            code="subscription_sharing_usage_limit_exceeded",
        ),
    )
    fallback_adapter = GeminiAdapter(routing_store=routing_store)
    adapters = ModelAdapterRegistry((plan_adapter, fallback_adapter))
    targets = ModelTargetRegistry(
        adapters,
        (
            _target(
                "work.chatgpt_plan.default",
                adapter_id="chatgpt_plan",
                provider_id="chatgpt_plan",
            ),
            _target(
                "work.gemini.default",
                adapter_id="gemini",
                provider_id="gemini",
            ),
        ),
    )
    router = ModelRouter(
        target_registry=targets,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda target: True,
        clock=lambda: 100.0,
    )
    reasoner = RoutedWorkReasoner(
        router=router,
        invoker=ModelInvoker(adapters),
        primary_target_id="work.chatgpt_plan.default",
        clock=lambda: 101.0,
    )
    work = _work(work_store)
    request = _brain_request(work)

    decision = await reasoner.decide(request)

    assert decision.action == "do_step"
    assert len(plan_adapter.calls) == 1
    assert len(fallback_adapter.calls) == 1
    route_request = build_work_routing_request(
        request,
        primary_target_id="work.chatgpt_plan.default",
    )
    persisted = routing_store.find_decision_by_request(route_request.routing_request_id)
    assert persisted is not None
    attempts = routing_store.list_attempts(persisted.decision.decision_id)
    assert [attempt.target_id for attempt in attempts] == [
        "work.chatgpt_plan.default",
        "work.gemini.default",
    ]
    assert attempts[0].failure_class == "quota_exhausted"
    assert attempts[1].failure_class is None


@pytest.mark.asyncio
async def test_single_target_rate_limit_becomes_routing_resource_blocker(
    tmp_path: Path,
) -> None:
    class RateLimitError(RuntimeError):
        status_code = 429

    adapter = ReasoningAdapter(error=RateLimitError("rate limited"))
    work_store, routing_store, reasoner, _ = _routed_reasoner(
        tmp_path,
        adapter=adapter,
        provider_id="gemini",
    )
    work = _work(work_store)
    request = _brain_request(work)

    with pytest.raises(RoutingResourceBlocked) as caught:
        await reasoner.decide(request)

    assert caught.value.decision_id is not None
    route_request = build_work_routing_request(
        request,
        primary_target_id="work.fake.default",
    )
    persisted = routing_store.find_decision_by_request(route_request.routing_request_id)
    assert persisted is not None
    attempts = routing_store.list_attempts(persisted.decision.decision_id)
    assert len(attempts) == 1
    assert attempts[0].failure_class == "rate_limited"


@pytest.mark.asyncio
async def test_routed_reasoner_honors_shared_circuit_before_same_target_retry(
    tmp_path: Path,
) -> None:
    class ServiceUnavailable(RuntimeError):
        status_code = 503

    now = 1000.0
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    adapter = ReasoningAdapter(
        routing_store=routing_store,
        error=ServiceUnavailable("503 temporarily unavailable"),
    )
    adapters = ModelAdapterRegistry((adapter,))
    targets = ModelTargetRegistry(
        adapters,
        (_target("work.fake.default"),),
    )
    router = ModelRouter(
        target_registry=targets,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda target: True,
        clock=lambda: now,
    )
    circuits = BackgroundProviderCircuitRegistry(
        path=tmp_path / "provider-circuits.json",
        clock=lambda: now,
    )
    reasoner = RoutedWorkReasoner(
        router=router,
        invoker=ModelInvoker(adapters),
        primary_target_id="work.fake.default",
        clock=lambda: now,
        provider_circuit_registry=circuits,
    )

    with pytest.raises(RoutingResourceBlocked):
        await reasoner.decide(_brain_request(_work(work_store)))

    assert len(adapter.calls) == 1
    circuit = circuits.circuit("fake:fake-model")
    assert circuit.allow_request() is False
    assert circuit.failed_attempts == 1
