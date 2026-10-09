from pathlib import Path
from types import SimpleNamespace

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.engineering_substrate.change_integration import MANIFEST_KIND
from jarvis.engineering_substrate.contracts import HardwareAcceptanceVerdict
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
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.monitoring import GICC_MONITOR_EVENT_CONTRACT
from jarvis.goal_intelligence.phase9 import (
    Phase9AcquisitionRequestV2,
    Phase9GoalBridge,
    Phase9GoalContinuationVerifier,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.models import WorkState, WorkType
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

    def find_by_source(
        self, source_session_id: str, source_turn_id: str, process_key: str
    ):
        return None


class CapturingArtifacts:
    def __init__(self) -> None:
        self.records = []

    def latest_artifact(self, change_id: str, kind: str):
        return None

    def find_by_source(
        self, source_session_id: str, source_turn_id: str, process_key: str
    ):
        return None

    def add_artifact(self, change_id: str, *, kind: str, payload: dict[str, object]):
        self.records.append((change_id, kind, payload))
        return SimpleNamespace(
            artifact_id="artifact-gap-link",
            digest="e" * 64,
            payload=payload,
        )


class LinkedFakeAdmitter(FakeAdmitter):
    def admit(self, goal, *, source_revision: str):
        self.goals.append((goal, source_revision))
        return SimpleNamespace(
            change=SimpleNamespace(change_id="change-phase9"),
            acquisition_work_id="work-acquisition",
            goal_artifact_id="artifact-goal",
            admission_artifact_id="artifact-admission",
            disposition=SimpleNamespace(value="engineering_change"),
        )


class LineageWorkStore:
    def __init__(self) -> None:
        self.items = {}
        self.steps = {}

    def get(self, work_id: str):
        return self.items.get(work_id)

    def list_steps(self, work_id: str):
        return tuple(self.steps.get(work_id, ()))


class LineageArtifacts:
    def __init__(self) -> None:
        self.change = SimpleNamespace(change_id="change-phase9")
        self.artifacts = {}
        self.work = LineageWorkStore()

    def latest_artifact(self, change_id: str, kind: str):
        assert change_id == self.change.change_id
        return self.artifacts.get(kind)

    def add_artifact(self, change_id: str, *, kind: str, payload: dict[str, object]):
        assert change_id == self.change.change_id
        artifact = SimpleNamespace(
            artifact_id=f"artifact-{kind}",
            digest=(kind[0] if kind else "a") * 64,
            payload=payload,
        )
        self.artifacts[kind] = artifact
        return artifact

    def find_by_source(
        self, source_session_id: str, source_turn_id: str, process_key: str
    ):
        del source_session_id, source_turn_id, process_key
        return self.change


def _install_current_lineage(
    artifacts: LineageArtifacts,
    *,
    request: Phase9AcquisitionRequestV2,
    goal: OwnerGoalV2,
    gap: CapabilityGapV1,
) -> None:
    candidate = SimpleNamespace(
        artifact_id="artifact-candidate",
        digest="c" * 64,
        payload={
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
            "development_work_id": "work-development",
        },
    )
    admission = SimpleNamespace(
        artifact_id="artifact-admission",
        digest="a" * 64,
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
        },
    )
    activation = SimpleNamespace(
        artifact_id="artifact-activation",
        digest="b" * 64,
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "admission_artifact_id": admission.artifact_id,
            "admission_artifact_digest": admission.digest,
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
            "effective_enabled": True,
            "authority_session_id": "owner-session",
            "source_turn_id": "activation-turn",
        },
    )
    artifacts.artifacts.update(
        {
            "gicc_capability_gap_link": SimpleNamespace(
                artifact_id="artifact-link",
                digest="l" * 64,
                payload={
                    "schema": "gicc_phase9_gap_link.v2",
                    "request_id": request.request_id,
                    "request_digest": request.digest,
                    "motivating_goal_id": goal.goal_id,
                    "gap_id": gap.gap_id,
                    "engineering_change_id": artifacts.change.change_id,
                    "acquisition_work_id": "work-acquisition",
                },
            ),
            "capability_candidate": candidate,
            "capability_package_admission": admission,
            "capability_lifecycle_activation": activation,
            "architecture": SimpleNamespace(
                artifact_id="artifact-architecture",
                digest="r" * 64,
                payload={
                    "owner_acceptance_contract_ids": [
                        PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
                    ]
                },
            ),
            "capability_goal": SimpleNamespace(
                artifact_id="artifact-goal",
                digest="g" * 64,
                payload={"schema": "owner_capability_goal.v1"},
            ),
            MANIFEST_KIND: SimpleNamespace(
                artifact_id="artifact-manifest",
                digest="m" * 64,
                payload={"schema": "substrate_manifest.v1"},
            ),
        }
    )


