from pathlib import Path

import pytest

from jarvis.goal_intelligence.models import GoalKind, OwnerGoalV2
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    RequirementDerivationError,
    RequirementValidator,
)


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="session-requirement",
        source_turn_id="turn-requirement",
        exact_owner_request="I want to watch Transporter on my TV.",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="Watch Transporter on the living-room TV.",
        completion_predicates=("playback_started",),
        referenced_entity_ids=("entity_tv",),
        created_at="2026-10-01T13:00:00+00:00",
    )


def test_requirement_validator_keeps_task_parameter_out_of_identity() -> None:
    goal = _goal()
    graph = RequirementValidator().validate(
        goal=goal,
        known_entity_ids=("entity_tv",),
        task_specific_terms=("transporter",),
        proposals=(
            CapabilityRequirementProposal(
                semantic_capability="media_player.control",
                operation="launch_app",
                target_entity_id="entity_tv",
                target_entity_type="media_player",
                expected_postconditions=["media application active"],
                observation_requirements=["active application observable"],
                reason="Open the selected media application.",
            ),
            CapabilityRequirementProposal(
                semantic_capability="media_player.control",
                operation="play",
                target_entity_id="entity_tv",
                target_entity_type="media_player",
                expected_postconditions=["playback started"],
                observation_requirements=["playback state observable"],
                reason="Start selected media playback.",
                depends_on_indexes=[0],
            ),
        ),
    )

    assert {item.semantic_capability for item in graph.requirements} == {
        "media_player.control"
    }
    assert {item.operation for item in graph.requirements} == {
        "launch_app",
        "play",
    }
    assert "transporter" not in str(graph.canonical_payload()).casefold().replace(
        goal.desired_outcome.casefold(),
        "",
    )


def test_task_specific_capability_identity_is_rejected() -> None:
    goal = _goal()

    with pytest.raises(RequirementDerivationError, match="task-specific"):
        RequirementValidator().validate(
            goal=goal,
            known_entity_ids=("entity_tv",),
            task_specific_terms=("transporter",),
            proposals=(
                CapabilityRequirementProposal(
                    semantic_capability="media_player.transporter",
                    operation="play",
                    target_entity_id="entity_tv",
                    target_entity_type="media_player",
                    expected_postconditions=["playback started"],
                    reason="Bad task-specific identity.",
                ),
            ),
        )


def test_unbound_target_entity_is_rejected() -> None:
    goal = _goal()

    with pytest.raises(RequirementDerivationError, match="not bound"):
        RequirementValidator().validate(
            goal=goal,
            known_entity_ids=("entity_tv",),
            proposals=(
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play",
                    target_entity_id="invented_tv",
                    target_entity_type="media_player",
                    expected_postconditions=["playback started"],
                    reason="Target was invented.",
                ),
            ),
        )


def test_requirement_without_observable_completion_is_rejected() -> None:
    goal = _goal()

    with pytest.raises(RequirementDerivationError, match="observation"):
        RequirementValidator().validate(
            goal=goal,
            proposals=(
                CapabilityRequirementProposal(
                    semantic_capability="notification.owner",
                    operation="send",
                    reason="Notify owner.",
                ),
            ),
        )
