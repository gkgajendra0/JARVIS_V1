from pathlib import Path

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
from jarvis.goal_intelligence.composition import GoalIntelligenceCoordinator
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import GoalKind, WorldEntityRefV1
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
        )
    )
    registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Bedroom TV",
            aliases=("my tv",),
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
