from pathlib import Path

import pytest

from jarvis.goal_intelligence.continuation import ContinuationCoordinator
from jarvis.goal_intelligence.models import (
    ContinuationBlockerType,
    ContinuationState,
    GoalKind,
    InformationNeedCategory,
    InformationNeedV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


def _store(tmp_path: Path) -> tuple[GoalStore, OwnerGoalV2, PlanGraphV1]:
    store = GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"q" * 32),
        )
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="continuation-session",
            source_turn_id="continuation-turn",
            exact_owner_request="Use my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Use the intended TV.",
            created_at="2026-10-01T17:00:00+00:00",
        )
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.CLARIFY,
        summary="Resolve intended TV.",
        information_need_id="need-placeholder",
    )
    plan = store.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
            created_at="2026-10-01T17:01:00+00:00",
        )
    )
    return store, goal, plan


def test_continuation_restores_exact_blocker_after_restart(tmp_path: Path) -> None:
    store, goal, plan = _store(tmp_path)
    coordinator = ContinuationCoordinator(store)
    continuation = coordinator.block(
        goal=goal,
        plan=plan,
        blocked_by_type=ContinuationBlockerType.WAIT,
        blocked_by_id="wait:door-event",
        resume_node_id=plan.nodes[0].node_id,
        created_at="2026-10-01T17:02:00+00:00",
    )

    restored = ContinuationCoordinator(store).restore(continuation.continuation_id)

    assert restored == continuation
    assert restored.state is ContinuationState.BLOCKED
    assert restored.blocked_by_id == "wait:door-event"


def test_information_need_resumes_only_after_exact_need_is_resolved(
    tmp_path: Path,
) -> None:
    store, goal, plan = _store(tmp_path)
    need = store.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.AMBIGUOUS_REFERENCE,
            subject="TV",
            required_fact="which TV",
            why_required="Target identity changes execution.",
            allowed_resolution_sources=("owner_input",),
            owner_question="Which TV?",
            answer_schema={"type": "entity_id"},
            created_at="2026-10-01T17:02:00+00:00",
        )
    )
    coordinator = ContinuationCoordinator(store)
    continuation = coordinator.block(
        goal=goal,
        plan=plan,
        blocked_by_type=ContinuationBlockerType.INFORMATION_NEED,
        blocked_by_id=need.information_need_id,
        resume_node_id=plan.nodes[0].node_id,
    )

    blocked = coordinator.resume_information_need(
        continuation_id=continuation.continuation_id,
        information_need_id=need.information_need_id,
    )
    assert blocked.resumed is False

    resolved = store.resolve_information_need(
        need.information_need_id,
        resolution_ref="entity:living-room-tv",
        expected_revision=need.revision,
        resolved_at="2026-10-01T17:03:00+00:00",
    )
    assert resolved.resolution_ref == "entity:living-room-tv"

    resumed = coordinator.resume_information_need(
        continuation_id=continuation.continuation_id,
        information_need_id=need.information_need_id,
        resumed_at="2026-10-01T17:04:00+00:00",
    )
    repeated = coordinator.resume_information_need(
        continuation_id=continuation.continuation_id,
        information_need_id=need.information_need_id,
        resumed_at="2026-10-01T17:05:00+00:00",
    )

    assert resumed.resumed is True
    assert resumed.continuation.state is ContinuationState.RESUMED
    assert repeated.continuation == resumed.continuation


def test_wrong_blocker_cannot_resume_continuation(tmp_path: Path) -> None:
    store, goal, plan = _store(tmp_path)
    coordinator = ContinuationCoordinator(store)
    continuation = coordinator.block(
        goal=goal,
        plan=plan,
        blocked_by_type=ContinuationBlockerType.WORK_ITEM,
        blocked_by_id="work-1",
        resume_node_id=plan.nodes[0].node_id,
    )

    with pytest.raises(GoalStoreConflict, match="does not match"):
        coordinator.resume_verified_blocker(
            continuation_id=continuation.continuation_id,
            blocker_type=ContinuationBlockerType.WORK_ITEM,
            blocker_id="work-2",
            verifier=lambda _type, _id: True,
        )


def test_verified_blocker_resume_is_idempotent(tmp_path: Path) -> None:
    store, goal, plan = _store(tmp_path)
    coordinator = ContinuationCoordinator(store)
    continuation = coordinator.block(
        goal=goal,
        plan=plan,
        blocked_by_type=ContinuationBlockerType.EXTERNAL_ACCEPTANCE,
        blocked_by_id="acceptance-1",
        resume_node_id=plan.nodes[0].node_id,
    )

    first = coordinator.resume_verified_blocker(
        continuation_id=continuation.continuation_id,
        blocker_type=ContinuationBlockerType.EXTERNAL_ACCEPTANCE,
        blocker_id="acceptance-1",
        verifier=lambda _type, _id: True,
        resumed_at="2026-10-01T17:06:00+00:00",
    )
    second = coordinator.resume_verified_blocker(
        continuation_id=continuation.continuation_id,
        blocker_type=ContinuationBlockerType.EXTERNAL_ACCEPTANCE,
        blocker_id="acceptance-1",
        verifier=lambda _type, _id: True,
        resumed_at="2026-10-01T17:07:00+00:00",
    )

    assert first.continuation.state is ContinuationState.RESUMED
    assert second.continuation == first.continuation
