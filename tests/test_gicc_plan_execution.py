from pathlib import Path

import pytest

from tests.test_gicc_planning import _catalog, _valid_proposal

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.execution import (
    GoalPlanDispatcher,
    PlanDispatchDisposition,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    OwnerGoalV2,
    PlanNodeState,
    PlanState,
)
from jarvis.goal_intelligence.planning import (
    PlanValidationContext,
    PlanValidator,
)
from jarvis.goal_intelligence.service import GoalOrchestrator, VerificationRegistry
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeRuntime:
    def __init__(self, *, opened: bool = True) -> None:
        self.opened = opened
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=request.capability_key,
            operation=request.operation,
            data={
                "opened": self.opened,
                "verification_passed": self.opened,
            },
            provenance=("fake-runtime",),
        )


def _store(tmp_path: Path) -> tuple[GoalStore, OwnerGoalV2]:
    store = GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"x" * 32),
        )
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-exec",
            source_turn_id="turn-exec",
            exact_owner_request="Open Calculator.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Open Calculator.",
            completion_predicates=("app_open",),
            created_at="2026-10-01T15:10:00+00:00",
        )
    )
    return store, goal


def _plan(store: GoalStore, goal: OwnerGoalV2, revision: int = 1):
    context = PlanValidationContext(
        catalog=_catalog(),
        allowed_capability_operations=(("app:lifecycle", "open_app"),),
        allowed_postcondition_refs=("app_open",),
    )
    plan = PlanValidator().validate(
        goal=goal,
        proposal=_valid_proposal(),
        context=context,
        plan_revision=revision,
        created_at=f"2026-10-01T15:{10 + revision:02d}:00+00:00",
    )
    return store.put_plan(plan)


def _verification_registry(pass_value: bool) -> VerificationRegistry:
    registry = VerificationRegistry()

    def app_open(evidence):
        if not pass_value:
            return False
        results = evidence.get("results", ())
        return any(
            isinstance(item, dict)
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("data", {}).get("opened") is True
            for item in results
        )

    registry.register("app_open", app_open)
    return registry


@pytest.mark.asyncio
async def test_action_then_registered_verify_completes_plan(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    runtime = FakeRuntime(opened=True)
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=runtime,
            verification_registry=_verification_registry(True),
        ),
    )

    action = dispatcher.ready_nodes(plan)[0]
    action_result = await dispatcher.dispatch(
        plan_id=plan.plan_id,
        node_id=action.node_id,
        session_id="runtime-session",
        state_fingerprint="desktop-before",
    )
    assert action_result.disposition is PlanDispatchDisposition.SUCCEEDED
    assert runtime.requests[0].origin is ActionOrigin.MODEL_SUGGESTED

    verify = dispatcher.ready_nodes(action_result.plan)[0]
    verified = await dispatcher.dispatch(
        plan_id=plan.plan_id,
        node_id=verify.node_id,
        session_id="runtime-session",
    )

    assert verified.disposition is PlanDispatchDisposition.SUCCEEDED
    assert verified.plan.state is PlanState.SUCCEEDED


@pytest.mark.asyncio
async def test_default_verifier_accepts_only_bound_verified_executor_evidence(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    runtime = FakeRuntime(opened=True)
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=runtime,
        ),
    )

    action = dispatcher.ready_nodes(plan)[0]
    action_result = await dispatcher.dispatch(
        plan_id=plan.plan_id,
        node_id=action.node_id,
        session_id="runtime-session",
        state_fingerprint="desktop-before",
    )
    action_evidence = store.list_plan_node_results(
        plan_id=plan.plan_id,
        node_id=action.node_id,
    )
    assert action_evidence[-1]["payload"]["postcondition_ref"] == "app_open"

    assert runtime.requests

    verify = dispatcher.ready_nodes(action_result.plan)[0]
    verified = await dispatcher.dispatch(
        plan_id=plan.plan_id,
        node_id=verify.node_id,
        session_id="runtime-session",
    )

    assert verified.disposition is PlanDispatchDisposition.SUCCEEDED
    assert verified.plan.state is PlanState.SUCCEEDED