def _completed_external_step(kind: str, observation: dict[str, object]):
    return SimpleNamespace(
        kind=kind,
        state=SimpleNamespace(value="completed"),
        observation=observation,
    )


def _install_current_external_pass(artifacts: LineageArtifacts) -> None:
    candidate = artifacts.artifacts["capability_candidate"]
    activation = artifacts.artifacts["capability_lifecycle_activation"]
    architecture = artifacts.artifacts["architecture"]
    goal_artifact = artifacts.artifacts["capability_goal"]
    manifest = artifacts.artifacts[MANIFEST_KIND]
    work_id = "work-external"

    binding = SimpleNamespace(
        artifact_id="artifact-external-binding",
        digest="i" * 64,
        payload={
            "schema": "capability_external_acceptance_binding.v1",
            "work_id": work_id,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_artifact_digest": architecture.digest,
            "manifest_artifact_id": manifest.artifact_id,
            "manifest_artifact_digest": manifest.digest,
            "goal_artifact_id": goal_artifact.artifact_id,
            "goal_artifact_digest": goal_artifact.digest,
            "acceptance_contract_id": PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
            "authority_session_id": activation.payload["authority_session_id"],
            "source_turn_id": activation.payload["source_turn_id"],
        },
    )
    artifacts.artifacts[EXTERNAL_ACCEPTANCE_BINDING_KIND] = binding
    artifacts.work.items[work_id] = SimpleNamespace(
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-phase9",
        source_turn_id=activation.artifact_id,
        dependencies=(candidate.payload["development_work_id"],),
        state=WorkState.COMPLETED,
    )
    artifacts.work.steps[work_id] = (
        _completed_external_step("external_acceptance_inspect", {"inspected": True}),
        _completed_external_step("external_acceptance_prepare", {"prepared": True}),
        _completed_external_step("external_acceptance_invoke", {"invoked": True}),
        _completed_external_step(
            "external_acceptance_record",
            {"acceptance_recorded": True, "verdict": "pass"},
        ),
    )
    artifacts.artifacts["capability_external_acceptance"] = SimpleNamespace(
        artifact_id="artifact-external-acceptance",
        digest="x" * 64,
        payload={
            "schema": "capability_external_acceptance.v1",
            "work_id": work_id,
            "binding_artifact_id": binding.artifact_id,
            "binding_artifact_digest": binding.digest,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "verdict": HardwareAcceptanceVerdict.PASS.value,
        },
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


def _graph(
    goal: OwnerGoalV2, *, target_entity_id: str | None = None
) -> CapabilityRequirementGraphV1:
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play",
        target_entity_type="media_player",
        target_entity_id=target_entity_id,
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


def test_monitoring_observer_gap_requires_verified_event_contract(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-monitor-session",
            source_turn_id="owner-monitor-turn",
            exact_owner_request="Tell me when a delivery agent is at the gate.",
            goal_kind=GoalKind.MONITORING,
            desired_outcome="Delivery agent is verified at the gate.",
            created_at="2026-10-01T14:05:00+00:00",
        )
    )
    gap = CapabilityGapV1.create(
        goal_id=goal.goal_id,
        requirement_ids=("req-perception",),
        reusable_capability_family="vision.perceive",
        target_entity_type="camera",
        minimum_required_operations=("verify_scene_condition",),
        motivating_goal_id=goal.goal_id,
    )

    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    phase9_goal = request.to_v1(owner_goal_created_at=goal.created_at)

    assert request.monitor_event_contract_required is True
    assert (
        f"monitor_event_contract:{GICC_MONITOR_EVENT_CONTRACT}"
        in phase9_goal.target_hints
    )
    assert request.canonical_payload()["monitor_event_contract_required"] is True


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


def _identified_tv_goal_and_gap(
    store: GoalStore,
) -> tuple[OwnerGoalV2, CapabilityGapV1]:
    entity = store.put_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Verified owner television",
            provenance_refs=("owner_inventory:test",),
        )
    )
    goal = _goal(store)
    goal = store.update_goal_referenced_entities(
        goal.goal_id,
        (entity.entity_id,),
        expected_revision=goal.goal_revision,
    )
    return goal, _gap(store, goal, _graph(goal, target_entity_id=entity.entity_id))


def test_phase9_bridge_blocks_unidentified_physical_device(tmp_path: Path) -> None:
    from jarvis.goal_intelligence.store import GoalStoreConflict

    store = _store(tmp_path)
    goal = _goal(store)
    gap = _gap(store, goal, _graph(goal))
    admitter = FakeAdmitter()
    bridge = Phase9GoalBridge(
        coordinator=admitter,
        change_store=FakeArtifacts(),
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )
    import pytest

    with pytest.raises(GoalStoreConflict, match="resolved canonical"):
        bridge.admit_gap(gap, goal)
    assert not admitter.goals


