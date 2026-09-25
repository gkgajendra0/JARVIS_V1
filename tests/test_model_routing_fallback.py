import asyncio
from pathlib import Path

import pytest

from jarvis.model_routing.eligibility import EligibilityPolicy, TargetHealthEligibility
from jarvis.model_routing.health import TargetHealthRecord
from jarvis.model_routing.invoker import ModelInvocationContext, ModelInvoker
from jarvis.model_routing.models import (
    BenchmarkStatus,
    ModelLocality,
    ModelTarget,
    RoutingAttemptKind,
    RoutingStrategyResult,
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
from jarvis.work.brain import BrainAction, BrainCoordinator, BrainRequest
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkDeliveryKind, WorkItem, WorkState, WorkType
from jarvis.work.reasoner import RoutedWorkReasoner
from jarvis.work.store import SQLiteWorkStore


class RateLimitError(RuntimeError):
    status_code = 429


class ServiceUnavailableError(RuntimeError):
    status_code = 503


class RequestRejectedError(RuntimeError):
    status_code = 400


class StaticEngineeringStrategy:
    strategy_key = "engineering_stage"
    strategy_version = 1
    strategy_digest = "d" * 64

    def rank(
        self,
        *,
        request,
        eligible_targets: tuple[ModelTarget, ...],
        history,
    ) -> RoutingStrategyResult:
        del request, history
        return RoutingStrategyResult(
            ordered_target_ids=tuple(
                target.target_id for target in eligible_targets
            ),
            reason_codes=("test_static_order",),
            selected_role="efficient",
        )


class ScriptedAdapter:
    adapter_id = "fake"

    def __init__(self, scripts: dict[str, list[object]]) -> None:
        self.scripts = {key: list(value) for key, value in scripts.items()}
        self.calls: list[tuple[str, ModelInvocationContext]] = []

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict,
        response_model,
        request_context: ModelInvocationContext,
    ):
        del system_prompt, input_payload
        self.calls.append((target.target_id, request_context))
        script = self.scripts.setdefault(target.target_id, [])
        behavior = script.pop(0) if script else "ok"
        if isinstance(behavior, BaseException):
            raise behavior
        if isinstance(behavior, asyncio.Event):
            await behavior.wait()
        return response_model(
            action="do_step",
            summary="Execute bounded step",
            parameters={},
        )


class NeverUsedExecutor:
    descriptor = BrainAction(
        name="do_step",
        description="Execute one bounded step",
        parameter_schema={"type": "object"},
    )
    work_types = frozenset({WorkType.GENERIC})

    async def execute(self, *, work: WorkItem, parameters: dict):
        del work, parameters
        raise AssertionError("executor must not run while routing is blocked")


class BlockerReasoner:
    async def decide(self, request: BrainRequest):
        del request
        raise RoutingResourceBlocked(
            decision_id="decision-blocked",
            reason="approved reasoning targets are unavailable",
            retry_after_seconds=17.0,
        )


def _target(target_id: str) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id="fake",
        provider_id=target_id,
        model_id=f"{target_id}-model",
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


def _work(store: SQLiteWorkStore, *, turn: str = "turn-fallback") -> WorkItem:
    work = WorkItem(
        request="Perform a bounded routed step",
        work_type=WorkType.GENERIC,
        source_session_id="session-fallback",
        source_turn_id=turn,
    )
    store.create(work)
    return work


def _brain_request(work: WorkItem) -> BrainRequest:
    return BrainRequest(
        work=work,
        recent_steps=(),
        purpose="Choose one bounded step",
        allowed_actions=(
            BrainAction(
                name="do_step",
                description="Execute one bounded step",
                parameter_schema={"type": "object"},
            ),
        ),
    )


def _reasoner(
    *,
    work_store: SQLiteWorkStore,
    routing_store: ModelRoutingStore,
    adapter: ScriptedAdapter,
    clock=lambda: 100.0,
) -> RoutedWorkReasoner:
    adapters = ModelAdapterRegistry((adapter,))
    targets = ModelTargetRegistry(
        adapters,
        (_target("target-a"), _target("target-b")),
    )
    router = ModelRouter(
        target_registry=targets,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((StaticEngineeringStrategy(),)),
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda target: True,
        clock=clock,
        fallback_budget=1,
    )
    return RoutedWorkReasoner(
        router=router,
        invoker=ModelInvoker(adapters),
        primary_target_id="target-a",
        clock=clock,
    )


@pytest.mark.asyncio
async def test_429_cools_primary_and_falls_back_with_same_work_identity(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    adapter = ScriptedAdapter(
        {
            "target-a": [RateLimitError("rate limited")],
            "target-b": ["ok"],
        }
    )
    reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=adapter,
    )
    work = _work(work_store)
    request = _brain_request(work)

    decision = await reasoner.decide(request)

    assert decision.action == "do_step"
    assert [target for target, _ in adapter.calls] == ["target-a", "target-b"]
    route = routing_store.find_decision_by_request(
        build_work_routing_request(
            request,
            primary_target_id="target-a",
        ).routing_request_id
    )
    assert route is not None
    attempts = routing_store.list_attempts(route.decision.decision_id)
    assert [attempt.work_id for attempt in attempts] == [work.work_id, work.work_id]
    assert [attempt.kind for attempt in attempts] == [
        RoutingAttemptKind.PRIMARY,
        RoutingAttemptKind.FALLBACK,
    ]
    assert attempts[0].failure_class == "rate_limited"
    assert attempts[1].failure_class is None

    health = routing_store.get_health("target-a")
    assert health is not None
    assert health.state is TargetHealthEligibility.COOLDOWN


