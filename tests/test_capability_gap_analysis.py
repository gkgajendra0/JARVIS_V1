from pathlib import Path

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.models import DesiredActivationState
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityInventoryEntry,
    CapabilityManagementMode,
    EffectiveCapabilityState,
)
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.models import (
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    GoalKind,
    OwnerGoalV2,
)
from jarvis.goal_intelligence.monitoring import GICC_MONITOR_EVENT_CONTRACT
from jarvis.goal_intelligence.store import GoalStore
from jarvis.self_model.health import HealthState
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="session-gap",
        source_turn_id="turn-gap",
        exact_owner_request="I want to watch Transporter on my TV.",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="Watch Transporter on my TV.",
        created_at="2026-10-01T13:10:00+00:00",
    )


def _context(
    descriptors: tuple[CapabilityDescriptor, ...],
    *,
    managed_keys: tuple[str, ...] = (),
    snapshot: CapabilityEffectiveSnapshot | None = None,
) -> AcquisitionContextV1:
    managed = set(managed_keys)
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(
            sources=(
                DiscoverySnapshot(
                    source_id="test",
                    state=DiscoveryState.AVAILABLE,
                    capabilities=descriptors,
                ),
            ),
            capabilities=descriptors,
        ),
        inventory=tuple(
            CapabilityInventoryEntry(
                capability_id=item.capability_id,
                capability_key=item.key,
                management_mode=(
                    CapabilityManagementMode.PACKAGE_MANAGED
                    if item.key in managed
                    else CapabilityManagementMode.CORE_PINNED
                ),
            )
            for item in descriptors
        ),
        effective_snapshot=snapshot,
    )


def test_existing_legacy_hands_operation_satisfies_pc_requirement() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="computer.application",
        operation="open_app",
        target_entity_type="computer",
        expected_postconditions=("application_open",),
        reason="Open an application.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    descriptor = CapabilityDescriptor.create(
        capability_id="lifecycle",
        source_id="app",
        kind=CapabilityKind.NATIVE_API,
        name="Windows application lifecycle",
        description="Open and close applications.",
        operations=("open_app", "close_app"),
        execution_enabled=True,
    )

    result = CapabilityGraphResolver().analyze(
        graph,
        _context((descriptor,)),
    )

    assert result.satisfied is True
    assert result.gaps == ()
    assert result.matches[0].capability_key == "app:lifecycle"


def test_tv_request_emits_reusable_gap_without_movie_identity() -> None:
    goal = _goal()
    requirements = (
        CapabilityRequirementV1.create(
            goal_id=goal.goal_id,
            semantic_capability="media_player.control",
            operation="launch_app",
            target_entity_type="media_player",
            expected_postconditions=("app_active",),
            reason="Open selected service.",
        ),
        CapabilityRequirementV1.create(
            goal_id=goal.goal_id,
            semantic_capability="media_player.control",
            operation="play",
            target_entity_type="media_player",
            expected_postconditions=("playback_started",),
            reason="Start playback.",
        ),
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=requirements,
    )

    result = CapabilityGraphResolver().analyze(graph, _context(()))

    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.reusable_capability_family == "media_player.control"
    assert gap.minimum_required_operations == ("launch_app", "play")
    assert "transporter" not in str(gap.canonical_payload()).casefold()


def test_gate_requirements_group_by_reusable_family() -> None:
    goal = _goal()
    requirements = tuple(
        CapabilityRequirementV1.create(
            goal_id=goal.goal_id,
            semantic_capability=family,
            operation=operation,
            target_entity_type=target,
            expected_postconditions=(f"{operation}_available",),
            reason="Gate monitoring requirement.",
        )
        for family, operation, target in (
            ("camera.observe", "read_live_stream", "camera"),
            ("vision.perceive", "person_and_package", "generic_external_resource"),
            ("monitor.evaluate", "evaluate", "generic_external_resource"),
            ("notification.owner", "send", "generic_external_resource"),
        )
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=requirements,
    )

    result = CapabilityGraphResolver().analyze(graph, _context(()))

    assert {gap.reusable_capability_family for gap in result.gaps} == {
        "camera.observe",
        "monitor.evaluate",
        "notification.owner",
        "vision.perceive",
    }


def test_semantic_metadata_prevents_same_verb_from_wrong_family() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="notification.owner",
        operation="send",
        expected_postconditions=("notification_sent",),
        reason="Notify owner.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    wrong = CapabilityDescriptor.create(
        capability_id="email",
        source_id="connector",
        kind=CapabilityKind.SEMANTIC_CONNECTOR,
        name="Email sender",
        description="Send email.",
        operations=("send",),
        metadata={"semantic_capability_family": "email.send"},
        execution_enabled=True,
    )

    result = CapabilityGraphResolver().analyze(graph, _context((wrong,)))

    assert result.satisfied is False
    assert result.gaps[0].reusable_capability_family == "notification.owner"


