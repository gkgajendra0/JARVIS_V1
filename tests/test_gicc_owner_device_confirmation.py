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


def _evidence(*, address: str, now: int, category: str = "Media Device") -> str:
    candidate = AepIdentityCandidateV1(
        endpoint_id=f"test-endpoint-{address}",
        address=address,
        protocol="upnp",
        name="Unverified television advertisement",
        manufacturer="ExampleVendor",
        model="Screen",
        category=category,
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
        evidence_refs=(evidence, "windows_aep_authorized_scope_consumed:upnp"),
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
        evidence_refs=(
            _evidence(address="192.168.1.10", now=now),
            "windows_aep_authorized_scope_consumed:upnp",
        ),
    )
    second = store.update_information_need_state(
        need.information_need_id,
        first.state,
        expected_revision=first.revision,
        evidence_refs=(
            _evidence(address="192.168.1.11", now=now, category="Video Camera"),
            "windows_aep_authorized_scope_consumed:upnp",
        ),
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
        evidence_refs=(
            _evidence(address="192.168.1.10", now=int(time.time())),
            "windows_aep_authorized_scope_consumed:upnp",
        ),
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
        evidence_refs=(stale_evidence, "windows_aep_authorized_scope_consumed:upnp"),
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
        evidence_refs=(
            _evidence(address="192.168.1.10", now=now),
            "windows_aep_authorized_scope_consumed:upnp",
        ),
    )
    second_goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=first_goal.source_session_id,
            source_turn_id="independent-second-device-request",
            exact_owner_request="Identify another camera",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Identify camera",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    second_need = store.create_information_need(
        InformationNeedV1.create(
            goal_id=second_goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="my camera",
            required_fact="second canonical camera",
            why_required="unidentified physical device",
            allowed_resolution_sources=(
                "world_registry",
                "current_state_observation",
                "bounded_local_discovery",
                "owner_input",
            ),
            answer_schema={"type": "entity_id", "entity_type": "camera"},
        )
    )
    store.update_information_need_state(
        second_need.information_need_id,
        second_need.state,
        expected_revision=second_need.revision,
        evidence_refs=(
            _evidence(address="192.168.1.11", now=now, category="Video Camera"),
            "windows_aep_authorized_scope_consumed:upnp",
        ),
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
    # Prove that the second goal was otherwise eligible for confirmation:
    # a genuinely new owner turn can confirm its own authorized camera.
    second = confirm_single_discovered_device(
        store=store,
        world=world,
        goal_id=second_goal.goal_id,
        information_need_id=second_need.information_need_id,
        session_id=second_goal.source_session_id,
        owner_turn_id="new-camera-confirmation-turn",
    )
    assert second is not None
    assert second.entity_type == "camera"
    assert {entity.entity_id for entity in world.entities()} == {
        first.entity_id,
        second.entity_id,
    }


def test_owner_confirmation_requires_consumed_discovery_authority(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(_evidence(address="192.168.1.10", now=int(time.time())),),
    )
    assert (
        confirm_single_discovered_device(
            store=store,
            world=world,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            session_id=goal.source_session_id,
            owner_turn_id="owner-intent-without-authorized-scan",
        )
        is None
    )
    assert world.entities() == ()
    # Nothing was consumed: the owner can safely approve an actual
    # bounded discovery and later confirm the observed device.


def test_multiple_discovered_devices_need_exact_owner_choice(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    world = WorldRegistry(store)
    now = int(time.time())
    first_ref = _evidence(address="192.168.1.10", now=now)
    second_ref = _evidence(address="192.168.1.20", now=now)
    store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(
            first_ref,
            second_ref,
            "windows_aep_authorized_scope_consumed:upnp",
        ),
    )
    common = {
        "store": store,
        "world": world,
        "goal_id": goal.goal_id,
        "information_need_id": need.information_need_id,
        "session_id": goal.source_session_id,
        "owner_turn_id": "owner-explicit-second-tv",
    }
    assert confirm_single_discovered_device(**common) is None
    assert (
        confirm_single_discovered_device(
            **common,
            selected_evidence_ref="made-up-network-device",
        )
        is None
    )
    assert world.entities() == ()

    confirmed = confirm_single_discovered_device(
        **common,
        selected_evidence_ref=second_ref,
    )
    assert confirmed is not None
    assert f"unverified_aep_evidence:{second_ref}" in confirmed.provenance_refs
    assert f"unverified_aep_evidence:{first_ref}" not in confirmed.provenance_refs
    assert world.bindings(entity_id=confirmed.entity_id) == ()


def test_owner_device_claim_rolls_back_if_inventory_insertion_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed store write must not permanently consume the owner's turn."""
    import pytest

    store, goal, need = _data(tmp_path)
    evidence = _evidence(address="192.168.1.10", now=int(time.time()))
    store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(
            evidence,
            "windows_aep_authorized_scope_consumed:upnp",
        ),
    )
    turn_id = "owner-confirm-rollback"
    entry = WorldEntityRefV1.create(
        entity_id=f"owner_confirmed_network:{need.information_need_id}",
        entity_type="media_player",
        canonical_name="Owner-confirmed TV",
        aliases=("my tv",),
        provenance_refs=(
            f"owner_inventory:explicit_device_confirmation:{goal.goal_id}:{turn_id}",
            f"unverified_aep_evidence:{evidence}",
        ),
    )
    original_encode = store._encode

    def fail_only_entity(payload):
        if isinstance(payload, dict) and payload.get("entity_id") == entry.entity_id:
            raise RuntimeError("simulated inventory disk write failure")
        return original_encode(payload)

    monkeypatch.setattr(store, "_encode", fail_only_entity)
    with pytest.raises(RuntimeError, match="simulated inventory disk"):
        store.claim_owner_device_confirmation(
            goal_id=goal.goal_id,
            need_id=need.information_need_id,
            owner_turn_id=turn_id,
            entity=entry,
        )
    monkeypatch.setattr(store, "_encode", original_encode)
    assert store.get_entity(entry.entity_id) is None
    assert store.claim_owner_device_confirmation(
        goal_id=goal.goal_id,
        need_id=need.information_need_id,
        owner_turn_id=turn_id,
        entity=entry,
    )
    assert store.get_entity(entry.entity_id) == entry
    assert not store.claim_owner_device_confirmation(
        goal_id=goal.goal_id,
        need_id=need.information_need_id,
        owner_turn_id=turn_id,
        entity=entry,
    )
