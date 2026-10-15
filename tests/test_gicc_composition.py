from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.planning import (
    GoalPlanner,
    PlanNodeCandidate,
    PlanProposalV1,
)
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    CapabilityRequirementProposalSet,
    RequirementDeriver,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.hands.provider_adapters import StructuredOutputTelemetry
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class QueueStructuredClient:
    provider_name = "fake"
    model_name = "fake-gicc"

    def __init__(self, *outputs) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    async def parse_with_telemetry(
        self,
        *,
        system_prompt,
        input_payload,
        response_model,
    ):
        del system_prompt, input_payload, response_model
        self.calls += 1
        return StructuredOutputTelemetry(
            parsed=self.outputs.pop(0),
            usage={},
            usage_observed=False,
            latency_ms=1.0,
        )


class StaticContext:
    def __init__(self, descriptors=()) -> None:
        descriptors = tuple(descriptors)
        self._context = AcquisitionContextV1(
            catalog=CapabilityCatalog(
                sources=(
                    DiscoverySnapshot(
                        source_id="test",
                        state=DiscoveryState.AVAILABLE,
                        capabilities=descriptors,
                    ),
                ),
                capabilities=descriptors,
            ),
            inventory=tuple(
                CapabilityInventoryEntry(
                    capability_id=item.capability_id,
                    capability_key=item.key,
                    management_mode=CapabilityManagementMode.CORE_PINNED,
                )
                for item in descriptors
            ),
        )

    def current(self):
        return self._context


class FakePhase9Bridge:
    def __init__(self) -> None:
        self.gaps = []

    def admit_gap(self, gap, goal):
        self.gaps.append((gap, goal))
        return SimpleNamespace(
            request=SimpleNamespace(gap_id=gap.gap_id),
            admission=SimpleNamespace(acquisition_work_id=f"work-{gap.gap_id}"),
        )


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"z" * 32),
        )
    )


def _conversation(text: str):
    conversation = ConversationSession(session_id="gicc-apply-session")
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, text)
    return conversation, turn


def _computer_descriptor() -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id="lifecycle",
        source_id="app",
        kind=CapabilityKind.NATIVE_API,
        name="Windows application lifecycle",
        description="Open and close applications.",
        operations=("open_app", "close_app"),
        execution_enabled=True,
    )


@pytest.mark.asyncio
async def test_existing_hands_goal_reaches_plan_without_acquisition(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    computer = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="computer",
            canonical_name="Current Computer",
            aliases=("my computer", "my pc"),
            provenance_refs=("machine:current",),
        )
    )
    conversation, turn = _conversation("Open Calculator on my computer.")
    interpretation_client = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Open Calculator on the current computer.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my computer",
                    proposed_type="computer",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_completion_predicates=["app_open"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirement_client = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="computer.application",
                    operation="open_app",
                    target_entity_id=computer.entity_id,
                    target_entity_type="computer",
                    required_parameters_schema={
                        "type": "object",
                        "properties": {"app": {"type": "string"}},
                    },
                    expected_postconditions=["app_open"],
                    reason="Open the requested application.",
                )
            ]
        )
    )
    planner_client = QueueStructuredClient(
        PlanProposalV1(
            nodes=[
                PlanNodeCandidate(
                    node_type="action",
                    summary="Open Calculator.",
                    capability_key="app:lifecycle",
                    operation="open_app",
                    parameters={"app": "Calculator"},
                    postcondition_ref="app_open",
                ),
                PlanNodeCandidate(
                    node_type="verify",
                    summary="Verify Calculator opened.",
                    postcondition_ref="app_open",
                    depends_on_indexes=[0],
                ),
            ]
        )
    )
    phase9 = FakePhase9Bridge()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpretation_client),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirement_client),
        capability_context=StaticContext((_computer_descriptor(),)),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
        planner=GoalPlanner(client=planner_client),
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.PLAN_READY
    assert result.plan is not None
    assert phase9.gaps == []
    assert result.capability_analysis is not None
    assert result.capability_analysis.gaps == ()
    assert result.goal is not None
    assert result.goal.referenced_entity_ids == (computer.entity_id,)


@pytest.mark.asyncio
async def test_tv_goal_creates_reusable_gap_and_phase9_link(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    tv = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
            provenance_refs=("owner-config:media-target",),
        )
    )
    conversation, turn = _conversation("I want to watch Transporter on my TV.")
    interpretation_client = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Watch Transporter on the living-room TV.",
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
    requirement_client = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play",
                    target_entity_id=tv.entity_id,
                    target_entity_type="media_player",
                    required_parameters_schema={
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                    expected_postconditions=["playback_started"],
                    reason="Start selected media playback.",
                )
            ]
        )
    )
    phase9 = FakePhase9Bridge()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpretation_client),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirement_client),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert len(result.phase9_admissions) == 1
    assert len(phase9.gaps) == 1
    gap = phase9.gaps[0][0]
    assert gap.reusable_capability_family == "media_player.control"
    assert gap.minimum_required_operations == ("play",)
    assert "transporter" not in str(gap.canonical_payload()).casefold()
    assert result.plan is not None


@pytest.mark.asyncio
async def test_ambiguous_tv_creates_one_exact_owner_interaction(
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
                provenance_refs=(f"owner-config:{name}",),
            )
        )
    conversation, turn = _conversation("Play Transporter on my TV.")
    interpretation_client = QueueStructuredClient(
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
            candidate_completion_predicates=["playback_started"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirement_client = QueueStructuredClient()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpretation_client),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirement_client),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_INFORMATION
    assert len(result.information_needs) == 1
    assert len(result.information_interactions) == 1
    assert requirement_client.calls == 0


@pytest.mark.asyncio
async def test_repeated_same_turn_returns_existing_goal_without_new_model_call(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="computer",
            canonical_name="Current Computer",
            aliases=("my computer",),
            provenance_refs=("machine:current",),
        )
    )
    conversation, turn = _conversation("Open Calculator on my computer.")
    interpretation_client = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Open Calculator.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my computer",
                    proposed_type="computer",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_completion_predicates=["app_open"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirement_client = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="computer.application",
                    operation="open_app",
                    target_entity_type="computer",
                    expected_postconditions=["app_open"],
                    reason="Open app.",
                )
            ]
        )
    )
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpretation_client),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirement_client),
        capability_context=StaticContext((_computer_descriptor(),)),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
    )

    first = await coordinator.pursue(conversation=conversation, turn=turn)
    second = await coordinator.pursue(conversation=conversation, turn=turn)

    assert first.goal is not None
    assert second.disposition is GoalIntakeDisposition.EXISTING_GOAL
    assert second.goal is not None
    assert second.goal.goal_id == first.goal.goal_id
    assert interpretation_client.calls == 1
