from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_gicc_composition import (
    FakePhase9Bridge,
    QueueStructuredClient,
    StaticContext,
    _conversation,
    _store,
)

from jarvis.conversation import ConversationRole
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeState,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    CapabilityRequirementProposalSet,
    RequirementDeriver,
)
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.voice.gicc_tools import GiccAgentTools


@pytest.mark.asyncio
async def test_gicc_voice_clarification_resumes_exact_goal(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    living = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:living_room_tv",),
        )
    )
    registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Bedroom TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:bedroom_tv",),
        )
    )
    conversation, turn = _conversation("Play Transporter on my TV.")
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Play Transporter on the selected TV.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my TV",
                    proposed_type="media_player",
                    evidence_turn_ids=[turn.turn_id],
                ),
                ShadowEntityCandidate(
                    mention="Transporter",
                    proposed_type="media_content",
                    evidence_turn_ids=[turn.turn_id],
                ),
            ],
            candidate_completion_predicates=["playback_started"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play",
                    target_entity_id=living.entity_id,
                    target_entity_type="media_player",
                    expected_postconditions=["playback_started"],
                    reason="Start selected media playback.",
                )
            ]
        )
    )
    telemetry = CapturingGiccTelemetry()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=FakePhase9Bridge(),
        telemetry=telemetry,
    )
    tools = GiccAgentTools(
        coordinator,
        conversation,
        store,
        telemetry=telemetry,
    )

    admitted = await tools.pursue_owner_goal(None)

    assert admitted["status"] == "waiting_information"
    questions = admitted["questions"]
    assert isinstance(questions, list)
    assert len(questions) == 1
    question = questions[0]
    assert question["interaction_id"]
    labels = {option["label"] for option in question["options"]}
    assert labels == {"Bedroom TV", "Living Room TV"}

    conversation.accept_turn(ConversationRole.USER, "Use the Living Room TV.")
    continued = await tools.resolve_goal_information(
        None,
        interaction_id=str(question["interaction_id"]),
        selected_candidate_value=living.entity_id,
    )

    assert continued["ok"] is True
    assert continued["status"] == "waiting_capability"
    goal = store.get_goal(str(continued["goal_id"]))
    assert goal is not None
    assert living.entity_id in goal.referenced_entity_ids


@pytest.mark.asyncio
async def test_gicc_voice_rejects_candidate_not_bound_to_interaction(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    for name in ("Living Room TV", "Bedroom TV"):
        registry.register_entity(
            WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name=name,
                aliases=("my tv",),
            )
        )
    conversation, turn = _conversation("Play Transporter on my TV.")
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(
            client=QueueStructuredClient(
                ShadowGoalInterpretationOutput(
                    actionable=True,
                    desired_outcome="Play Transporter on my TV.",
                    goal_kind=GoalKind.ONE_SHOT,
                    candidate_entities=[
                        ShadowEntityCandidate(
                            mention="my TV",
                            proposed_type="media_player",
                            evidence_turn_ids=[turn.turn_id],
                        )
                    ],
                    evidence_turn_ids=[turn.turn_id],
                )
            )
        ),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=QueueStructuredClient()),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
    )
    tools = GiccAgentTools(coordinator, conversation, store)

    admitted = await tools.pursue_owner_goal(None)
    question = admitted["questions"][0]
    conversation.accept_turn(ConversationRole.USER, "Use some other TV.")

    rejected = await tools.resolve_goal_information(
        None,
        interaction_id=str(question["interaction_id"]),
        selected_candidate_value="entity_not_offered",
    )

    assert rejected["ok"] is False
    assert rejected["status"] == "candidate_value_not_allowed"
    need = store.get_information_need(str(question["information_need_id"]))
    assert need is not None
    assert need.state.value == "waiting_for_owner"


class FailingGoalCoordinator(GoalIntelligenceCoordinator):
    def __init__(self) -> None:
        pass

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        raise RuntimeError("synthetic internal requirement failure")


class CompletedExecutionRuntime:
    def __init__(self, result: GoalIntakeResult) -> None:
        self.result = result
        self.pursue_calls = 0

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        self.pursue_calls += 1
        return self.result

    async def continue_goal(self, goal_id: str):
        del goal_id
        return self.result


