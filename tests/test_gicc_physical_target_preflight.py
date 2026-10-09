"""Adversarial physical-target binding checks for the GICC -> Phase 9 boundary."""

from __future__ import annotations

import pytest

from jarvis.goal_intelligence.models import (
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    GoalKind,
    OwnerGoalV2,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.target_preflight import (
    PhysicalTargetPreflightError,
    bind_physical_target_requirements,
)


def _entity(name: str, kind: str = "media_player") -> WorldEntityRefV1:
    return WorldEntityRefV1.create(
        entity_type=kind,
        canonical_name=name,
        provenance_refs=("reviewed-owner-inventory",),
    )


def _graph(
    *,
    target_type: str | None = "television",
    target_id: str | None = None,
    family: str = "media_player.control",
) -> CapabilityRequirementGraphV1:
    goal = OwnerGoalV2.create(
        source_session_id="session",
        source_turn_id="turn",
        exact_owner_request="Control my TV",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="TV responds",
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability=family,
        operation="issue_supported_control",
        target_entity_type=target_type,
        target_entity_id=target_id,
        expected_postconditions=("confirmed_external_control",),
        reason="Use a real existing target",
    )
    return CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
        edges=((requirement.requirement_id, "confirmed_external_control"),),
        completion_predicates=("confirmed_external_control",),
    )


def test_missing_device_does_not_get_model_generated_binding() -> None:
    graph = _graph()
    new, missing = bind_physical_target_requirements(
        graph, referenced_entity_ids=(), get_entity=lambda _: None
    )
    assert new is graph
    assert missing == ("media_player",)


def test_one_canonical_device_binds_and_rekeys_digest_bound_edges() -> None:
    tv = _entity("Owner's television")
    graph = _graph()
    new, missing = bind_physical_target_requirements(
        graph, referenced_entity_ids=(tv.entity_id,), get_entity=lambda _: tv
    )
    assert missing == ()
    assert new.digest != graph.digest
    assert new.requirements[0].target_entity_id == tv.entity_id
    assert new.requirements[0].target_entity_type == "media_player"
    assert new.edges[0][0] == new.requirements[0].requirement_id
    assert new.edges[0][1] == "confirmed_external_control"


def test_two_matching_physical_devices_require_clarification() -> None:
    tv_a = _entity("Living room TV")
    tv_b = _entity("Guest room TV")
    found = {tv_a.entity_id: tv_a, tv_b.entity_id: tv_b}
    graph = _graph()
    new, missing = bind_physical_target_requirements(
        graph,
        referenced_entity_ids=(tv_a.entity_id, tv_b.entity_id),
        get_entity=found.get,
    )
    assert new is graph
    assert missing == ("media_player",)


def test_wrong_device_type_is_never_substituted() -> None:
    camera = _entity("Gate camera", "camera")
    graph = _graph(target_id=camera.entity_id)
    with pytest.raises(PhysicalTargetPreflightError):
        bind_physical_target_requirements(
            graph,
            referenced_entity_ids=(camera.entity_id,),
            get_entity=lambda _: camera,
        )


def test_unscoped_generic_software_capability_needs_no_physical_device() -> None:
    graph = _graph(target_type=None, family="notification.owner")
    new, missing = bind_physical_target_requirements(
        graph, referenced_entity_ids=(), get_entity=lambda _: None
    )
    assert new is graph
    assert missing == ()


def test_missing_entity_type_cannot_hide_media_player_requirement() -> None:
    graph = _graph(target_type=None)
    _, missing = bind_physical_target_requirements(
        graph, referenced_entity_ids=(), get_entity=lambda _: None
    )
    assert missing == ("media_player",)
