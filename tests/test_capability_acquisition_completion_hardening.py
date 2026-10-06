from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.runtime_context import (
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
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
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.phase9 import (
    Phase9AcquisitionRequestV2,
    Phase9GoalBridge,
    Phase9GoalContinuationVerifier,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class _Backend:
    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        return work_id


def _context(*, ready: bool) -> AcquisitionContextV1:
    if not ready:
        return AcquisitionContextV1(
            catalog=CapabilityCatalog(
                sources=(
                    DiscoverySnapshot(
                        source_id="hardening",
                        state=DiscoveryState.AVAILABLE,
                    ),
                ),
                capabilities=(),
            ),
            inventory=(),
        )

    descriptor = CapabilityDescriptor.create(
        capability_id="media_player_control",
        source_id="hardening",
        kind=CapabilityKind.NATIVE_API,
        name="Acquired media-player control",
        description="Control the resolved media player.",
        operations=("play_media",),
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
                    source_id="hardening",
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


def test_exact_completion_lineage_fences_and_resumes_original_goal(
    tmp_path: Path,
) -> None:
    """Partial or stale Phase-9 evidence can never resume the owner continuation."""

    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    coordinator = ChangeCoordinator(changes, _Backend())
    phase9 = Phase9GoalBridge(
        coordinator=CapabilityAcquisitionCoordinator(
            changes=coordinator,
            context_provider=StaticAcquisitionContextProvider(_context(ready=False)),
        ),
        change_store=changes,
        goal_store=goals,
        source_revision_provider=lambda: "a" * 40,
    )

    target = goals.put_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
            provenance_refs=("hardening:target",),
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="completion-session",
            source_turn_id="completion-turn",
            exact_owner_request="Play The Martian on my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="The Martian is playing on the living-room TV.",
            completion_predicates=("playback_started",),
            referenced_entity_ids=(target.entity_id,),
            state=GoalState.WAITING_CAPABILITY,
        )
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play_media",
        target_entity_id=target.entity_id,
        target_entity_type="media_player",
        expected_postconditions=("playback_started",),
        reason="Play selected media.",
    )
    graph = goals.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=(requirement,),
        )
    )
    gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=graph.requirement_ids,
            reusable_capability_family="media_player.control",
            target_entity_type="media_player",
            target_entity_id=target.entity_id,
            minimum_required_operations=("play_media",),
            missing_reason_codes=("no_effective_capability_match",),
            motivating_goal_id=goal.goal_id,
        )
    )
    node = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:hardening-acquisition",
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire reusable media-player control.",
        gap_id=gap.gap_id,
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
        )
    )

    admitted = phase9.admit_gap(gap, goal)
    assert admitted.admission.change is not None
    assert admitted.admission.acquisition_work_id is not None
    change_id = admitted.admission.change.change_id

    continuation = goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            work_ids=(admitted.admission.acquisition_work_id,),
            goal_revision=goal.goal_revision,
        )
    )
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)

    assert phase9.completion_verified(gap=gap, goal=goal) is False
    assert (
        verify_capability_acquisition_completion(
            changes,
            change_id=change_id,
            motivating_goal_id=goal.goal_id,
            gap_id=gap.gap_id,
            request_id=request.request_id,
            request_digest=request.digest,
        )
        is None
    )

    package_digest = "b" * 64
    candidate = changes.add_artifact(
        change_id,
        kind="capability_candidate",
        payload={
            "schema": "capability_candidate.v1",
            "candidate_id": "candidate-hardening",
            "digest": "c" * 64,
            "development_work_id": "work-development-hardening",
            "capability_id": "media_player_control",
            "package_id": "media.player.control",
            "package_version": "1.0.0",
            "package_digest": package_digest,
        },
    )
    architecture = changes.add_artifact(
        change_id,
        kind="architecture",
        payload={
            "schema": "capability_acquisition_architecture.v1",
            "owner_acceptance_contract_ids": [PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT],
        },
    )
    admission = changes.add_artifact(
        change_id,
        kind="capability_package_admission",
        payload={
            "schema": "capability_acquisition_release_admission.v1",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "package_id": "media.player.control",
            "package_version": "1.0.0",
            "package_digest": package_digest,
            "capability_id": "media_player_control",
            "auto_activated": False,
        },
    )
    activation = changes.add_artifact(
        change_id,
        kind="capability_lifecycle_activation",
        payload={
            "schema": "capability_acquisition_activation.v1",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "admission_artifact_id": admission.artifact_id,
            "admission_artifact_digest": admission.digest,
            "capability_id": "media_player_control",
            "package_id": "media.player.control",
            "package_version": "1.0.0",
            "package_digest": package_digest,
            "effective_enabled": True,
            "authority_session_id": "completion-session",
            "source_turn_id": "activation-turn",
        },
    )

    assert architecture.artifact_id
    assert phase9.completion_verified(gap=gap, goal=goal) is False

    # A PASS-shaped result alone is not completion. The canonical verifier must
    # require the exact post-activation WorkItem/binding created by the runtime.
    changes.add_artifact(
        change_id,
        kind="capability_external_acceptance",
        payload={
            "schema": "capability_external_acceptance.v1",
            "work_id": "work-external-forged",
            "binding_artifact_id": "artifact-binding-forged",
            "binding_artifact_digest": "1" * 64,
            "verdict": HardwareAcceptanceVerdict.PASS.value,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
        },
    )
    assert (
        verify_capability_acquisition_completion(
            changes,
            change_id=change_id,
            motivating_goal_id=goal.goal_id,
            gap_id=gap.gap_id,
            request_id=request.request_id,
            request_digest=request.digest,
        )
        is None
    )
    assert phase9.completion_verified(gap=gap, goal=goal) is False
    assert goals.get_continuation(continuation.continuation_id).state is (
        ContinuationState.BLOCKED
    )

    manifest = changes.add_artifact(
        change_id,
        kind="substrate_manifest",
        payload={
            "schema": "engineering_manifest.v1",
            "manifest_id": "manifest-hardening",
            "manifest_digest": "d" * 64,
        },
    )
    goal_artifact = changes.latest_artifact(change_id, "capability_goal")
    assert goal_artifact is not None

    acceptance_work = work.create(
        WorkItem(
            request="Validate the exact activated acquired capability.",
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id=f"phase9-external:{change_id}",
            source_turn_id=activation.artifact_id,
            state=WorkState.COMPLETED,
            dependencies=("work-development-hardening",),
        )
    )
    for kind, observation in (
        ("external_acceptance_inspect", {"inspected": True}),
        ("external_acceptance_prepare", {"prepared": True}),
        ("external_acceptance_invoke", {"invoked": True}),
        (
            "external_acceptance_record",
            {"acceptance_recorded": True, "verdict": "pass"},
        ),
    ):
        step = WorkStep(
            work_id=acceptance_work.work_id,
            kind=kind,
            summary=kind,
        )
        work.add_step(step)
        work.save_step(step.start().complete(observation))

    binding = changes.add_artifact(
        change_id,
        kind="capability_external_acceptance_binding",
        payload={
            "schema": "capability_external_acceptance_binding.v1",
            "work_id": acceptance_work.work_id,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_artifact_digest": architecture.digest,
            "manifest_artifact_id": manifest.artifact_id,
            "manifest_artifact_digest": manifest.digest,
            "goal_artifact_id": goal_artifact.artifact_id,
            "goal_artifact_digest": goal_artifact.digest,
            "capability_id": "media_player_control",
            "package_id": "media.player.control",
            "package_version": "1.0.0",
            "requested_operations": ["play_media"],
            "acceptance_contract_id": PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
            "device_identity": "Living Room TV",
            "target_hints": ["entity_type:media_player"],
            "authority_session_id": "completion-session",
            "source_turn_id": "activation-turn",
        },
    )

    # Even with a real WorkItem/binding, stale result-to-binding evidence is rejected.
    changes.add_artifact(
        change_id,
        kind="capability_external_acceptance",
        payload={
            "schema": "capability_external_acceptance.v1",
            "work_id": acceptance_work.work_id,
            "binding_artifact_id": binding.artifact_id,
            "binding_artifact_digest": "0" * 64,
            "verdict": HardwareAcceptanceVerdict.PASS.value,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
        },
    )
    with pytest.raises(
        CapabilityAcquisitionLineageError,
        match="current acceptance mission",
    ):
        verify_capability_acquisition_completion(
            changes,
            change_id=change_id,
            motivating_goal_id=goal.goal_id,
            gap_id=gap.gap_id,
            request_id=request.request_id,
            request_digest=request.digest,
        )

    external = changes.add_artifact(
        change_id,
        kind="capability_external_acceptance",
        payload={
            "schema": "capability_external_acceptance.v1",
            "work_id": acceptance_work.work_id,
            "binding_artifact_id": binding.artifact_id,
            "binding_artifact_digest": binding.digest,
            "verdict": HardwareAcceptanceVerdict.PASS.value,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
        },
    )
    lineage = verify_capability_acquisition_completion(
        changes,
        change_id=change_id,
        motivating_goal_id=goal.goal_id,
        gap_id=gap.gap_id,
        request_id=request.request_id,
        request_digest=request.digest,
    )
    assert lineage is not None
    assert lineage.external_acceptance_binding_artifact_id == binding.artifact_id
    assert lineage.external_acceptance_work_id == acceptance_work.work_id
    assert lineage.external_acceptance_artifact_id == external.artifact_id
    assert phase9.completion_verified(gap=gap, goal=goal) is True

    refreshed = {"count": 0}

    def refresh() -> None:
        refreshed["count"] += 1

    recheck = Phase9GoalContinuationVerifier(
        goal_store=goals,
        graph_resolver=CapabilityGraphResolver(store=goals),
        context_provider=StaticAcquisitionContextProvider(_context(ready=True)),
        refresh_capability_catalog=refresh,
    ).recheck(
        request=request,
        graph=graph,
        continuation_id=continuation.continuation_id,
    )

    assert refreshed["count"] == 1
    assert recheck.gap_satisfied is True
    assert recheck.continuation is not None
    assert recheck.continuation.state is ContinuationState.RESUMED
    assert goals.get_gap(gap.gap_id).state.value == "satisfied"