@pytest.mark.asyncio
async def test_transient_failure_gets_one_bounded_same_target_retry_then_fallback(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    adapter = ScriptedAdapter(
        {
            "target-a": [
                ServiceUnavailableError("down"),
                ServiceUnavailableError("still down"),
            ],
            "target-b": ["ok"],
        }
    )
    reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=adapter,
    )
    work = _work(work_store)

    decision = await reasoner.decide(_brain_request(work))

    assert decision.action == "do_step"
    assert [target for target, _ in adapter.calls] == [
        "target-a",
        "target-a",
        "target-b",
    ]
    health = routing_store.get_health("target-a")
    assert health is not None
    assert health.state is TargetHealthEligibility.COOLDOWN


@pytest.mark.asyncio
async def test_fallback_budget_exhaustion_surfaces_typed_resource_blocker(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    adapter = ScriptedAdapter(
        {
            "target-a": [RateLimitError("a limited")],
            "target-b": [RateLimitError("b limited")],
        }
    )
    reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=adapter,
    )
    work = _work(work_store)

    with pytest.raises(RoutingResourceBlocked) as caught:
        await reasoner.decide(_brain_request(work))

    assert caught.value.decision_id is not None
    assert [target for target, _ in adapter.calls] == ["target-a", "target-b"]
    attempts = routing_store.list_attempts(caught.value.decision_id)
    assert len(attempts) == 2
    assert {attempt.work_id for attempt in attempts} == {work.work_id}


@pytest.mark.asyncio
async def test_request_rejection_fails_closed_without_provider_hopping(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    adapter = ScriptedAdapter(
        {
            "target-a": [RequestRejectedError("request rejected")],
            "target-b": ["ok"],
        }
    )
    reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=adapter,
    )
    work = _work(work_store)

    with pytest.raises(RequestRejectedError):
        await reasoner.decide(_brain_request(work))

    assert [target for target, _ in adapter.calls] == ["target-a"]


@pytest.mark.asyncio
async def test_restart_resumes_existing_fallback_lineage_without_duplicate_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite"
    work_store = SQLiteWorkStore(path)
    routing_store = ModelRoutingStore(work_store)
    fallback_block = asyncio.Event()
    first_adapter = ScriptedAdapter(
        {
            "target-a": [RateLimitError("rate limited")],
            "target-b": [fallback_block],
        }
    )
    first_reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=first_adapter,
    )
    work = _work(work_store)
    request = _brain_request(work)
    route_request = build_work_routing_request(
        request,
        primary_target_id="target-a",
    )

    task = asyncio.create_task(first_reasoner.decide(request))
    for _ in range(200):
        if len(first_adapter.calls) >= 2:
            break
        await asyncio.sleep(0.001)
    assert [target for target, _ in first_adapter.calls] == [
        "target-a",
        "target-b",
    ]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    reopened_work = SQLiteWorkStore(path)
    reopened_routing = ModelRoutingStore(reopened_work)
    second_adapter = ScriptedAdapter({"target-b": ["ok"]})
    second_reasoner = _reasoner(
        work_store=reopened_work,
        routing_store=reopened_routing,
        adapter=second_adapter,
    )

    decision = await second_reasoner.decide(request)

    assert decision.action == "do_step"
    assert [target for target, _ in second_adapter.calls] == ["target-b"]
    route = reopened_routing.find_decision_by_request(
        route_request.routing_request_id
    )
    assert route is not None
    attempts = reopened_routing.list_attempts(route.decision.decision_id)
    assert [attempt.attempt_ordinal for attempt in attempts] == [1, 2]
    assert [attempt.target_id for attempt in attempts] == ["target-a", "target-b"]
    with reopened_work.extension_transaction() as connection:
        decision_count = connection.execute(
            """
            SELECT COUNT(*) FROM model_routing_decisions
            WHERE routing_request_id = ?
            """,
            (route_request.routing_request_id,),
        ).fetchone()[0]
        work_count = connection.execute(
            "SELECT COUNT(*) FROM work_items WHERE work_id = ?",
            (work.work_id,),
        ).fetchone()[0]
    assert decision_count == 1
    assert work_count == 1


@pytest.mark.asyncio
async def test_all_targets_in_cooldown_fail_before_invocation(
    tmp_path: Path,
) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    for target_id in ("target-a", "target-b"):
        routing_store.create_health(
            TargetHealthRecord(
                target_id=target_id,
                state=TargetHealthEligibility.COOLDOWN,
                consecutive_failures=1,
                cooldown_until_epoch=200.0,
                last_failure_kind="rate_limited",
                updated_at_epoch=100.0,
                version=1,
            )
        )
    adapter = ScriptedAdapter({})
    reasoner = _reasoner(
        work_store=work_store,
        routing_store=routing_store,
        adapter=adapter,
    )
    work = _work(work_store)

    with pytest.raises(RoutingResourceBlocked) as caught:
        await reasoner.decide(_brain_request(work))

    assert caught.value.routing_request_id is not None
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_work_engine_turns_routing_blocker_into_waiting_resource_delivery(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _work(store, turn="turn-engine-blocker")
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(BlockerReasoner()),
        actions=WorkActionRegistry((NeverUsedExecutor(),)),
    )

    result = await engine.advance(work.work_id)

    assert result.work_id == work.work_id
    assert result.state is WorkState.WAITING_RESOURCE
    assert result.retry_after_seconds == 17.0
    persisted = store.require(work.work_id)
    assert persisted.state is WorkState.WAITING_RESOURCE
    assert persisted.status_detail == "approved reasoning targets are unavailable"
    steps = store.list_steps(work.work_id)
    assert steps[-1].kind == "routing_resource_blocker"
    deliveries = store.list_pending_deliveries()
    assert len(deliveries) == 1
    assert deliveries[0].kind is WorkDeliveryKind.RESOURCE_BLOCKER
    assert deliveries[0].work_id == work.work_id
