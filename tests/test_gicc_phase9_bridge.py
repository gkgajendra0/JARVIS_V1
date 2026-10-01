from pathlib import Path
from types import SimpleNamespace

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.models import (
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    ContinuationBlockerType,
    ContinuationState,
    GoalContinuationV1,
    GoalKind,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.phase9 import (
    Phase9AcquisitionRequestV2,
    Phase9GoalBridge,
    Phase9GoalContinuationVerifier,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeAdmitter:
    def __init__(self) -> None:
        self.goals = []

    def admit(self, goal, *, source_revision: str):
        self.goals.append((goal, source_revision))
        return SimpleNamespace(change=None)


class FakeArtifacts:
    def latest_artifact(self, change_id: str, kind: str):
        return None

    def add_artifact(self, change_id: str, *, kind: str, payload: dict[str, object]):
        return SimpleNamespace(
            artifact_id="artifact-1",
            digest="d" * 64,
            payload=payload,
        )


class MutableContext:
    def __init__(self, context: AcquisitionContextV1) -> None:
        self.context = context

    def current(self) -> AcquisitionContextV1:
        return self.context


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"p" * 32),
        )
    )


def _goal(store: GoalStore) -> OwnerGoalV2:
    return store.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="owner-turn",
            exact_owner_request="I want to watch Transporter on my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Watch Transporter on the TV.",
            created_at="2026-10-01T14:00:00+00:00",
        )
    )


def _graph(goal: OwnerGoalV2) -> CapabilityRequirementGraphV1:
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play",
        target_entity_type="media_player",
        expected_postconditions=("playback_started",),
        reason="Start media playback.",
    )
    return CapabilityRequirementGraphV1.create(
        goal_id=goal.goal_id,
        requirements=(requirement,),
    )


def _empty_context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(
            sources=(
                DiscoverySnapshot(
                    source_id="test",
                    state=DiscoveryState.AVAILABLE,
                ),
            ),
            capabilities=(),
        ),
        inventory=(),
    )


def _ready_context() -> AcquisitionContextV1:
    descriptor = CapabilityDescriptor.create(
        capability_id="control",
        source_id="media-player",
        kind=CapabilityKind.NATIVE_API,
        name="Generic media player control",
        description="Control a media-player resource.",
        operations=("play",),
        metadata={
            "semantic_capability_family": "media_player.control",
            "target_entity_types": ["media_player"],
        },
        execution_enabled=True,
    )
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(
            sources=(
                DiscoverySnapshot(
                    source_id="test",
                    state=DiscoveryState.AVAILABLE,
                    capabilities=(descriptor,),
                ),
            ),
            capabilities=(descriptor,),
        ),
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.CORE_PINNED,
            ),
        ),
    )


def _gap(
    store: GoalStore,
    goal: OwnerGoalV2,
    graph: CapabilityRequirementGraphV1,
) -> CapabilityGapV1:
    analysis = CapabilityGraphResolver(store=store).analyze(
        graph,
        _empty_context(),
        persist_gaps=True,
    )
    return analysis.gaps[0]


def test_phase9_v2_request_excludes_task_only_movie_parameter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = _graph(goal)
    gap = _gap(store, goal, graph)

    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    v1 = request.to_v1(owner_goal_created_at=goal.created_at)

    assert request.motivating_goal_id == goal.goal_id
    assert request.gap_id == gap.gap_id
    assert v1.requested_capability == "media_player.control"
    assert v1.required_operations == ("play",)
    assert "transporter" not in v1.request.casefold()
    assert "transporter" not in " ".join(v1.target_hints).casefold()
    assert v1.source_session_id == f"gicc:{goal.goal_id}"
    assert v1.source_turn_id == f"gap:{gap.gap_id}"


def test_multiple_gaps_get_unique_phase9_bridge_sources(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    first = CapabilityGapV1.create(
        goal_id=goal.goal_id,
        requirement_ids=("req-1",),
        reusable_capability_family="camera.observe",
        target_entity_type="camera",
        minimum_required_operations=("read_live_stream",),
        motivating_goal_id=goal.goal_id,
    )
    second = CapabilityGapV1.create(
        goal_id=goal.goal_id,
        requirement_ids=("req-2",),
        reusable_capability_family="notification.owner",
        target_entity_type="generic_external_resource",
        minimum_required_operations=("send",),
        motivating_goal_id=goal.goal_id,
    )

    first_request = Phase9AcquisitionRequestV2.create(gap=first, goal=goal)
    second_request = Phase9AcquisitionRequestV2.create(gap=second, goal=goal)

    assert (
        first_request.bridge_source_session_id
        == second_request.bridge_source_session_id
    )
    assert first_request.bridge_source_turn_id != second_request.bridge_source_turn_id


def test_phase9_bridge_admits_generic_v1_goal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = _graph(goal)
    gap = _gap(store, goal, graph)
    admitter = FakeAdmitter()
    bridge = Phase9GoalBridge(
        coordinator=admitter,
        change_store=FakeArtifacts(),
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    admitted = bridge.admit_gap(gap, goal)

    assert admitted.request.gap_id == gap.gap_id
    assert len(admitter.goals) == 1
    phase9_goal, revision = admitter.goals[0]
    assert revision == "a" * 40
    assert phase9_goal.requested_capability == "media_player.control"
    assert "transporter" not in phase9_goal.request.casefold()


def test_completion_rechecks_actual_capability_truth_before_resume(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = store.put_requirement_graph(_graph(goal))
    gap = _gap(store, goal, graph)
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire reusable media-player control.",
        gap_id=gap.gap_id,
    )
    plan = store.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
            created_at="2026-10-01T14:01:00+00:00",
        )
    )
    continuation = store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T14:02:00+00:00",
        )
    )
    context = MutableContext(_empty_context())

    verifier = Phase9GoalContinuationVerifier(
        goal_store=store,
        graph_resolver=CapabilityGraphResolver(),
        context_provider=context,
        refresh_capability_catalog=lambda: None,
    )
    not_ready = verifier.recheck(
        request=request,
        graph=graph,
        continuation_id=continuation.continuation_id,
    )

    assert not_ready.gap_satisfied is False
    assert not_ready.continuation is None
    current_continuation = store.get_continuation(continuation.continuation_id)
    assert current_continuation is not None
    assert current_continuation.state is ContinuationState.BLOCKED

    def refresh() -> None:
        context.context = _ready_context()

    verifier = Phase9GoalContinuationVerifier(
        goal_store=store,
        graph_resolver=CapabilityGraphResolver(),
        context_provider=context,
        refresh_capability_catalog=refresh,
    )
    ready = verifier.recheck(
        request=request,
        graph=graph,
        continuation_id=continuation.continuation_id,
    )

    assert ready.gap_satisfied is True
    assert ready.continuation is not None
    assert ready.continuation.state is ContinuationState.RESUMED
    persisted_gap = store.get_gap(gap.gap_id)
    assert persisted_gap is not None
    assert persisted_gap.state.value == "satisfied"
