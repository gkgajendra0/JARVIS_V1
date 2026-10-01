from pathlib import Path

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.goal_intelligence.models import (
    GoalKind,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.service import (
    GoalDispatchStatus,
    GoalOrchestrator,
    VerificationOutcome,
    VerificationRegistry,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeCapabilityRuntime:
    def __init__(self) -> None:
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=request.capability_key,
            operation=request.operation,
            data={"verification_passed": True},
            provenance=("fake-runtime",),
        )


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"s" * 32),
        )
    )


def _goal(store: GoalStore) -> OwnerGoalV2:
    return store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-service",
            source_turn_id="turn-service",
            exact_owner_request="Open Calculator.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Calculator is open.",
            completion_predicates=("app_open",),
            created_at="2026-10-01T15:20:00+00:00",
        )
    )


def _plan(goal: OwnerGoalV2) -> PlanGraphV1:
    action = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Open Calculator.",
        capability_key="app:lifecycle",
        operation="open_app",
        parameters={"app": "calculator"},
        postcondition_ref="app_open",
    )
    verify = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=1,
        node_type=PlanNodeType.VERIFY,
        summary="Verify Calculator opened.",
        postcondition_ref="app_open",
    )
    return PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(action, verify),
        edges=((action.node_id, verify.node_id),),
        root_node_ids=(action.node_id,),
        completion_node_ids=(verify.node_id,),
        created_at="2026-10-01T15:21:00+00:00",
    )


def test_action_dispatch_preserves_authority_boundary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    plan = _plan(goal)
    runtime = FakeCapabilityRuntime()
    orchestrator = GoalOrchestrator(
        goal_store=store,
        capability_runtime=runtime,
    )

    result = orchestrator.dispatch_node(
        goal=goal,
        plan=plan,
        node=plan.nodes[0],
    )

    assert result.status is GoalDispatchStatus.SUCCEEDED
    assert result.route == "capability_runtime"
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.origin is ActionOrigin.MODEL_SUGGESTED
    assert request.parameters == {"app": "calculator"}


def test_verification_false_is_not_reported_as_success(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    plan = _plan(goal)
    registry = VerificationRegistry()
    registry.register(
        "app_open",
        lambda evidence: VerificationOutcome(
            verified=bool(evidence.get("open")),
            reason="window observation",
            evidence_refs=("window:list",),
        ),
    )
    orchestrator = GoalOrchestrator(
        goal_store=store,
        capability_runtime=FakeCapabilityRuntime(),
        verification_registry=registry,
    )

    result = orchestrator.dispatch_node(
        goal=goal,
        plan=plan,
        node=plan.nodes[1],
        verification_evidence={"open": False},
    )

    assert result.status is GoalDispatchStatus.FAILED
    assert result.verification is not None
    assert result.verification.verified is False


def test_ready_nodes_only_advance_after_dependencies_succeed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    plan = _plan(goal)
    action, verify = plan.nodes

    first = GoalOrchestrator.ready_nodes(plan)
    second = GoalOrchestrator.ready_nodes(
        plan,
        succeeded_node_ids={action.node_id},
    )

    assert tuple(node.node_id for node in first) == (action.node_id,)
    assert tuple(node.node_id for node in second) == (verify.node_id,)


def test_acquisition_node_blocks_without_phase9_bridge(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    acquire = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire reusable media control.",
        gap_id="gap_missing",
    )
    plan = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(acquire,),
        edges=(),
        root_node_ids=(acquire.node_id,),
        completion_node_ids=(acquire.node_id,),
    )
    orchestrator = GoalOrchestrator(
        goal_store=store,
        capability_runtime=FakeCapabilityRuntime(),
    )

    result = orchestrator.dispatch_node(
        goal=goal,
        plan=plan,
        node=acquire,
    )

    assert result.status is GoalDispatchStatus.BLOCKED
    assert result.route == "phase9"