@pytest.mark.asyncio
async def test_gicc_voice_reports_only_verified_durable_completion(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, turn = _conversation("Open Calculator.")
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=conversation.session_id,
            source_turn_id=turn.turn_id,
            exact_owner_request=turn.text,
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Calculator is open.",
            completion_predicates=("app_open",),
            state=GoalState.COMPLETED,
            created_at="2026-10-01T18:00:00+00:00",
        )
    )
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.PLAN_READY,
        goal=goal,
    )
    execution = CompletedExecutionRuntime(result)
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=execution,
    )

    payload = await tools.pursue_owner_goal(None)

    assert execution.pursue_calls == 1
    assert payload["status"] == "completed"
    assert payload["verified_completion"] is True
    assert "may acknowledge" in str(payload["truth_note"])


@pytest.mark.asyncio
async def test_gicc_voice_surfaces_sensitive_external_owner_input_without_leak(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, turn = _conversation("Play Transporter on my TV.")
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=conversation.session_id,
            source_turn_id=turn.turn_id,
            exact_owner_request=turn.text,
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Transporter is playing on my TV.",
            completion_predicates=("playback_started",),
            state=GoalState.EXECUTING,
            created_at="2026-10-01T18:02:00+00:00",
        )
    )
    action = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Play Transporter on the TV.",
        capability_key="package:tv-control",
        operation="play",
        parameters={"title": "Transporter"},
        postcondition_ref="playback_started",
    )
    proposed = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(action,),
        edges=(),
        root_node_ids=(action.node_id,),
        completion_node_ids=(action.node_id,),
        created_at="2026-10-01T18:03:00+00:00",
    )
    waiting = proposed.with_node_state(
        action.node_id,
        PlanNodeState.WAITING,
        plan_state=PlanState.WAITING,
    )
    waiting = store.put_plan(waiting)
    evidence = store.put_plan_node_result(
        plan_id=waiting.plan_id,
        node_id=action.node_id,
        attempt=1,
        status="waiting",
        payload={
            "route": "capability_runtime:owner_input",
            "interaction": {
                "kind": "external_owner_input",
                "input_kind": "pin",
                "prompt": "Enter the TV pairing PIN.",
                "parameter": "pin",
                "sensitive": True,
            },
        },
        created_at="2026-10-01T18:04:00+00:00",
    )
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.PLAN_READY,
        goal=goal,
        plan=waiting,
    )
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=CompletedExecutionRuntime(result),
    )

    payload = await tools.pursue_owner_goal(None)

    assert payload["status"] == "waiting_owner_input"
    assert payload["owner_input"] == {
        "interaction_ref": evidence["result_id"],
        "input_kind": "pin",
        "prompt": "Enter the TV pairing PIN.",
        "parameter": "pin",
        "sensitive": True,
    }
    assert "generic GICC tool argument" in str(payload["truth_note"])
    interaction = evidence["payload"]["interaction"]
    assert "owner_value" not in interaction
    assert "response" not in interaction
    assert "1234" not in str(evidence["payload"])


@pytest.mark.asyncio
async def test_gicc_voice_internal_failure_does_not_invent_device_problem(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, _ = _conversation("Play Interstellar on my TV.")
    telemetry = CapturingGiccTelemetry()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        telemetry=telemetry,
    )

    result = await tools.pursue_owner_goal(None)

    assert result["ok"] is False
    assert result["status"] == "internal_goal_processing_error"
    assert result["retryable"] is True
    truth_note = str(result["truth_note"])
    assert "internally" in truth_note
    assert "Do not claim a device connectivity failure" in truth_note
    assert any(
        event["event"] == "gicc_goal_processing_error" for event in telemetry.events
    )


@pytest.mark.asyncio
async def test_gicc_voice_status_reads_canonical_objective_projection(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, _ = _conversation("What is happening with my TV task?")
    payload = {
        "goal_id": "goal_tv",
        "overall_state": "waiting_owner",
        "phase": "waiting_owner_approval",
        "verified_completion": False,
    }
    objective = SimpleNamespace(public_payload=lambda: payload)
    resolver = SimpleNamespace(
        list_active=lambda *, limit: (objective,),
        resolve=lambda goal_id: objective,
    )
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        objective_status=resolver,  # type: ignore[arg-type]
    )

    listed = await tools.list_owner_objectives(None)  # type: ignore[arg-type]
    found = await tools.get_owner_objective_status(
        None,  # type: ignore[arg-type]
        goal_id="goal_tv",
    )

    assert listed["objectives"] == [payload]
    assert found["goal_id"] == "goal_tv"
    assert found["verified_completion"] is False
    assert "Never infer overall completion" in str(listed["truth_note"])
