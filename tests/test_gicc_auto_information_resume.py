"""GICC must autonomously resume resolved device facts without losing context."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.test_gicc_composition import QueueStructuredClient, StaticContext, _conversation, _store

from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.information import (
    InformationProbeResult,
    InformationResolutionStrategy,
    InformationResolver,
)
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
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry


class ReviewedInventorySelectionProbe:
    """Fixture: independent reviewed inventory resolves an ambiguous owner TV."""

    strategy = InformationResolutionStrategy.WORLD_REGISTRY

    def __init__(self, verified_id: str, *, ready: bool) -> None:
        self.verified_id = verified_id
        self.ready = ready
        self.calls = 0

    def resolve(self, need):
        self.calls += 1
        return InformationProbeResult(
            resolution_ref=self.verified_id if self.ready else None,
            evidence_refs=("owner_inventory:verified_owner_selection",),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_during_intake", (True, False))
async def test_resolved_tv_reuses_exact_goal_and_preserves_known_camera(
    tmp_path: Path,
    resolved_during_intake: bool,
) -> None:
    store = _store(tmp_path)
    world = WorldRegistry(store)
    known_camera = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="camera",
            canonical_name="Main Gate Camera",
            aliases=("gate camera",),
            provenance_refs=("owner_inventory:main_gate_camera",),
        )
    )
    living_room = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room Television",
            aliases=("my TV",),
            provenance_refs=("owner_inventory:living_room_tv",),
        )
    )
    world.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Guest Room Television",
            aliases=("my TV",),
            provenance_refs=("owner_inventory:guest_room_tv",),
        )
    )
    conversation, turn = _conversation("Inspect my gate camera and prepare my TV.")
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Prepare reviewed camera and television resources",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="gate camera",
                    proposed_type="camera",
                    evidence_turn_ids=[turn.turn_id],
                ),
                ShadowEntityCandidate(
                    mention="my TV",
                    proposed_type="media_player",
                    evidence_turn_ids=[turn.turn_id],
                ),
            ],
            candidate_completion_predicates=["resources_ready"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="camera.observe",
                    operation="read_live_stream",
                    target_entity_id=known_camera.entity_id,
                    target_entity_type="camera",
                    expected_postconditions=["camera_observable"],
                    reason="Access reviewed camera",
                ),
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play",
                    target_entity_id=living_room.entity_id,
                    target_entity_type="media_player",
                    expected_postconditions=["tv_ready"],
                    reason="Access independently resolved television",
                ),
            ]
        )
    )
    probe = ReviewedInventorySelectionProbe(
        living_room.entity_id, ready=resolved_during_intake
    )
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(world),
        information_resolver=InformationResolver(store=store, probes=(probe,)),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
    )
    result = await coordinator.pursue(conversation=conversation, turn=turn)
    assert result.goal is not None
    goal_id = result.goal.goal_id
    if not resolved_during_intake:
        assert result.disposition is GoalIntakeDisposition.WAITING_INFORMATION
        assert result.goal.referenced_entity_ids == (known_camera.entity_id,)
        probe.ready = True
        result = await coordinator.continue_goal(goal_id, retry_information=True)

    assert result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert result.goal is not None
    assert result.goal.goal_id == goal_id
    assert set(result.goal.referenced_entity_ids) == {
        known_camera.entity_id,
        living_room.entity_id,
    }
    assert probe.calls >= 1
    assert len(store.list_information_needs(goal_id=goal_id)) == 1
    assert all(
        need.resolution_ref == living_room.entity_id
        for need in store.list_information_needs(goal_id=goal_id)
    )
    assert requirements.calls == 1
