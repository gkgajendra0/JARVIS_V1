import sqlite3
from pathlib import Path

import pytest

from jarvis.goal_intelligence.models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    ContinuationBlockerType,
    GoalContinuationV1,
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedV1,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    ResourceBindingV1,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


@pytest.fixture
def goal_store(tmp_path: Path) -> GoalStore:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(
        path,
        payload_codec=ProtectedWorkPayloadCodec(b"k" * 32),
    )
    return GoalStore(work)


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="session-1",
        source_turn_id="turn-1",
        exact_owner_request="Monitor my main gate.",
        goal_kind=GoalKind.MONITORING,
        desired_outcome="Notify the owner when the gate condition is verified.",
        completion_predicates=("notification_sent",),
        created_at="2026-10-01T10:00:00+00:00",
    )


def test_goal_store_protects_owner_payload_and_round_trips(
    goal_store: GoalStore,
) -> None:
    goal = _goal()

    stored = goal_store.create_goal(goal)
    assert goal_store.payload_protected is True
    assert goal_store.get_goal(goal.goal_id) == stored

    with sqlite3.connect(goal_store.work.path) as db:
        raw = db.execute(
            "SELECT payload FROM owner_goals_v2 WHERE goal_id=?",
            (goal.goal_id,),
        ).fetchone()[0]

    assert raw.startswith("enc:v1:")
    assert goal.exact_owner_request not in raw


def test_goal_state_update_uses_compare_and_swap(goal_store: GoalStore) -> None:
    goal = goal_store.create_goal(_goal())

    updated = goal_store.update_goal_state(
        goal.goal_id,
        GoalState.RESOLVING,
        expected_revision=1,
        updated_at="2026-10-01T10:01:00+00:00",
    )

    assert updated.goal_revision == 2
    assert updated.state is GoalState.RESOLVING

    with pytest.raises(GoalStoreConflict, match="revision changed"):
        goal_store.update_goal_state(
            goal.goal_id,
            GoalState.REQUIREMENTS_READY,
            expected_revision=1,
        )


def test_information_need_resolution_is_exact_and_idempotent(
    goal_store: GoalStore,
) -> None:
    goal = goal_store.create_goal(_goal())
    need = InformationNeedV1.create(
        goal_id=goal.goal_id,
        category=InformationNeedCategory.AMBIGUOUS_REFERENCE,
        subject="gate camera",
        required_fact="Which of two gate cameras is intended?",
        why_required="The target resource changes execution.",
        candidate_values=("camera.front", "camera.side"),
        allowed_resolution_sources=("owner_input",),
        owner_question="Which gate camera do you mean?",
        answer_schema={"type": "entity_id"},
        created_at="2026-10-01T10:02:00+00:00",
    )
    goal_store.create_information_need(need)

    resolved = goal_store.resolve_information_need(
        need.information_need_id,
        resolution_ref="entity:camera.front",
        evidence_refs=("interaction:need-1",),
        expected_revision=1,
        resolved_at="2026-10-01T10:03:00+00:00",
    )
    repeated = goal_store.resolve_information_need(
        need.information_need_id,
        resolution_ref="entity:camera.front",
    )

    assert repeated == resolved

    with pytest.raises(GoalStoreConflict, match="another reference"):
        goal_store.resolve_information_need(
            need.information_need_id,
            resolution_ref="entity:camera.side",
        )


def test_goal_store_persists_entity_graph_gap_plan_continuation_and_monitor(
    goal_store: GoalStore,
) -> None:
    goal = goal_store.create_goal(_goal())
    entity = goal_store.put_entity(
        WorldEntityRefV1.create(
            entity_type="camera",
            canonical_name="Main Gate Camera",
            aliases=("main gate camera",),
            provenance_refs=("owner-config:main-gate",),
        )
    )
    binding = ResourceBindingV1.create(
        entity_id=entity.entity_id,
        provider_id="onvif",
        provider_resource_id="camera-1",
        capability_keys=("camera.observe",),
        evidence_refs=("discovery:onvif",),
        last_verified_at="2026-10-01T10:04:00+00:00",
    )
    goal_store.put_resource_binding(binding)

    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="camera.observe",
        operation="read_live_stream",
        target_entity_id=entity.entity_id,
        target_entity_type="camera",
        reason="Observe the main gate.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    goal_store.put_requirement_graph(graph)

    gap = CapabilityGapV1.create(
        goal_id=goal.goal_id,
        requirement_ids=graph.requirement_ids,
        reusable_capability_family="camera.observe",
        target_entity_type="camera",
        target_entity_id=entity.entity_id,
        minimum_required_operations=("read_live_stream",),
        missing_reason_codes=("resource_access_missing",),
    )
    goal_store.put_gap(gap)
    satisfied = goal_store.update_gap_state(
        gap.gap_id,
        CapabilityGapState.SATISFIED,
        expected_revision=1,
    )

    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.WAIT,
        summary="Wait for camera access.",
    )
    plan = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(node,),
        edges=(),
        root_node_ids=(node.node_id,),
        completion_node_ids=(node.node_id,),
        created_at="2026-10-01T10:05:00+00:00",
    )
    goal_store.put_plan(plan)

    continuation = GoalContinuationV1.create(
        goal_id=goal.goal_id,
        plan_id=plan.plan_id,
        blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
        blocked_by_id=gap.gap_id,
        resume_node_id=node.node_id,
        goal_revision=goal.goal_revision,
        created_at="2026-10-01T10:06:00+00:00",
    )
    goal_store.put_continuation(continuation)
    resumed = goal_store.resume_continuation(
        continuation.continuation_id,
        expected_revision=1,
        resumed_at="2026-10-01T10:07:00+00:00",
    )
    repeated = goal_store.resume_continuation(
        continuation.continuation_id,
        expected_revision=1,
    )

    predicate = MonitorPredicateV1.create(
        goal_id=goal.goal_id,
        source_entity_ids=(entity.entity_id,),
        observation_capabilities=("camera.observe",),
        semantic_condition="delivery agent is standing at the door",
        candidate_trigger_strategy="motion_then_local_perception",
        stability_window=1.0,
        cooldown=60.0,
        completion_policy="complete_once",
        notification_policy="owner_once",
        verification_requirement="verified_person_at_gate",
    )
    goal_store.put_monitor_predicate(predicate)

    assert goal_store.get_entity(entity.entity_id) == entity
    assert goal_store.get_resource_binding(binding.binding_id) == binding
    assert goal_store.get_requirement_graph(graph.graph_id) == graph
    assert satisfied.state is CapabilityGapState.SATISFIED
    assert goal_store.get_plan(plan.plan_id) == plan
    assert repeated == resumed
    assert goal_store.get_monitor_predicate(predicate.predicate_id) == predicate
