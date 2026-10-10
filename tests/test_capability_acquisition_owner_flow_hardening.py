from __future__ import annotations

import asyncio
from pathlib import Path

from jarvis.capabilities.models import (
    CapabilityCatalog,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.hardening import assert_capability_system_invariants
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.runtime_context import (
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
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
from jarvis.goal_intelligence.models import GoalKind, WorldEntityRefV1
from jarvis.goal_intelligence.phase9 import Phase9GoalBridge
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    CapabilityRequirementProposalSet,
    RequirementDeriver,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.hands.provider_adapters import StructuredOutputTelemetry
from jarvis.work.models import WorkPriority
from jarvis.work.store import SQLiteWorkStore

_DISCOVERED_TV_ID = "entity_discovered_living_room_tv"


class _Backend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submissions.append(work_id)
        return work_id


class _QueueStructuredClient:
    provider_name = "hardening"
    model_name = "deterministic"

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


class _DiscoveredTelevision:
    discovery_id = "hardening.discovered_tv.v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def discover(
        self,
        *,
        mention: str,
        expected_entity_types: tuple[str, ...],
    ) -> tuple[WorldEntityRefV1, ...]:
        self.calls.append((mention, expected_entity_types))
        if "media_player" not in expected_entity_types:
            return ()
        return (
            WorldEntityRefV1.create(
                entity_id=_DISCOVERED_TV_ID,
                entity_type="media_player",
                canonical_name="Discovered Living Room TV",
                aliases=("my tv", "living room tv"),
                provenance_refs=("bounded_discovery:test-tv",),
            ),
        )


def _empty_context() -> StaticAcquisitionContextProvider:
    return StaticAcquisitionContextProvider(
        AcquisitionContextV1(
            catalog=CapabilityCatalog(
                sources=(
                    DiscoverySnapshot(
                        source_id="hardening",
                        state=DiscoveryState.AVAILABLE,
                    ),
                ),
                capabilities=(),
            ),
            inventory=(),
        )
    )


def test_owner_turn_with_verified_target_enters_exact_phase9_lineage(
    tmp_path: Path,
) -> None:
    """A reviewed owner inventory target permits GICC-to-Phase9 lineage."""

    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend()
    change_coordinator = ChangeCoordinator(changes, backend)
    capability_context = _empty_context()
    acquisition = CapabilityAcquisitionCoordinator(
        changes=change_coordinator,
        context_provider=capability_context,
    )
    phase9 = Phase9GoalBridge(
        coordinator=acquisition,
        change_store=changes,
        goal_store=goals,
        source_revision_provider=lambda: "a" * 40,
    )

    conversation = ConversationSession(session_id="hardening-owner-session")
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER,
        "Open Hotstar, search The Martian and play it on my TV.",
    )

    interpretation_client = _QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Play The Martian on the owner's television.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my TV",
                    proposed_type="media_player",
                    evidence_turn_ids=[turn.turn_id],
                ),
                ShadowEntityCandidate(
                    mention="The Martian",
                    proposed_type="media_content",
                    evidence_turn_ids=[turn.turn_id],
                ),
            ],
            candidate_completion_predicates=["playback_started"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirement_client = _QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play_media",
                    target_entity_id=_DISCOVERED_TV_ID,
                    target_entity_type="media_player",
                    required_parameters_schema={
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                    expected_postconditions=["playback_started"],
                    reason="Play the selected media on the resolved media player.",
                )
            ]
        )
    )
    discovery = _DiscoveredTelevision()
    world = WorldRegistry(goals)
    world.register_entity(
        WorldEntityRefV1.create(
            entity_id=_DISCOVERED_TV_ID,
            entity_type="media_player",
            canonical_name="Verified Living Room TV",
            aliases=("my tv", "living room tv"),
            provenance_refs=("owner_inventory:verified_living_room_tv",),
        )
    )
    coordinator = GoalIntelligenceCoordinator(
        store=goals,
        interpreter=GoalInterpreter(client=interpretation_client),
        entity_resolver=EntityResolver(
            world,
            discoveries=(discovery,),
        ),
        requirement_deriver=RequirementDeriver(client=requirement_client),
        capability_context=capability_context,
        capability_graph_resolver=CapabilityGraphResolver(store=goals),
        phase9_bridge=phase9,
    )

    result = asyncio.run(
        coordinator.pursue(
            conversation=conversation,
            turn=turn,
        )
    )

    assert result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert result.goal is not None
    assert result.goal.exact_owner_request == turn.text
    assert result.goal.referenced_entity_ids == (_DISCOVERED_TV_ID,)
    assert not discovery.calls  # already reviewed inventory, no redundant scan
    assert goals.get_entity(_DISCOVERED_TV_ID) is not None

    assert result.requirement_result is not None
    requirements = result.requirement_result.graph.requirements
    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.semantic_capability == "media_player.control"
    assert requirement.operation == "play_media"
    assert requirement.target_entity_id == _DISCOVERED_TV_ID
    assert "martian" not in requirement.semantic_capability
    assert "martian" not in requirement.operation

    assert result.capability_analysis is not None
    assert len(result.capability_analysis.gaps) == 1
    gap = result.capability_analysis.gaps[0]
    assert gap.reusable_capability_family == "media_player.control"
    assert gap.minimum_required_operations == ("play_media",)
    assert gap.target_entity_id == _DISCOVERED_TV_ID
    assert "martian" not in str(gap.canonical_payload()).casefold()

    assert len(result.phase9_admissions) == 1
    admission = result.phase9_admissions[0]
    assert admission.admission.change is not None
    change = admission.admission.change
    assert change.source_session_id == f"gicc:{result.goal.goal_id}"
    assert change.source_turn_id == f"gap:{gap.gap_id}"
    assert "martian" not in change.request.casefold()
    assert "hotstar" not in change.request.casefold()

    link = changes.latest_artifact(change.change_id, "gicc_capability_gap_link")
    target = changes.latest_artifact(change.change_id, "gicc_target_context")
    assert link is not None
    assert target is not None
    assert link.payload["motivating_goal_id"] == result.goal.goal_id
    assert link.payload["gap_id"] == gap.gap_id
    assert link.payload["engineering_change_id"] == change.change_id
    assert target.payload["target_entity_id"] == _DISCOVERED_TV_ID
    assert target.payload["canonical_name"] == "Verified Living Room TV"

    source = changes.current_stage_attempt(change.change_id, "acquisition")
    assert source is not None
    assert source.work_id == admission.admission.acquisition_work_id
    assert source.work_id in backend.submissions

    continuations = goals.list_continuations(goal_id=result.goal.goal_id)
    assert len(continuations) == 1
    continuation = continuations[0]
    assert continuation.blocked_by_id == gap.gap_id
    assert continuation.work_ids == (source.work_id,)

    report = assert_capability_system_invariants(
        goal_store=goals,
        change_store=changes,
        goal_id=result.goal.goal_id,
    )
    assert report.passed is True
