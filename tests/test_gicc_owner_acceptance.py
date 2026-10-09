import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_gicc_composition import (
    FakePhase9Bridge,
    QueueStructuredClient,
    StaticContext,
    _computer_descriptor,
    _conversation,
    _store,
)

from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
)
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.information import (
    InformationResolutionStrategy,
    InformationResolver,
    restore_bound_information_interaction,
)
from jarvis.goal_intelligence.local_network import (
    WindowsNeighborInformationProbe,
    WindowsPassiveNeighborBackend,
)
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    InformationNeedState,
    PlanNodeType,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.monitoring import GICC_MONITOR_EVENT_CONTRACT
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
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.goal_intelligence.world_discovery import EntityInformationProbe
from jarvis.hands.provider_adapters import StructuredOutputTelemetry


class CallbackStructuredClient:
    provider_name = "fake"
    model_name = "fake-gicc"

    def __init__(self, callback) -> None:
        self.callback = callback
        self.calls = 0

    async def parse_with_telemetry(
        self,
        *,
        system_prompt,
        input_payload,
        response_model,
    ):
        del system_prompt, response_model
        self.calls += 1
        return StructuredOutputTelemetry(
            parsed=self.callback(input_payload),
            usage={},
            usage_observed=False,
            latency_ms=1.0,
        )


def _events(telemetry: CapturingGiccTelemetry) -> list[str]:
    return [str(item["event"]) for item in telemetry.events]


@pytest.mark.asyncio
async def test_owner_acceptance_scenario_1_tv_uses_reusable_gap_only(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    tv = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
            provenance_refs=("owner-config:living-room-tv",),
        )
    )
    conversation, turn = _conversation("Jarvis, I want to watch Transporter on my TV.")
    interpreter = QueueStructuredClient(
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
    requirements = QueueStructuredClient(
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
    telemetry = CapturingGiccTelemetry()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
        telemetry=telemetry,
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert len(result.phase9_admissions) == 1
    gap = result.capability_analysis.gaps[0]
    assert gap.reusable_capability_family == "media_player.control"
    assert gap.minimum_required_operations == ("play",)
    assert "transporter" not in str(gap.canonical_payload()).casefold()
    assert "gicc_capability_gap_created" in _events(telemetry)
    assert "gicc_phase9_linked" in _events(telemetry)


@pytest.mark.asyncio
async def test_owner_acceptance_scenario_2_gate_becomes_monitor_plan_without_question(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    camera = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="camera",
            canonical_name="Main Gate Camera",
            aliases=("gate camera",),
            provenance_refs=("owner-config:main-gate-camera",),
        )
    )
    registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="entrance",
            canonical_name="Main Gate",
            aliases=("main gate",),
            relation_ids=(camera.entity_id,),
            provenance_refs=("owner-config:main-gate",),
        )
    )
    conversation, turn = _conversation(
        "Jarvis, monitor my main gate and let me know once a delivery agent "
        "is standing at the door."
    )
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome=(
                "Notify the owner when a delivery agent is verified at the main gate."
            ),
            goal_kind=GoalKind.MONITORING,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="main gate",
                    proposed_type="camera",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_completion_predicates=["owner_notified"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="camera.observe",
                    operation="read_live_stream",
                    target_entity_id=camera.entity_id,
                    target_entity_type="camera",
                    expected_postconditions=["stream_available"],
                    observation_requirements=["candidate_frame_available"],
                    reason="Observe the gate camera only when needed.",
                ),
                CapabilityRequirementProposal(
                    semantic_capability="vision.perceive",
                    operation="detect_delivery_agent",
                    expected_postconditions=["delivery_agent_verified"],
                    observation_requirements=["person_and_package_evidence"],
                    reason="Verify a delivery-agent candidate locally.",
                    depends_on_indexes=[0],
                ),
                CapabilityRequirementProposal(
                    semantic_capability="monitor.evaluate",
                    operation="evaluate",
                    expected_postconditions=["condition_true"],
                    observation_requirements=["stable_condition_evidence"],
                    reason="Evaluate the durable monitoring predicate.",
                    depends_on_indexes=[1],
                ),
                CapabilityRequirementProposal(
                    semantic_capability="notification.owner",
                    operation="send",
                    expected_postconditions=["owner_notified"],
                    reason="Notify the owner after verified trigger.",
                    depends_on_indexes=[2],
                ),
            ]
        )
    )
    descriptors = (
        CapabilityDescriptor.create(
            capability_id="observe",
            source_id="camera",
            kind=CapabilityKind.NATIVE_API,
            name="Camera observation",
            description="Read candidate camera observations.",
            operations=("read_live_stream",),
            metadata={
                "semantic_capability_family": "camera.observe",
                "target_entity_types": ["camera"],
                "observation_operations": ["read_live_stream"],
                "monitor_event_contract": GICC_MONITOR_EVENT_CONTRACT,
            },
            execution_enabled=True,
        ),
        CapabilityDescriptor.create(
            capability_id="perceive",
            source_id="vision",
            kind=CapabilityKind.NATIVE_API,
            name="Local perception",
            description="Detect delivery-agent candidates.",
            operations=("detect_delivery_agent",),
            metadata={
                "semantic_capability_family": "vision.perceive",
                "observation_operations": ["detect_delivery_agent"],
                "monitor_event_contract": GICC_MONITOR_EVENT_CONTRACT,
            },
            execution_enabled=True,
        ),
        CapabilityDescriptor.create(
            capability_id="evaluate",
            source_id="monitor",
            kind=CapabilityKind.NATIVE_API,
            name="Monitor evaluation",
            description="Evaluate monitoring predicates.",
            operations=("evaluate",),
            metadata={"semantic_capability_family": "monitor.evaluate"},
            execution_enabled=True,
        ),
        CapabilityDescriptor.create(
            capability_id="notify",
            source_id="owner",
            kind=CapabilityKind.NATIVE_API,
            name="Owner notification",
            description="Notify the owner.",
            operations=("send",),
            metadata={"semantic_capability_family": "notification.owner"},
            execution_enabled=True,
        ),
    )

    def monitor_plan(input_payload):
        predicate_ids = input_payload["monitor_predicate_ids"]
        assert len(predicate_ids) == 1
        return PlanProposalV1(
            nodes=[
                PlanNodeCandidate(
                    node_type=PlanNodeType.MONITOR,
                    summary="Monitor the verified main-gate predicate.",
                    monitor_predicate_id=predicate_ids[0],
                )
            ]
        )

    telemetry = CapturingGiccTelemetry()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(descriptors),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        planner=GoalPlanner(client=CallbackStructuredClient(monitor_plan)),
        telemetry=telemetry,
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.PLAN_READY
    assert result.information_interactions == ()
    assert result.capability_analysis is not None
    assert result.capability_analysis.gaps == ()
    assert result.plan is not None
    assert tuple(node.node_type for node in result.plan.nodes) == (
        PlanNodeType.MONITOR,
    )
    assert "gicc_plan_created" in _events(telemetry)


