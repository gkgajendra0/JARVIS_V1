from __future__ import annotations

from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.goal_intelligence.models import (
    ContinuationBlockerType,
    GoalContinuationV1,
    GoalKind,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.status import (
    ObjectiveChangeStatus,
    ObjectiveOverallState,
    ObjectivePhase,
    OwnerObjectiveStatusResolver,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.models import WorkState
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def submit(self, work_id, *, priority):
        del priority
        return work_id


def _goal(goals: GoalStore) -> OwnerGoalV2:
    return goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="owner-turn",
            exact_owner_request="Acquire capability to control my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="JARVIS can control the owner's TV.",
            state=GoalState.WAITING_CAPABILITY,
            created_at="2026-10-04T10:00:00+00:00",
        )
    )


def _plan_and_continuation(
    goals: GoalStore,
    goal: OwnerGoalV2,
    *,
    work_id: str,
) -> None:
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.WAIT,
        summary="Wait for reusable capability acquisition.",
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
            created_at="2026-10-04T10:01:00+00:00",
        )
    )
    goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="capability_gap_tv_control",
            resume_node_id=node.node_id,
            work_ids=(work_id,),
            goal_revision=goal.goal_revision,
            created_at="2026-10-04T10:02:00+00:00",
        )
    )


def _complete(work: SQLiteWorkStore, work_id: str) -> None:
    item = work.require(work_id)
    running = work.save(
        item.transition(WorkState.RUNNING, status_detail="researching"),
        expected_version=item.version,
    )
    work.save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="research complete",
            result={"ok": True},
        ),
        expected_version=running.version,
    )


def test_completed_child_work_does_not_complete_owner_objective(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, RecordingBackend())

    goal = _goal(goals)
    change = coordinator.start(
        goal.exact_owner_request,
        goal.source_session_id,
        goal.source_turn_id,
    )
    research = changes.list_stages(change.change_id)[0]
    _plan_and_continuation(goals, goal, work_id=research.work_id)

    _complete(work, research.work_id)
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "custom_adapter"},
    )
    coordinator.reconcile(change.change_id)
    gate = GateService(changes, verify_owner=lambda *_: False).present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )

    status = OwnerObjectiveStatusResolver(
        goals=goals,
        changes=changes,
    ).resolve(goal.goal_id)

    assert work.require(research.work_id).state is WorkState.COMPLETED
    assert changes.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL
    assert status.verified_completion is False
    assert status.terminal is False
    assert status.overall_state is ObjectiveOverallState.WAITING_OWNER
    assert status.phase is ObjectivePhase.WAITING_OWNER_APPROVAL
    assert status.blocker is not None
    assert status.blocker.blocker_id == gate.gate_id
    assert status.blocker.owner_action_required is True
    assert status.engineering_changes[0].state == "waiting_owner_approval"
    assert status.work[0].state == "completed"


def test_terminal_goal_is_only_overall_completion_authority(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work)
    goal = _goal(goals)

    waiting = OwnerObjectiveStatusResolver(
        goals=goals,
        changes=changes,
    ).resolve(goal.goal_id)
    assert waiting.verified_completion is False

    completed = goals.update_goal_state(
        goal.goal_id,
        GoalState.COMPLETED,
        expected_revision=goal.goal_revision,
    )
    status = OwnerObjectiveStatusResolver(
        goals=goals,
        changes=changes,
    ).resolve(completed.goal_id)

    assert status.overall_state is ObjectiveOverallState.COMPLETED
    assert status.phase is ObjectivePhase.COMPLETED
    assert status.verified_completion is True
    assert status.terminal is True


def test_cancelled_goal_is_not_returned_as_active_objective(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work)
    goal = _goal(goals)
    goals.update_goal_state(
        goal.goal_id,
        GoalState.CANCELLED,
        expected_revision=goal.goal_revision,
    )

    resolver = OwnerObjectiveStatusResolver(goals=goals, changes=changes)

    assert resolver.list_active() == ()


def test_lineage_integrity_failure_blocks_objective_projection(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    resolver = OwnerObjectiveStatusResolver(
        goals=GoalStore(work),
        changes=ChangeStore(work),
    )
    change = ObjectiveChangeStatus(
        change_id="change_integrity",
        state=ChangeState.OBSERVING.value,
        work=(),
        pending_gate_ids=(),
        lifecycle_proposal_present=True,
        activation_present=True,
        external_acceptance_required=True,
        external_acceptance_work_id="work_acceptance",
        external_acceptance_work_state="completed",
        external_acceptance_verdict="pass",
        lineage_complete=False,
        lineage_error="CapabilityAcquisitionLineageError",
    )

    overall, phase, blocker = resolver._status_for_change(change)

    assert overall is ObjectiveOverallState.BLOCKED
    assert phase is ObjectivePhase.BLOCKED
    assert blocker is not None
    assert blocker.kind == "lineage_integrity"
    assert blocker.owner_action_required is False


def test_failed_external_acceptance_blocks_objective_projection(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    resolver = OwnerObjectiveStatusResolver(
        goals=GoalStore(work),
        changes=ChangeStore(work),
    )
    change = ObjectiveChangeStatus(
        change_id="change_acceptance",
        state=ChangeState.OBSERVING.value,
        work=(),
        pending_gate_ids=(),
        lifecycle_proposal_present=True,
        activation_present=True,
        external_acceptance_required=True,
        external_acceptance_work_id="work_acceptance",
        external_acceptance_work_state="completed",
        external_acceptance_verdict="fail",
        lineage_complete=False,
        lineage_error=None,
    )

    overall, phase, blocker = resolver._status_for_change(change)

    assert overall is ObjectiveOverallState.BLOCKED
    assert phase is ObjectivePhase.BLOCKED
    assert blocker is not None
    assert blocker.kind == "external_acceptance_failed"


def test_lifecycle_proposal_makes_observing_change_wait_for_owner_activation(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    resolver = OwnerObjectiveStatusResolver(
        goals=GoalStore(work),
        changes=ChangeStore(work),
    )
    change = ObjectiveChangeStatus(
        change_id="change_activation",
        state=ChangeState.OBSERVING.value,
        work=(),
        pending_gate_ids=(),
        lifecycle_proposal_present=True,
        activation_present=False,
        external_acceptance_required=True,
        external_acceptance_work_id=None,
        external_acceptance_work_state=None,
        external_acceptance_verdict=None,
        lineage_complete=False,
        lineage_error=None,
    )

    overall, phase, blocker = resolver._status_for_change(change)

    assert overall is ObjectiveOverallState.WAITING_OWNER
    assert phase is ObjectivePhase.WAITING_ACTIVATION
    assert blocker is not None
    assert blocker.kind == "capability_activation"
    assert blocker.owner_action_required is True
