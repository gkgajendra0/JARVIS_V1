import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from jarvis.model_routing.eligibility import EligibilityPolicy
from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    StructuredOutputModelAdapter,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
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
from jarvis.work.brain import (
    BrainAction,
    BrainCoordinator,
    BrainPreempted,
    BrainRequest,
    InteractiveBrainGate,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.reasoner import RoutedWorkReasoner
from jarvis.work.store import SQLiteWorkStore


class DummyResponse(BaseModel):
    value: str


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
    ) -> None:
        self.routing_store = routing_store
        self.block = block
        self.error = error
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
        del target, system_prompt, input_payload
        self.calls.append(request_context)
        if self.routing_store is not None:
            persisted = self.routing_store.get_decision(request_context.decision_id)
            assert persisted is not None
        if self.error is not None:
            raise self.error
        if self.block is not None:
            await self.block.wait()
        return response_model(
            action="do_step",
            summary="Execute bounded step",
            parameters={},
        )


def _routed_reasoner(
    tmp_path: Path,
    *,
    adapter: ReasoningAdapter | None = None,
    provider_id: str = "fake",
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
    )
    return work_store, routing_store, reasoner, selected_adapter


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
    assert len(adapter.calls) == 1
    persisted = routing_store.find_decision_by_request(
        expected_route.routing_request_id
    )
    assert persisted is not None
    attempts = routing_store.list_attempts(persisted.decision.decision_id)
    assert len(attempts) == 1
    assert attempts[0].target_id == "work.fake.default"


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
