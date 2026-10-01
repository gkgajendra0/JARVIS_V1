from dataclasses import replace

import pytest

from jarvis.goal_intelligence.models import (
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


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="session-1",
        source_turn_id="turn-7",
        exact_owner_request="I want to watch Transporter on my TV.",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="Watch Transporter on the owner's TV.",
        completion_predicates=("media playback has started",),
        created_at="2026-10-01T10:00:00+00:00",
    )


def test_owner_goal_identity_is_deterministic_but_revision_digest_changes() -> None:
    first = _goal()
    second = _goal()

    assert first.goal_id == second.goal_id
    assert first.digest == second.digest

    resolving = first.with_state(
        GoalState.RESOLVING,
        updated_at="2026-10-01T10:01:00+00:00",
    )

    assert resolving.goal_id == first.goal_id
    assert resolving.goal_revision == 2
    assert resolving.digest != first.digest


def test_digest_tampering_is_rejected() -> None:
    goal = _goal()

    with pytest.raises(ValueError, match="goal digest mismatch"):
        replace(goal, desired_outcome="tampered")


def test_information_need_identity_is_task_bound_and_secret_value_is_not_stored() -> None:
    goal = _goal()
    need = InformationNeedV1.create(
        goal_id=goal.goal_id,
        category=InformationNeedCategory.OWNER_SECRET,
        subject="TV pairing",
        required_fact="Pairing credential reference",
        why_required="Provider requires an owner-visible pairing credential.",
        allowed_resolution_sources=("owner_input", "secret_flow"),
        answer_schema={"type": "secret_reference"},
        created_at="2026-10-01T10:02:00+00:00",
    )

    resolved = need.with_resolution(
        resolution_ref="secret://tv-pairing",
        evidence_refs=("interaction:pairing-1",),
        resolved_at="2026-10-01T10:03:00+00:00",
    )

    assert resolved.goal_id == goal.goal_id
    assert resolved.resolution_ref == "secret://tv-pairing"
    assert "1234" not in str(resolved.canonical_payload())


def test_requirement_graph_persists_semantic_requirements_not_task_specific_skill() -> None:
    goal = _goal()
    launch = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="launch_app",
        target_entity_type="media_player",
        reason="Open the selected media application.",
    )
    play = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play",
        target_entity_type="media_player",
        expected_postconditions=("playback_started",),
        reason="Start selected media playback.",
    )

    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(launch, play),
        edges=((launch.requirement_id, play.requirement_id),),
    )
    gap = CapabilityGapV1.create(
        goal_id=goal.goal_id,
        requirement_ids=graph.requirement_ids,
        reusable_capability_family="media_player.control",
        target_entity_type="media_player",
        minimum_required_operations=("launch_app", "play"),
        missing_reason_codes=("no_matching_capability",),
    )

    assert gap.reusable_capability_family == "media_player.control"
    assert "transporter" not in gap.reusable_capability_family


def test_plan_graph_requires_typed_action_and_is_acyclic() -> None:
    goal = _goal()
    action = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Launch media application",
        capability_key="media_player.control",
        operation="launch_app",
    )
    verify = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=1,
        node_type=PlanNodeType.VERIFY,
        summary="Verify application launch",
        postcondition_ref="observation:app_active",
    )

    plan = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(action, verify),
        edges=((action.node_id, verify.node_id),),
        root_node_ids=(action.node_id,),
        completion_node_ids=(verify.node_id,),
        created_at="2026-10-01T10:04:00+00:00",
    )

    assert plan.nodes[0].node_id == action.node_id

    with pytest.raises(ValueError, match="DAG"):
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(action, verify),
            edges=(
                (action.node_id, verify.node_id),
                (verify.node_id, action.node_id),
            ),
            root_node_ids=(action.node_id,),
            completion_node_ids=(verify.node_id,),
            created_at="2026-10-01T10:04:00+00:00",
        )


def test_world_binding_continuation_and_monitor_are_digest_bound() -> None:
    goal = _goal()
    entity = WorldEntityRefV1.create(
        entity_type="media_player",
        canonical_name="Living Room TV",
        aliases=("my tv",),
        provenance_refs=("owner-config:tv",),
    )
    binding = ResourceBindingV1.create(
        entity_id=entity.entity_id,
        provider_id="vidaa",
        provider_resource_id="tv-1",
        capability_keys=("media_player.control",),
        evidence_refs=("discovery:vidaa-1",),
        last_verified_at="2026-10-01T10:05:00+00:00",
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.WAIT,
        summary="Wait for capability acquisition",
    )
    plan = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(node,),
        edges=(),
        root_node_ids=(node.node_id,),
        completion_node_ids=(node.node_id,),
        created_at="2026-10-01T10:06:00+00:00",
    )
    continuation = GoalContinuationV1.create(
        goal_id=goal.goal_id,
        plan_id=plan.plan_id,
        blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
        blocked_by_id="gap-1",
        resume_node_id=node.node_id,
        goal_revision=goal.goal_revision,
        created_at="2026-10-01T10:07:00+00:00",
    )
    predicate = MonitorPredicateV1.create(
        goal_id=goal.goal_id,
        source_entity_ids=(entity.entity_id,),
        observation_capabilities=("media_player.observe",),
        semantic_condition="playback has started",
        candidate_trigger_strategy="state_change",
        completion_policy="complete_once",
        notification_policy="none",
        verification_requirement="playback_state=playing",
    )

    assert binding.entity_id == entity.entity_id
    assert continuation.goal_id == goal.goal_id
    assert predicate.goal_id == goal.goal_id
