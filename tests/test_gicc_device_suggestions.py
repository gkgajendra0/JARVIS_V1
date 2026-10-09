"""Unverified Windows identity hints are useful only as fresh owner choices."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.test_gicc_network_consent import _data

from jarvis.goal_intelligence.device_suggestions import (
    pending_owner_device_suggestions,
)
from jarvis.goal_intelligence.models import InformationNeedState
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.windows_aep import AepIdentityCandidateV1


def _evidence(
    address: str = "192.168.1.22",
    *,
    observed: int = 1000,
    manufacturer: str = "Example",
    model: str = "Family 4K",
    category: str = "Media",
    protocol: str = "upnp",
    correlated: bool = False,
) -> str:
    candidate = AepIdentityCandidateV1(
        endpoint_id="synthetic-endpoint",
        address=address,
        protocol=protocol,
        name="Family television",
        manufacturer=manufacturer,
        model=model,
        category=category,
        observed_at_epoch=observed,
    )
    kind = (
        "windows_aep_neighbor_correlated_unverified"
        if correlated
        else "windows_aep_discovered_unverified"
    )
    return f"{kind}:{address}:{candidate.evidence_ref}"


def _add(store, need, *refs):
    return store.update_information_need_state(
        need.information_need_id,
        InformationNeedState.WAITING_FOR_OWNER,
        expected_revision=need.revision,
        evidence_refs=refs,
    )


def test_fresh_corroborated_hint_is_presented_without_creating_identity(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    ref = _evidence(correlated=True)
    updated = _add(store, need, ref)
    runtime = GiccApplyRuntime(
        store=store,
        world=object(),
        coordinator=object(),
        dispatcher=object(),
        telemetry=object(),
        capability_runtime=object(),
    )

    options = runtime.pending_network_device_suggestions(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    )
    assert len(options) == 1
    assert options[0].display_hint == "example family 4k"
    assert options[0].address == "192.168.1.22"
    assert options[0].neighbor_correlated
    assert options[0].evidence_ref == ref
    assert store.list_entities() == ()
    assert store.get_information_need(need.information_need_id) == updated


@pytest.mark.parametrize(
    "now_epoch",
    (999, 1121, 999999999),
)
def test_future_or_expired_metadata_cannot_be_displayed(
    tmp_path: Path, now_epoch: int
) -> None:
    store, goal, need = _data(tmp_path)
    _add(store, need, _evidence())
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=now_epoch,
    ) == ()


def test_cross_session_and_noncanonical_payload_denied(tmp_path: Path) -> None:
    store, goal, need = _data(tmp_path)
    valid = _evidence()
    invalid_address = valid.replace(
        "windows_aep_unverified:upnp:192.168.1.22",
        "windows_aep_unverified:upnp:192.168.1.33",
    )
    _add(
        store,
        need,
        "windows_aep_discovered_unverified:8.8.8.8:"
        + valid.split(":", 2)[2],
        invalid_address,
        "provider:unverified-other-system",
    )
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id="other-session",
        now_epoch=1001,
    ) == ()
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    ) == ()


def test_conflicting_recent_identification_is_not_suggested(tmp_path: Path) -> None:
    store, goal, need = _data(tmp_path)
    _add(
        store,
        need,
        _evidence(manufacturer="Vendor A", correlated=True),
        _evidence(manufacturer="Vendor B", protocol="dns_sd"),
    )
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    ) == ()


def test_suggestion_requires_real_vendor_or_model(tmp_path: Path) -> None:
    store, goal, need = _data(tmp_path)
    _add(store, need, _evidence(manufacturer="", model=""))
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    ) == ()


def test_owner_cannot_get_suggestions_for_resolved_need(tmp_path: Path) -> None:
    store, goal, need = _data(tmp_path)
    current = _add(store, need, _evidence())
    store.resolve_information_need(
        need.information_need_id,
        resolution_ref="entity_previously_verified",
        expected_revision=current.revision,
    )
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    ) == ()


def test_owner_only_information_does_not_reveal_unverified_network_choices(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path, sources=("owner_input",))
    _add(store, need, _evidence())
    assert pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    ) == ()