@pytest.mark.asyncio
async def test_owner_acceptance_scenario_3_existing_hands_needs_no_acquisition(
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
    interpreter = QueueStructuredClient(
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
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="computer.application",
                    operation="open_app",
                    target_entity_id=computer.entity_id,
                    target_entity_type="computer",
                    expected_postconditions=["app_open"],
                    reason="Open the requested application.",
                )
            ]
        )
    )
    planner = QueueStructuredClient(
        PlanProposalV1(
            nodes=[
                PlanNodeCandidate(
                    node_type=PlanNodeType.ACTION,
                    summary="Open Calculator.",
                    capability_key="app:lifecycle",
                    operation="open_app",
                    parameters={"app": "Calculator"},
                    postcondition_ref="app_open",
                ),
                PlanNodeCandidate(
                    node_type=PlanNodeType.VERIFY,
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
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext((_computer_descriptor(),)),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
        planner=GoalPlanner(client=planner),
        telemetry=CapturingGiccTelemetry(),
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.PLAN_READY
    assert result.capability_analysis is not None
    assert result.capability_analysis.gaps == ()
    assert phase9.gaps == []


@pytest.mark.asyncio
async def test_owner_acceptance_scenario_4_ambiguity_asks_one_bound_question(
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
    interpreter = QueueStructuredClient(
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
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=QueueStructuredClient()),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        telemetry=CapturingGiccTelemetry(),
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_INFORMATION
    assert len(result.information_needs) == 1
    assert len(result.information_interactions) == 1
    interaction = result.information_interactions[0]
    assert (
        interaction["information_need_id"]
        == result.information_needs[0].information_need_id
    )
    assert interaction["goal_id"] == result.goal.goal_id


@pytest.mark.asyncio
async def test_owner_acceptance_scenario_5_restart_restores_exact_clarification(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "work.sqlite3"

    def store():
        from jarvis.goal_intelligence.store import GoalStore
        from jarvis.work.privacy import ProtectedWorkPayloadCodec
        from jarvis.work.store import SQLiteWorkStore

        return GoalStore(
            SQLiteWorkStore(
                db_path,
                payload_codec=ProtectedWorkPayloadCodec(b"z" * 32),
            )
        )

    first_store = store()
    registry = WorldRegistry(first_store)
    for name in ("Living Room TV", "Bedroom TV"):
        registry.register_entity(
            WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name=name,
                aliases=("my tv",),
            )
        )
    conversation = ConversationSession(session_id="gicc-restart-session")
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER,
        "Play Transporter on my TV.",
    )
    coordinator = GoalIntelligenceCoordinator(
        store=first_store,
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
        capability_graph_resolver=CapabilityGraphResolver(store=first_store),
        telemetry=CapturingGiccTelemetry(),
    )
    result = await coordinator.pursue(conversation=conversation, turn=turn)
    interaction_id = str(result.information_interactions[0]["interaction_id"])
    need_id = result.information_needs[0].information_need_id
    goal_id = result.goal.goal_id

    restarted_store = store()
    restored_need = restarted_store.get_information_need(need_id)
    restored_interaction = restore_bound_information_interaction(
        store=restarted_store,
        interaction_id=interaction_id,
    )

    assert restored_need is not None
    assert restored_need.state is InformationNeedState.WAITING_FOR_OWNER
    assert restored_need.goal_id == goal_id
    assert restored_interaction.goal_id == goal_id
    assert restored_interaction.information_need_id == need_id


@pytest.mark.asyncio
async def test_tv_identity_is_resolved_before_acquisition_if_model_omits_entity(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    tv = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Known living-room TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:living_room",),
        )
    )
    conversation, turn = _conversation("Acquire control of my TV.")
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Control my existing TV.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[],
            candidate_completion_predicates=["tv_controlled"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="issue_supported_control",
                    target_entity_type="television",
                    expected_postconditions=["tv_controlled"],
                    reason="A reusable TV control operation is missing.",
                )
            ]
        )
    )
    entity_resolver = EntityResolver(registry)
    information = InformationResolver(
        store=store,
        probes=(
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.WORLD_REGISTRY,
            ),
        ),
    )
    phase9 = FakePhase9Bridge()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=entity_resolver,
        information_resolver=information,
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert len(phase9.gaps) == 1
    assert phase9.gaps[0][0].target_entity_id == tv.entity_id
    assert result.goal is not None
    assert tv.entity_id in result.goal.referenced_entity_ids