def test_phase9_bridge_admits_generic_v1_goal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal, gap = _identified_tv_goal_and_gap(store)
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


def test_phase9_bridge_persists_exact_cross_lifecycle_lineage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal, gap = _identified_tv_goal_and_gap(store)
    admitter = LinkedFakeAdmitter()
    artifacts = CapturingArtifacts()
    bridge = Phase9GoalBridge(
        coordinator=admitter,
        change_store=artifacts,
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    admitted = bridge.admit_gap(gap, goal)

    assert len(artifacts.records) == 2
    by_kind = {
        kind: (change_id, payload) for change_id, kind, payload in artifacts.records
    }

    change_id, payload = by_kind["gicc_capability_gap_link"]
    assert change_id == "change-phase9"
    assert payload["schema"] == "gicc_phase9_gap_link.v2"
    assert payload["motivating_goal_id"] == goal.goal_id
    assert payload["gap_id"] == gap.gap_id
    assert payload["request_id"] == admitted.request.request_id
    assert payload["phase9_goal_id"] == admitted.phase9_goal.goal_id
    assert payload["phase9_goal_digest"] == admitted.phase9_goal.digest
    assert payload["engineering_change_id"] == "change-phase9"
    assert payload["acquisition_work_id"] == "work-acquisition"
    assert payload["goal_artifact_id"] == "artifact-goal"
    assert payload["admission_artifact_id"] == "artifact-admission"
    assert payload["admission_disposition"] == "engineering_change"
    assert payload["bridge_source_session_id"] == f"gicc:{goal.goal_id}"
    assert payload["bridge_source_turn_id"] == f"gap:{gap.gap_id}"

    target_change_id, target = by_kind["gicc_target_context"]
    assert target_change_id == "change-phase9"
    assert target["schema"] == "gicc_target_context.v1"
    assert target["motivating_goal_id"] == goal.goal_id
    assert target["gap_id"] == gap.gap_id
    assert target["target_entity_type"] == gap.target_entity_type
    assert target["target_entity_id"] == gap.target_entity_id
    assert target["canonical_name"] == "Verified owner television"
    assert target["target_hints"] == [
        f"entity_type:{gap.target_entity_type}",
        "entity_name:Verified owner television",
    ]


def test_phase9_completion_requires_exact_current_lineage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = _graph(goal)
    gap = _gap(store, goal, graph)
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    artifacts = LineageArtifacts()
    _install_current_lineage(artifacts, request=request, goal=goal, gap=gap)
    _install_current_external_pass(artifacts)
    bridge = Phase9GoalBridge(
        coordinator=FakeAdmitter(),
        change_store=artifacts,
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    assert bridge.completion_verified(gap=gap, goal=goal) is True

    artifacts.artifacts["capability_lifecycle_activation"].payload[
        "candidate_artifact_digest"
    ] = "0" * 64
    assert bridge.completion_verified(gap=gap, goal=goal) is False


def test_phase9_completion_requires_real_external_acceptance_when_declared(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = _graph(goal)
    gap = _gap(store, goal, graph)
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    artifacts = LineageArtifacts()
    _install_current_lineage(artifacts, request=request, goal=goal, gap=gap)
    artifacts.artifacts["architecture"].payload["owner_acceptance_contract_ids"] = [
        PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
    ]
    bridge = Phase9GoalBridge(
        coordinator=FakeAdmitter(),
        change_store=artifacts,
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    assert bridge.completion_verified(gap=gap, goal=goal) is False

    _install_current_external_pass(artifacts)
    assert bridge.completion_verified(gap=gap, goal=goal) is True

    artifacts.artifacts["capability_external_acceptance"].payload["verdict"] = (
        HardwareAcceptanceVerdict.FAIL.value
    )
    assert bridge.completion_verified(gap=gap, goal=goal) is False


def test_phase9_completion_accepts_existing_capability_reuse_without_change(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store)
    graph = _graph(goal)
    gap = _gap(store, goal, graph)
    bridge = Phase9GoalBridge(
        coordinator=FakeAdmitter(),
        change_store=FakeArtifacts(),
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    # The caller invokes completion_verified only after refreshed canonical
    # capability truth says the semantic gap is gone. With no EngineeringChange,
    # Phase 9 has reused an already-existing capability and there is no new package
    # generation that needs provenance binding.
    assert bridge.completion_verified(gap=gap, goal=goal) is True


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
