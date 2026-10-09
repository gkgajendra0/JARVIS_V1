"""Read-only inventory must not claim physical control access."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from tools.research import owner_environment_readonly_preflight as probe
from tools.research.owner_environment_readonly_preflight import (
    discover_read_only,
    reviewed_device_scopes,
)

from jarvis.engineering_substrate.contracts import DiscoveryScope
from jarvis.goal_intelligence.models import WorldEntityRefV1
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


@dataclass
class _Observation:
    observation_id: str = "observation-owned"
    stable_identity: str = "device-alias"
    endpoints: tuple[str, ...] = ("http://192.168.50.20:9000",)
    expires_at_epoch: float = 5000.0
    evidence_digest: str = "a" * 64


class _FakeBroker:
    def __init__(self, observations):
        self.scopes: list[DiscoveryScope] = []
        self.observations = observations

    def discover(self, scope):
        self.scopes.append(scope)
        return self.observations


def test_device_inventory_uses_only_existing_registered_bounded_scopes() -> None:
    scopes = reviewed_device_scopes()
    assert len(scopes) == 2
    assert {scope.adapter_id for scope in scopes} == {
        "mdns_dns_sd.v1",
        "ssdp_upnp.v1",
    }
    assert all(scope.max_results <= 16 for scope in scopes)
    assert all(scope.timeout_seconds <= 2.0 for scope in scopes)
    assert all("ssdp:all" not in scope.allowed_service_types for scope in scopes)
    assert all(not scope.allowed_device_types for scope in scopes)


def test_read_only_discovery_reports_observations_not_access() -> None:
    broker = _FakeBroker((_Observation(),))
    result = discover_read_only(broker)
    assert len(result) == 2
    assert all(row["status"] == "observed" for row in result)
    assert all(row["observation_count"] == 1 for row in result)
    assert all("authenticated" not in row for row in result)
    assert all("authorized" not in row for row in result)
    assert all("protocol" not in row for row in result)
    assert len(broker.scopes) == 2


def test_empty_discovery_does_not_invent_an_accessible_device() -> None:
    result = discover_read_only(_FakeBroker(()))
    assert len(result) == 2
    assert all(row["status"] == "no_observations" for row in result)
    assert all(row["observation_count"] == 0 for row in result)


def test_cameras_are_opt_in_and_use_reviewed_onvif_policy() -> None:
    scopes = reviewed_device_scopes(include_cameras=True)
    assert len(scopes) == 3
    assert scopes[-1].adapter_id == "onvif_ws_discovery.v1"
    assert scopes[-1].allowed_device_types == ("network_video_transmitter",)


def test_owner_inventory_reads_existing_protected_world_without_modifying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "owner.sqlite3"
    work = SQLiteWorkStore(
        db, payload_codec=build_default_work_payload_codec(db)
    )
    world = GoalStore(work)
    tv = world.put_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Known television",
            provenance_refs=("owner_inventory:screen",),
        )
    )
    monkeypatch.setattr(probe, "default_work_store_path", lambda: db)
    snapshot = probe.known_world_entities()
    assert snapshot["status"] == "read_only"
    assert len(snapshot["entities"]) == 1
    assert snapshot["entities"][0]["entity_id"] == tv.entity_id
    assert snapshot["entities"][0]["canonical_name"] == "Known television"
    assert "authorized_operations" not in snapshot["entities"][0]
    assert world.get_entity(tv.entity_id).digest == tv.digest
