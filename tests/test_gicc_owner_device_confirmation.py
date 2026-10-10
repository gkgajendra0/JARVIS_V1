"""Offline proof that only explicit owner inventory confirmation promotes a hint."""

from __future__ import annotations

import time
from pathlib import Path

from tests.test_gicc_network_consent import _data

from jarvis.goal_intelligence.models import (
    EntityLifecycleState,
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
    OwnerGoalV2,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.owner_device_confirmation import (
    confirm_single_discovered_device,
)
from jarvis.goal_intelligence.windows_aep import AepIdentityCandidateV1
from jarvis.goal_intelligence.world import WorldRegistry


def _evidence(*, address: str, now: int) -> str:
    candidate = AepIdentityCandidateV1(
        endpoint_id=f"test-endpoint-{address}",
        address=address,
        protocol="upnp",
        name="Unverified television advertisement",
        manufacturer="ExampleVendor",
        model="Screen",
        category="Media Device",
        observed_at_epoch=now,
    )
    return f"windows_aep_discovered_unverified:{address}:{candidate.evidence_ref}"


def test_owner_confirmed_unique_recent_hint_creates_identity_not_access(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    now = int(time.time())
    evidence = _evidence(address="192.168.1.10", now=now)
    updated = store.update_information_need_state(
        need.information_need_id,
        InformationNeedState.WAITING_FOR_OWNER,
        expected_revision=need.revision,
        evidence_refs=(evidence,),
    )
    assert updated.resolution_ref is None
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id="wrong-owner-session",
            owner_turn_id="explicit-owner-turn-1",
        )
        is None
    )
    assert world.entities() == ()

    confirmed = confirm_single_discovered_device(
        store=store,
        world=world,
        goal_id=goal.goal_id,
        information_need_id=need.information_need_id,
        session_id=goal.source_session_id,
        owner_turn_id="explicit-owner-turn-1",
    )
    assert confirmed is not None
    assert confirmed.entity_type == "media_player"
    assert confirmed.lifecycle_state is EntityLifecycleState.ACTIVE
    assert "my tv" in confirmed.aliases
    assert any(x.startswith("owner_inventory:") for x in confirmed.provenance_refs)
    assert any(
        x.startswith("unverified_aep_evidence:") for x in confirmed.provenance_refs
    )
    assert world.bindings(entity_id=confirmed.entity_id) == ()
    assert store.get_information_need(need.information_need_id).resolution_ref is None
    assert len(world.entities()) == 1
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="explicit-owner-turn-1",
        )
        == confirmed
    )


def test_owner_confirmation_refuses_ambiguous_or_stale_candidates(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    now = int(time.time())
    first = store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(_evidence(address="192.168.1.10", now=now),),
    )
    second = store.update_information_need_state(
        need.information_need_id,
        first.state,
        expected_revision=first.revision,
        evidence_refs=(_evidence(address="192.168.1.11", now=now),),
    )
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="owner-multiple",
        )
        is None
    )
    assert world.entities() == ()

    # Moving to a resolved/cancelled need must not revive device discovery.
    store.update_information_need_state(
        need.information_need_id,
        InformationNeedState.CANCELLED,
        expected_revision=second.revision,
    )
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="owner-late",
        )
        is None
    )


def test_owner_confirmation_never_creates_duplicate_of_known_tv(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    known = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Existing living room TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:prior_tv",),
        )
    )
    updated = store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(_evidence(address="192.168.1.10", now=int(time.time())),),
    )
    assert updated is not None
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="owner-known",
        )
        is None
    )
    assert world.entities() == (known,)


def test_owner_confirmation_rejects_expired_advertisements(tmp_path: Path) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    stale_evidence = _evidence(address="192.168.1.10", now=int(time.time()) - 600)
    store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(stale_evidence,),
    )
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="stale-owner-affirmation",
        )
        is None
    )
    assert world.entities() == ()


def test_owner_identity_confirmation_cannot_be_replayed_across_goals(
    tmp_path: Path,
) -> None:
    store, first_goal, first_need = _data(tmp_path)
    world = WorldRegistry(store)
    now = int(time.time())
    store.update_information_need_state(
        first_need.information_need_id,
        first_need.state,
        expected_revision=first_need.revision,
        evidence_refs=(_evidence(address="192.168.1.10", now=now),),
    )
    second_goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=first_goal.source_session_id,
            source_turn_id="independent-second-device-request",
            exact_owner_request="Identify another TV",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Identify second television",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    second_need = store.create_information_need(
        InformationNeedV1.create(
            goal_id=second_goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="my TV",
            required_fact="second canonical media_player",
            why_required="unidentified physical device",
            allowed_resolution_sources=(
                "world_registry",
                "current_state_observation",
                "bounded_local_discovery",
                "owner_input",
            ),
            answer_schema={"type": "entity_id", "entity_type": "television"},
        )
    )
    store.update_information_need_state(
        second_need.information_need_id,
        second_need.state,
        expected_revision=second_need.revision,
        evidence_refs=(_evidence(address="192.168.1.11", now=now),),
    )
    first = confirm_single_discovered_device(
        store=store,
        world=world,
        goal_id=first_goal.goal_id,
        information_need_id=first_need.information_need_id,
        session_id=first_goal.source_session_id,
        owner_turn_id="one-spoken-device-confirmation",
    )
    assert first is not None
    # The second goal must not share the same owner speech.
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=second_goal.goal_id,
            information_need_id=second_need.information_need_id,
            session_id=second_goal.source_session_id,
            owner_turn_id="one-spoken-device-confirmation",
        )
        is None
    )
    assert world.entities() == (first,)