def test_package_managed_capability_requires_explicit_semantic_identity() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play",
        target_entity_type="media_player",
        expected_postconditions=("playback_started",),
        reason="Play media on the requested media player.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    descriptor = CapabilityDescriptor.create(
        capability_id="control",
        source_id="package",
        kind=CapabilityKind.NATIVE_API,
        name="Generic external control",
        description="A package-managed capability exposing a colliding play verb.",
        operations=("play",),
        execution_enabled=True,
    )
    state = EffectiveCapabilityState(
        capability_id=descriptor.capability_id,
        capability_key=descriptor.key,
        component_id="capability.package:control",
        management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        registry_generation=1,
        applied_generation=1,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id="pkg-control",
        selected_package_version="1.0.0",
        selected_package_digest="c" * 64,
        package_disposition=None,
        compatibility_verdict=None,
        compatibility_digest=None,
        health_state=HealthState.HEALTHY,
        transition_fenced=False,
        effective_enabled=True,
        reason_codes=(),
    )
    snapshot = CapabilityEffectiveSnapshot(
        release_sha="d" * 40,
        states=(state,),
        reconciled_at_epoch=1.0,
        trigger="test",
    )

    result = CapabilityGraphResolver().analyze(
        graph,
        _context(
            (descriptor,),
            managed_keys=(descriptor.key,),
            snapshot=snapshot,
        ),
    )

    assert result.satisfied is False
    assert result.gaps[0].reusable_capability_family == "media_player.control"


def test_package_managed_capability_must_be_effectively_enabled() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="camera.observe",
        operation="read_live_stream",
        target_entity_type="camera",
        expected_postconditions=("stream_readable",),
        reason="Read camera stream.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    descriptor = CapabilityDescriptor.create(
        capability_id="camera",
        source_id="package",
        kind=CapabilityKind.NATIVE_API,
        name="Camera access",
        description="Read camera stream.",
        operations=("read_live_stream",),
        metadata={
            "semantic_capability_family": "camera.observe",
            "target_entity_types": ["camera"],
        },
        execution_enabled=True,
    )
    state = EffectiveCapabilityState(
        capability_id=descriptor.capability_id,
        capability_key=descriptor.key,
        component_id="capability.package:camera",
        management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        registry_generation=2,
        applied_generation=1,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id="pkg-camera",
        selected_package_version="1.0.0",
        selected_package_digest="a" * 64,
        package_disposition=None,
        compatibility_verdict=None,
        compatibility_digest=None,
        health_state=HealthState.HEALTHY,
        transition_fenced=False,
        effective_enabled=True,
        reason_codes=(),
    )
    snapshot = CapabilityEffectiveSnapshot(
        release_sha="b" * 40,
        states=(state,),
        reconciled_at_epoch=1.0,
        trigger="test",
    )

    result = CapabilityGraphResolver().analyze(
        graph,
        _context(
            (descriptor,),
            managed_keys=(descriptor.key,),
            snapshot=snapshot,
        ),
    )

    assert result.satisfied is False
    assert result.gaps[0].reusable_capability_family == "camera.observe"


def test_monitoring_goal_rejects_pull_only_observer_capability() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="vision.perceive",
        operation="verify_scene_condition",
        target_entity_type="camera",
        observation_requirements=("delivery_agent_verified",),
        reason="Verify the semantic scene condition.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    descriptor = CapabilityDescriptor.create(
        capability_id="scene",
        source_id="vision",
        kind=CapabilityKind.LOCAL_READ,
        name="Scene verifier",
        description="Verify a scene condition on demand.",
        operations=("verify_scene_condition",),
        metadata={
            "semantic_capability_family": "vision.perceive",
            "target_entity_types": ["camera"],
            "observation_operations": ["verify_scene_condition"],
        },
        execution_enabled=True,
    )

    result = CapabilityGraphResolver().analyze(
        graph,
        _context((descriptor,)),
        monitoring_goal=True,
    )

    assert result.satisfied is False
    assert result.gaps[0].reusable_capability_family == "vision.perceive"


def test_monitoring_goal_accepts_verified_event_observer_capability() -> None:
    goal = _goal()
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="vision.perceive",
        operation="verify_scene_condition",
        target_entity_type="camera",
        observation_requirements=("delivery_agent_verified",),
        reason="Verify the semantic scene condition.",
    )
    graph = CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )
    descriptor = CapabilityDescriptor.create(
        capability_id="scene",
        source_id="vision",
        kind=CapabilityKind.LOCAL_READ,
        name="Event scene verifier",
        description="Publish verified scene-condition observations.",
        operations=("verify_scene_condition",),
        metadata={
            "semantic_capability_family": "vision.perceive",
            "target_entity_types": ["camera"],
            "observation_operations": ["verify_scene_condition"],
            "monitor_event_contract": GICC_MONITOR_EVENT_CONTRACT,
        },
        execution_enabled=True,
    )

    result = CapabilityGraphResolver().analyze(
        graph,
        _context((descriptor,)),
        monitoring_goal=True,
    )

    assert result.satisfied is True
    assert result.matches[0].capability_key == descriptor.key


def test_gap_persistence_is_idempotent_for_same_semantic_gap(tmp_path: Path) -> None:
    work = SQLiteWorkStore(
        tmp_path / "work.sqlite3",
        payload_codec=ProtectedWorkPayloadCodec(b"c" * 32),
    )
    store = GoalStore(work)
    goal = store.create_goal(_goal())
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="camera.observe",
        operation="read_live_stream",
        target_entity_type="camera",
        expected_postconditions=("stream_readable",),
        reason="Read stream.",
    )
    graph = store.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=(requirement,),
        )
    )
    resolver = CapabilityGraphResolver(store=store)

    first = resolver.analyze(graph, _context(()), persist_gaps=True)
    second = resolver.analyze(graph, _context(()), persist_gaps=True)

    assert first.gaps[0] == second.gaps[0]
