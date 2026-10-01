from pathlib import Path

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.goal_intelligence.models import (
    EntityLifecycleState,
    ResourceBindingV1,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.world import (
    EntityResolutionState,
    EntityResolver,
    WorldRegistry,
)
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


def _registry(tmp_path: Path) -> WorldRegistry:
    work = SQLiteWorkStore(
        tmp_path / "work.sqlite3",
        payload_codec=ProtectedWorkPayloadCodec(b"w" * 32),
    )
    return WorldRegistry(GoalStore(work))


def test_one_known_tv_resolves_my_tv(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    tv = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv", "living room television"),
            provenance_refs=("owner-config:tv",),
        )
    )

    result = EntityResolver(registry).resolve(
        "my TV",
        expected_entity_types=("media_player",),
    )

    assert result.state is EntityResolutionState.RESOLVED
    assert result.entity_id == tv.entity_id


def test_two_tvs_make_generic_reference_ambiguous(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            provenance_refs=("owner-config:living-room-tv",),
        )
    )
    second = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Bedroom TV",
            provenance_refs=("owner-config:bedroom-tv",),
        )
    )

    result = EntityResolver(registry).resolve(
        "my TV",
        expected_entity_types=("media_player",),
    )

    assert result.state is EntityResolutionState.AMBIGUOUS
    assert set(result.candidate_entity_ids) == {first.entity_id, second.entity_id}


def test_main_gate_relation_can_resolve_related_camera(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    camera = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="camera",
            canonical_name="Main Gate Camera",
            provenance_refs=("owner-config:gate-camera",),
        )
    )
    gate = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="entrance",
            canonical_name="Main Gate",
            aliases=("main gate",),
            relation_ids=(camera.entity_id,),
            provenance_refs=("owner-config:main-gate",),
        )
    )

    gate_result = EntityResolver(registry).resolve(
        "main gate",
        expected_entity_types=("entrance",),
    )
    camera_result = EntityResolver(registry).resolve(
        "main gate",
        expected_entity_types=("camera",),
    )

    assert gate_result.entity_id == gate.entity_id
    assert camera_result.entity_id == camera.entity_id
    assert "relation" in camera_result.reason


def test_live_binding_requirement_rejects_unbound_or_stale_resource(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    unbound = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
        )
    )

    missing = EntityResolver(registry).resolve(
        "my tv",
        expected_entity_types=("media_player",),
        require_live_binding=True,
    )
    assert missing.state is EntityResolutionState.MISSING

    registry.register_binding(
        ResourceBindingV1.create(
            entity_id=unbound.entity_id,
            provider_id="vidaa",
            provider_resource_id="tv-1",
            capability_keys=("media_player.control",),
            evidence_refs=("discovery:vidaa",),
        )
    )
    live = EntityResolver(registry).resolve(
        "my tv",
        expected_entity_types=("media_player",),
        require_live_binding=True,
    )
    assert live.state is EntityResolutionState.RESOLVED

    stale_registry = _registry(tmp_path / "stale")
    stale = stale_registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Old TV",
            aliases=("old tv",),
            lifecycle_state=EntityLifecycleState.STALE,
        )
    )
    stale_registry.register_binding(
        ResourceBindingV1.create(
            entity_id=stale.entity_id,
            provider_id="legacy",
            provider_resource_id="old-tv",
        )
    )
    result = EntityResolver(stale_registry).resolve(
        "old tv",
        expected_entity_types=("media_player",),
        require_live_binding=True,
    )
    assert result.state is EntityResolutionState.MISSING

def _computer_catalog(*capability_ids: str) -> CapabilityCatalog:
    descriptors = tuple(
        CapabilityDescriptor.create(
            capability_id=capability_id,
            source_id="computer",
            kind=CapabilityKind.NATIVE_API,
            name=f"Local {capability_id}",
            description="Current computer capability.",
            operations=("execute",),
            execution_enabled=True,
        )
        for capability_id in capability_ids
    )
    snapshot = DiscoverySnapshot(
        source_id="computer",
        state=DiscoveryState.AVAILABLE,
        capabilities=descriptors,
    )
    return CapabilityCatalog(
        sources=(snapshot,),
        capabilities=descriptors,
    )


def test_current_computer_projection_is_restart_safe_and_revisioned(
    tmp_path: Path,
) -> None:
    first = _registry(tmp_path)
    entity, initial = first.project_current_computer(
        _computer_catalog("app")
    )

    restarted = _registry(tmp_path)
    same_entity, refreshed = restarted.project_current_computer(
        _computer_catalog("app", "browser")
    )

    assert same_entity.entity_id == entity.entity_id
    assert refreshed.binding_id == initial.binding_id
    assert refreshed.binding_revision == initial.binding_revision + 1
    assert refreshed.capability_keys == ("computer:app", "computer:browser")
    assert restarted.bindings(entity_id=entity.entity_id) == (refreshed,)

