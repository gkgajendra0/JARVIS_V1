from __future__ import annotations

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.gates import GateKind, GateService
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
    ObjectiveOverallState,
    ObjectivePhase,
    OwnerObjectiveStatusResolver,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


def _complete(work: SQLiteWorkStore, item: WorkItem) -> WorkItem:
    running = work.save(
        item.transition(WorkState.RUNNING, status_detail="researching"),
        expected_version=item.version,
    )
    return work.save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="research complete",
            result={"ok": True},
        ),
        expected_version=running.version,
    )


def test_objective_status_keeps_goal_active_after_child_research_completed(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work)

    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="owner-turn",
            exact_owner_request="Acquire capability to control my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="JARVIS can control the owner's TV.",
            completion_predicates=("tv_control_verified",),
            state=GoalState.WAITING_CAPABILITY,
            created_at="2026-10-05T04:00:00+00:00",
        )
    )

    wait_node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.WAIT,
        summary="Wait for reusable TV-control capability.",
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(wait_node,),
            edges=(),
            root_node_ids=(wait_node.node_id,),
            completion_node_ids=(wait_node.node_id,),
            created_at="2026-10-05T04:01:00+00:00",
        )
    )

    change = changes.create(
        request="Research reusable TV-control integration.",
        process_key="engineering.change",
        process_version=1,
        source_session_id=f"gicc:{goal.goal_id}",
        source_turn_id="gap:tv-control",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    research = WorkItem(
        request="Research reusable TV-control integration.",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="research:1",
    )
    changes.link_work(change.change_id, "research", 1, research)
    research = _complete(work, work.require(research.work_id))

    continuation = goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap_tv_control",
            resume_node_id=wait_node.node_id,
            work_ids=(research.work_id,),
            goal_revision=goal.goal_revision,
            created_at="2026-10-05T04:02:00+00:00",
        )
    )

    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"summary": "Use a reusable media-player adapter."},
    )
    gate = GateService(changes, verify_owner=lambda *_: False).present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )

    resolver = OwnerObjectiveStatusResolver(goals=goals, changes=changes)
    status = resolver.resolve(goal.goal_id)

    assert status.goal_id == goal.goal_id
    assert status.goal_state == GoalState.WAITING_CAPABILITY.value
    assert status.overall_state is ObjectiveOverallState.WAITING_OWNER
    assert status.phase is ObjectivePhase.WAITING_OWNER_APPROVAL
    assert status.verified_completion is False
    assert status.plan_id == plan.plan_id
    assert status.continuation_ids == (continuation.continuation_id,)
    assert status.blocker is not None
    assert status.blocker.owner_action_required is True
    assert status.blocker.blocker_id == gate.gate_id
    assert any(item.work_id == research.work_id for item in status.work)
    assert status.work[0].state == WorkState.COMPLETED.value
    assert status.engineering_changes[0].state == (
        ChangeState.WAITING_OWNER_APPROVAL.value
    )
    assert status.engineering_changes[0].pending_gate_ids == (gate.gate_id,)

    by_work = resolver.find_active_by_work_id(research.work_id)
    assert by_work is not None
    assert by_work.goal_id == goal.goal_id


def test_terminal_duplicate_goal_is_not_reported_as_active_objective(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work)

    active = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="active-session",
            source_turn_id="active-turn",
            exact_owner_request="Control my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="TV control works.",
            state=GoalState.WAITING_CAPABILITY,
            created_at="2026-10-05T04:00:00+00:00",
        )
    )
    cancelled = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="duplicate-session",
            source_turn_id="duplicate-turn",
            exact_owner_request="Proceed with that.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Duplicate accidental objective.",
            state=GoalState.CANCELLED,
            created_at="2026-10-05T04:01:00+00:00",
        )
    )

    resolver = OwnerObjectiveStatusResolver(goals=goals, changes=changes)
    listed = resolver.list_active(limit=20)

    assert [item.goal_id for item in listed] == [active.goal_id]
    assert all(item.goal_id != cancelled.goal_id for item in listed)
