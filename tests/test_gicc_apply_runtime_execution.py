from pathlib import Path

import pytest

from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
)
from jarvis.goal_intelligence.execution import GoalPlanDispatcher
from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.service import GoalOrchestrator
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeCapabilityRuntime:
    def __init__(self) -> None:
        self.requests = []
        self.refreshes = 0

    def refresh_catalog(self):
        self.refreshes += 1

    def execute(self, request):
        self.requests.append(request)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=request.capability_key,
            operation=request.operation,
            data={
                "opened": True,
                "verification_passed": True,
            },
            provenance=("fake-runtime",),
        )


class StaticCoordinator:
    def __init__(self, result: GoalIntakeResult) -> None:
        self.result = result

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        return self.result

    async def continue_goal(self, goal_id: str):
        del goal_id
        return self.result


class CapabilityContinuationCoordinator:
    def __init__(self, store: GoalStore) -> None:
        self.store = store
        self.calls = 0

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        raise AssertionError("pursue is not used in this test")

    async def continue_goal(self, goal_id: str) -> GoalIntakeResult:
        self.calls += 1
        current = self.store.get_goal(goal_id)
        assert current is not None
        planned = self.store.update_goal_state(
            current.goal_id,
            GoalState.PLANNED,
            expected_revision=current.goal_revision,
        )
        plan = _put_plan(self.store, planned)
        return GoalIntakeResult(
            disposition=GoalIntakeDisposition.PLAN_READY,
            goal=planned,
            plan=plan,
        )


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"r" * 32),
        )
    )


def _goal(store: GoalStore, *, state: GoalState) -> OwnerGoalV2:
    return store.create_goal(
        OwnerGoalV2.create(
            source_session_id="runtime-session",
            source_turn_id="runtime-turn",
            exact_owner_request="Open Calculator.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Calculator is open.",
            completion_predicates=("app_open",),
            state=state,
            created_at="2026-10-01T18:10:00+00:00",
        )
    )


def _put_plan(store: GoalStore, goal: OwnerGoalV2) -> PlanGraphV1:
    action = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:{goal.goal_revision}",
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Open Calculator.",
        capability_key="app:lifecycle",
        operation="open_app",
        parameters={"app": "Calculator"},
        postcondition_ref="app_open",
    )
    verify = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:{goal.goal_revision}",
        ordinal=1,
        node_type=PlanNodeType.VERIFY,
        summary="Verify Calculator opened.",
        postcondition_ref="app_open",
    )
    return store.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            plan_revision=1,
            nodes=(action, verify),
            edges=((action.node_id, verify.node_id),),
            root_node_ids=(action.node_id,),
            completion_node_ids=(verify.node_id,),
            created_at="2026-10-01T18:11:00+00:00",
        )
    )


def _runtime(
    store: GoalStore,
    coordinator,
    capability_runtime: FakeCapabilityRuntime,
) -> GiccApplyRuntime:
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=capability_runtime,
        ),
    )
    return GiccApplyRuntime(
        store=store,
        world=object(),  # type: ignore[arg-type]
        coordinator=coordinator,  # type: ignore[arg-type]
        dispatcher=dispatcher,
        telemetry=CapturingGiccTelemetry(),
        capability_runtime=capability_runtime,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_foreground_plan_ready_goal_reaches_verified_completion(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.PLANNED)
    plan = _put_plan(store, goal)
    capability_runtime = FakeCapabilityRuntime()
    runtime = _runtime(
        store,
        StaticCoordinator(
            GoalIntakeResult(
                disposition=GoalIntakeDisposition.PLAN_READY,
                goal=goal,
                plan=plan,
            )
        ),
        capability_runtime,
    )

    result = await runtime.pursue(conversation=object(), turn=object())

    assert result.goal is not None
    assert result.goal.state is GoalState.COMPLETED
    assert result.plan is not None
    assert result.plan.state is PlanState.SUCCEEDED
    assert len(capability_runtime.requests) == 1


@pytest.mark.asyncio
async def test_background_capability_continuation_uses_same_dispatcher(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    capability_runtime = FakeCapabilityRuntime()
    coordinator = CapabilityContinuationCoordinator(store)
    runtime = _runtime(store, coordinator, capability_runtime)

    advanced = await runtime.reconcile_once()

    latest_goal = store.get_goal(goal.goal_id)
    latest_plan = store.latest_plan_for_goal(goal.goal_id)
    assert advanced == 1
    assert coordinator.calls == 1
    assert capability_runtime.refreshes == 1
    assert latest_goal is not None
    assert latest_goal.state is GoalState.COMPLETED
    assert latest_plan is not None
    assert latest_plan.state is PlanState.SUCCEEDED
    assert len(capability_runtime.requests) == 1
