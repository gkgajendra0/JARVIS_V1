from __future__ import annotations

from pathlib import Path

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DiscoveryObservation
from jarvis.goal_intelligence.information import (
    InformationResolutionState,
    InformationResolutionStrategy,
    InformationResolver,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedV1,
    OwnerGoalV2,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.world import (
    EntityResolutionState,
    EntityResolver,
    WorldRegistry,
    canonical_world_entity_type,
)
from jarvis.goal_intelligence.world_discovery import (
    EntityInformationProbe,
    ReviewedLocalServiceEntityDiscovery,
)
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


def _store(path: Path) -> GoalStore:
    work = SQLiteWorkStore(
        path,
        payload_codec=build_default_work_payload_codec(path),
    )
    return GoalStore(work)


def _observation(scope, *, stable_identity: str, endpoints: tuple[str, ...]):
    return DiscoveryObservation(
        observation_id="obs_"
        + canonical_digest(
            {
                "scope": scope.scope_id,
                "stable_identity": stable_identity,
            }
        )[:20],
        scope_id=scope.scope_id,
        scope_digest=canonical_digest(scope),
        adapter_id=scope.adapter_id,
        adapter_version="fake-v1",
        stable_identity=stable_identity,
        endpoints=endpoints,
        observed_at_epoch=1.0,
        expires_at_epoch=60.0,
        evidence_digest=canonical_digest(
            {
                "stable_identity": stable_identity,
                "endpoints": list(endpoints),
            }
        ),
    )


class _FakeBroker:
    def __init__(self) -> None:
        self.scopes = []

    def discover(self, scope):
        self.scopes.append(scope)
        if scope.protocol == "mdns":
            return (
                _observation(
                    scope,
                    stable_identity="mdns:living-room-media",
                    endpoints=("tcp://192.168.1.40:7000",),
                ),
            )
        if scope.protocol == "ssdp":
            return (
                _observation(
                    scope,
                    stable_identity="ssdp:living-room-media",
                    endpoints=(
                        "udp://192.168.1.40:1900",
                        "http://192.168.1.40:8008/device.xml",
                    ),
                ),
            )
        if scope.protocol == "ws_discovery":
            return (
                _observation(
                    scope,
                    stable_identity="onvif:main-gate-camera",
                    endpoints=("http://192.168.1.70/onvif/device_service",),
                ),
            )
        return ()


def test_world_type_aliases_keep_tv_out_of_capability_identity(tmp_path: Path) -> None:
    goals = _store(tmp_path / "world-type.sqlite3")
    world = WorldRegistry(goals)
    entity = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="television",
            canonical_name="Living Room TV",
            provenance_refs=("owner_inventory:living_room",),
        )
    )

    assert canonical_world_entity_type("TV") == "media_player"
    assert canonical_world_entity_type("television") == "media_player"

    resolution = EntityResolver(world).resolve(
        "my tv",
        expected_entity_types=("media_player",),
        allow_discovery=False,
    )

    assert resolution.state is EntityResolutionState.RESOLVED
    assert resolution.entity_id == entity.entity_id


def test_reviewed_discovery_deduplicates_one_media_device_without_device_name() -> None:
    broker = _FakeBroker()
    discovery = ReviewedLocalServiceEntityDiscovery(
        broker=broker,
        timeout_seconds=0.5,
    )

    entities = discovery.discover(
        mention="my tv",
        expected_entity_types=("media_player",),
    )

    assert len(entities) == 1
    assert entities[0].entity_type == "media_player"
    assert entities[0].canonical_name == "Discovered media player 192.168.1.40"
    assert {scope.protocol for scope in broker.scopes} == {"mdns", "ssdp"}
    assert all(scope.target_hints == () for scope in broker.scopes)


def test_reviewed_discovery_resolves_onvif_camera_as_camera_entity() -> None:
    broker = _FakeBroker()
    discovery = ReviewedLocalServiceEntityDiscovery(
        broker=broker,
        timeout_seconds=0.5,
    )

    entities = discovery.discover(
        mention="main gate camera",
        expected_entity_types=("camera",),
    )

    assert len(entities) == 1
    assert entities[0].entity_type == "camera"
    assert entities[0].canonical_name == "Discovered camera 192.168.1.70"
    assert {scope.protocol for scope in broker.scopes} == {"ws_discovery"}
    assert broker.scopes[-1].allowed_device_types == ("network_video_transmitter",)


def test_information_resolver_uses_world_then_discovery_before_owner(
    tmp_path: Path,
) -> None:
    goals = _store(tmp_path / "information-discovery.sqlite3")
    world = WorldRegistry(goals)
    broker = _FakeBroker()
    entity_resolver = EntityResolver(
        world,
        discoveries=(
            ReviewedLocalServiceEntityDiscovery(
                broker=broker,
                timeout_seconds=0.5,
            ),
        ),
    )
    information = InformationResolver(
        store=goals,
        probes=(
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.WORLD_REGISTRY,
            ),
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY,
            ),
        ),
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="session",
            source_turn_id="turn",
            exact_owner_request="Play a movie on my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="The requested movie is playing on my TV.",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    need = goals.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="my tv",
            required_fact="canonical media_player identity for my tv",
            why_required="The target changes which governed capability may act.",
            allowed_resolution_sources=(
                "world_registry",
                "bounded_local_discovery",
                "owner_input",
            ),
            owner_question="Which TV should I use?",
            answer_schema={
                "type": "entity_id",
                "entity_type": "television",
            },
        )
    )

    result = information.resolve(need)

    # Service ads are useful observations, but do not identify a trusted TV.
    assert result.state is InformationResolutionState.NEEDS_OWNER
    assert result.need.resolution_ref is None
    assert any(ref.startswith("discovery:") for ref in result.need.evidence_refs)
    assert world.entities() == ()
    assert result.attempted_strategies == (
        InformationResolutionStrategy.WORLD_REGISTRY,
        InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY,
    )
    assert not any(item.entity_type == "media_player" for item in goals.list_entities())


def test_saved_service_advertisement_cannot_resolve_as_verified_tv(
    tmp_path: Path,
) -> None:
    goals = _store(tmp_path / "untrusted-advertisement.sqlite3")
    world = WorldRegistry(goals)
    observed = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Discovered media player 192.168.1.40",
            aliases=("my tv",),
            provenance_refs=(
                "discovery:obs_fixture",
                "discovery_evidence:unverified",
            ),
        )
    )
    resolution = EntityResolver(world).resolve(
        "my tv",
        expected_entity_types=("media_player",),
        allow_discovery=False,
    )
    assert resolution.state is EntityResolutionState.MISSING
    assert resolution.entity_id is None
    assert observed.entity_id not in resolution.candidate_entity_ids