@pytest.mark.asyncio
async def test_failed_verification_blocks_same_action_after_replan(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    first_plan = _plan(store, goal, revision=1)
    runtime = FakeRuntime(opened=False)
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=runtime,
            verification_registry=_verification_registry(False),
        ),
    )
    action = dispatcher.ready_nodes(first_plan)[0]
    action_result = await dispatcher.dispatch(
        plan_id=first_plan.plan_id,
        node_id=action.node_id,
        session_id="runtime-session",
        state_fingerprint="desktop-unchanged",
    )
    verify = dispatcher.ready_nodes(action_result.plan)[0]
    failed = await dispatcher.dispatch(
        plan_id=first_plan.plan_id,
        node_id=verify.node_id,
        session_id="runtime-session",
    )
    assert failed.disposition is PlanDispatchDisposition.FAILED

    second_plan = _plan(store, goal, revision=2)
    second_action = dispatcher.ready_nodes(second_plan)[0]
    blocked = await dispatcher.dispatch(
        plan_id=second_plan.plan_id,
        node_id=second_action.node_id,
        session_id="runtime-session",
        state_fingerprint="desktop-unchanged",
    )

    assert blocked.disposition is PlanDispatchDisposition.BLOCKED
    assert blocked.reason == "identical action/state previously made no progress"
    assert len(runtime.requests) == 1


@pytest.mark.asyncio
async def test_action_can_execute_without_fabricated_state_fingerprint(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    runtime = FakeRuntime(opened=True)
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=runtime,
        ),
    )

    action = dispatcher.ready_nodes(plan)[0]
    result = await dispatcher.dispatch(
        plan_id=plan.plan_id,
        node_id=action.node_id,
        session_id="runtime-session",
    )

    assert result.disposition is PlanDispatchDisposition.SUCCEEDED
    assert len(runtime.requests) == 1


def test_interrupted_running_node_without_durable_outcome_fails_closed(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    action = plan.nodes[0]
    running = plan.with_node_state(
        action.node_id,
        PlanNodeState.RUNNING,
        plan_state=PlanState.ACTIVE,
    )
    running = store.update_plan_execution(running, expected_digest=plan.digest)
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=FakeRuntime(),
        ),
    )

    recovered = dispatcher.recover_interrupted(running.plan_id)

    assert recovered.state is PlanState.FAILED
    assert next(
        node for node in recovered.nodes if node.node_id == action.node_id
    ).state is PlanNodeState.FAILED


def test_interrupted_running_node_with_durable_success_is_finalized(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    action = plan.nodes[0]
    running = plan.with_node_state(
        action.node_id,
        PlanNodeState.RUNNING,
        plan_state=PlanState.ACTIVE,
    )
    running = store.update_plan_execution(running, expected_digest=plan.digest)
    store.put_plan_node_result(
        plan_id=running.plan_id,
        node_id=action.node_id,
        attempt=1,
        status="succeeded",
        payload={"route": "capability_runtime"},
        created_at="2026-10-01T15:30:00+00:00",
    )
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=FakeRuntime(),
        ),
    )

    recovered = dispatcher.recover_interrupted(running.plan_id)

    assert recovered.state is PlanState.ACTIVE
    assert next(
        node for node in recovered.nodes if node.node_id == action.node_id
    ).state is PlanNodeState.SUCCEEDED
    assert dispatcher.ready_nodes(recovered)[0].node_type.value == "verify"


def test_latest_plan_for_goal_prefers_newest_goal_and_plan_revision(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    first = _plan(store, goal, revision=1)
    second = _plan(store, goal, revision=2)

    latest = store.latest_plan_for_goal(goal.goal_id)

    assert latest is not None
    assert latest.plan_id == second.plan_id
    assert latest.plan_id != first.plan_id


def test_action_fingerprint_is_parameter_sensitive(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    plan = _plan(store, goal)
    action = plan.nodes[0]
    action_fp = canonical_digest(
        {
            "capability_key": action.capability_key,
            "operation": action.operation,
            "parameters": action.parameters,
        }
    )
    store.record_no_progress(
        goal_id=goal.goal_id,
        plan_id=plan.plan_id,
        node_id=action.node_id,
        action_fingerprint=action_fp,
        state_fingerprint="same-state",
        reason="test",
        created_at="2026-10-01T15:20:00+00:00",
    )

    assert store.has_no_progress(
        goal_id=goal.goal_id,
        action_fingerprint=action_fp,
        state_fingerprint="same-state",
    )
