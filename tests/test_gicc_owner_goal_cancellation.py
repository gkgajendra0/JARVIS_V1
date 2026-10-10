"""Cancellation retires only one GICC goal's active lineage.

Tests intentionally exercise the old deterministic bridge (no new link
artifact), the shape observed on the owner's existing TV-control goal.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.goal_intelligence.models import (
    CapabilityGapState,
    CapabilityGapV1,
    ContinuationBlockerType,
    ContinuationState,
    GoalContinuationV1,
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.work.models import WorkDeliveryKind, WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


def _fixture(tmp_path):
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(work, processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,))
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="tv-owner-session",
            source_turn_id="original-tv-request",
            exact_owner_request="Acquire the capability to control my TV",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Control my real TV",
            state=GoalState.WAITING_CAPABILITY,
        )
    )
    gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=("requirement-tv",),
            reusable_capability_family="media_player.control",
            target_entity_type="television",
            target_entity_id=None,
            minimum_required_operations=("send_remote_key",),
            missing_reason_codes=("unavailable",),
        )
    )
    need = goals.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="TV",
            required_fact="model",
            why_required="Target must be corroborated",
            allowed_resolution_sources=("owner_input",),
        )
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.WAIT,
        summary="Wait for verified TV control",
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
        )
    )
    change = changes.create(
        request="Acquire TV control",
        process_key="owner_capability_acquisition",
        process_version=1,
        source_session_id=f"gicc:{goal.goal_id}",
        source_turn_id=f"gap:{gap.gap_id}",
    )
    item = WorkItem(
        request="Research TV control",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="acquisition:1",
    )
    changes.link_work(change.change_id, "acquisition", 1, item)
    continuation = goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            work_ids=(item.work_id,),
            goal_revision=goal.goal_revision,
        )
    )
    return work, goals, changes, goal, gap, need, plan, continuation, change, item


class LocalCancelOrchestrator:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def cancel(self, work_id):
        self.calls.append(work_id)
        item = self.store.require(work_id)
        if item.state.terminal:
            return item
        return self.store.save(
            item.transition(WorkState.CANCELLED, status_detail="owner cancelled"),
            expected_version=item.version,
        )


def _runtime(work, goals, changes, *, orchestrator=None):
    orchestrator = orchestrator or LocalCancelOrchestrator(work)
    return GiccApplyRuntime(
        store=goals,
        world=SimpleNamespace(),
        coordinator=SimpleNamespace(),
        dispatcher=SimpleNamespace(),
        telemetry=CapturingGiccTelemetry(),
        capability_runtime=SimpleNamespace(),
        change_store=changes,
        work_runtime=SimpleNamespace(store=work, orchestrator=orchestrator),
    ), orchestrator


@pytest.mark.asyncio
async def test_cancel_legacy_goal_stops_work_and_clears_only_active_projections(
    tmp_path,
):
    work, goals, changes, goal, gap, need, plan, continuation, change, item = _fixture(
        tmp_path
    )
    # A separate unrelated job must remain untouched.
    unrelated = WorkItem(
        request="Unrelated work",
        work_type=WorkType.RESEARCH,
        source_session_id="separate-project",
        source_turn_id="another-request",
    )
    work.create(unrelated)
    runtime, orchestrator = _runtime(work, goals, changes)
    stale = work.enqueue_delivery(
        work=work.require(item.work_id),
        kind=WorkDeliveryKind.PROGRESS,
        message="Old TV research is ready",
        event_key="old-tv-progress",
    )
    assert stale is not None
    assert len(work.list_pending_deliveries()) == 1

    result = await runtime.cancel_owner_goal(goal.goal_id)
    assert result["suppressed_pending_notifications"] == 1
    assert work.list_pending_deliveries() == ()

    assert result["status"] == "cancelled"
    assert result["historical_audit_retained"] is True
    assert result["cancelled_work_ids"] == [item.work_id]
    assert orchestrator.calls == [item.work_id]
    assert goals.get_goal(goal.goal_id).state is GoalState.CANCELLED
    assert goals.list_active_goals() == ()
    assert goals.get_gap(gap.gap_id).state is CapabilityGapState.CANCELLED
    assert goals.get_information_need(need.information_need_id).state is (
        InformationNeedState.CANCELLED
    )
    assert goals.get_plan(plan.plan_id).state is PlanState.CANCELLED
    assert goals.get_continuation(continuation.continuation_id).state is (
        ContinuationState.CANCELLED
    )
    assert changes.require(change.change_id).state is ChangeState.SUPERSEDED
    assert work.require(item.work_id).state is WorkState.CANCELLED
    assert work.require(unrelated.work_id).state is WorkState.QUEUED
    assert changes.get(change.change_id) is not None

    repeat = await runtime.cancel_owner_goal(goal.goal_id)
    assert repeat["idempotent"] is True
    assert orchestrator.calls == [item.work_id]


@pytest.mark.asyncio
async def test_failed_work_stop_prevents_false_cancelled_goal(tmp_path):
    work, goals, changes, goal, *_ = _fixture(tmp_path)

    class FailingOrchestrator:
        def cancel(self, work_id):
            raise RuntimeError("backend refused cancellation")

    runtime, _ = _runtime(work, goals, changes, orchestrator=FailingOrchestrator())

    with pytest.raises(RuntimeError, match="backend refused"):
        await runtime.cancel_owner_goal(goal.goal_id)

    assert goals.get_goal(goal.goal_id).state is GoalState.WAITING_CAPABILITY
    assert (
        changes.owner_goal_acquisition_changes(
            goal.goal_id, tuple(g.gap_id for g in goals.list_gaps(goal_id=goal.goal_id))
        )[0][0].state
        is ChangeState.PROPOSED
    )


def test_cancellation_rejects_stale_revision_and_terminal_goals(tmp_path):
    work, goals, changes, goal, *_ = _fixture(tmp_path)
    with pytest.raises(GoalStoreConflict, match="revision"):
        goals.cancel_goal_tree(goal.goal_id, expected_revision=goal.goal_revision + 1)
    assert goals.get_goal(goal.goal_id).state is GoalState.WAITING_CAPABILITY
    assert goals.get_goal(goal.goal_id).digest == goal.digest