@pytest.mark.asyncio
async def test_missing_tv_cannot_start_device_specific_acquisition(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    conversation, turn = _conversation("Acquire control of my TV.")
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Control my television.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[],
            candidate_completion_predicates=["tv_controlled"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="issue_supported_control",
                    target_entity_type="television",
                    expected_postconditions=["tv_controlled"],
                    reason="A reusable TV control operation is missing.",
                )
            ]
        )
    )
    # Simulate the owner's Windows LAN observation. A neighbor with a
    # syntactically valid address/MAC is still not a proven TV identity.
    windows_backend = WindowsPassiveNeighborBackend(
        platform="win32",
        clock=lambda: 1000.0,
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "InterfaceAlias": "Ethernet",
                        "InterfaceIndex": 2,
                        "IPAddress": "192.168.1.10",
                        "LinkLayerAddress": "50-BA-02-AE-0D-18",
                        "State": "Stale",
                    }
                ]
            ),
        ),
    )
    information_resolver = InformationResolver(
        store=store,
        probes=(WindowsNeighborInformationProbe(windows_backend),),
    )
    phase9 = FakePhase9Bridge()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        information_resolver=information_resolver,
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
    )

    result = await coordinator.pursue(conversation=conversation, turn=turn)

    assert result.disposition is GoalIntakeDisposition.WAITING_INFORMATION
    assert not phase9.gaps
    assert len(result.information_needs) == 1
    assert result.information_needs[0].answer_schema == {
        "type": "entity_id",
        "entity_type": "media_player",
    }
    assert result.information_needs[0].state is InformationNeedState.WAITING_FOR_OWNER
    assert any(
        item.startswith("windows_neighbor_unverified:192.168.1.10:")
        for item in result.information_needs[0].evidence_refs
    )
    assert registry.entities() == ()
