from __future__ import annotations

from dataclasses import dataclass

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
)
from jarvis.capability_acquisition.admission import (
    CapabilityAcquisitionAdmissionDisposition,
    CapabilityAcquisitionCoordinator,
)
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionSourceCompletionHandler,
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.artifacts import (
    candidate_payload,
    evaluation_payload,
    goal_payload,
    plan_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.runtime_context import (
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.workflow import acquisition_completion_guard
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.work.models import WorkPriority, WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore

REVISION = "a" * 40


@dataclass
class Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def _goal(*operations: str) -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Get a TV control capability",
        requested_capability="TV control",
        required_operations=operations or ("power",),
        target_hints=("living-room",),
        source_session_id="owner-session",
        source_turn_id="owner-turn",
        now_epoch=100.0,
    )


def _empty_context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _existing_context() -> AcquisitionContextV1:
    descriptor = CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="local",
        kind=CapabilityKind.NATIVE_API,
        name="TV control",
        description="Existing TV control",
        operations=("power", "volume"),
        execution_enabled=True,
    )
    catalog = CapabilityCatalog(sources=(), capabilities=(descriptor,))
    return AcquisitionContextV1(
        catalog=catalog,
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.CORE_PINNED,
            ),
        ),
    )


def _changes(tmp_path, *, handler: bool = False):
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = Backend([])
    coordinator = ChangeCoordinator(
        store,
        backend,
        source_completion_handlers=(
            (CapabilityAcquisitionSourceCompletionHandler(store),) if handler else ()
        ),
    )
    return work, store, backend, coordinator


def test_admission_short_circuits_existing_ready_capability(tmp_path) -> None:
    work, _, backend, changes = _changes(tmp_path)
    coordinator = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_existing_context()),
    )

    admission = coordinator.admit(_goal("power"), source_revision=REVISION)

    assert (
        admission.disposition
        is CapabilityAcquisitionAdmissionDisposition.EXISTING_READY
    )
    assert admission.change is None
    assert admission.acquisition_work_id is None
    assert backend.submitted == []
    assert work.list(limit=10) == ()


def test_admission_creates_one_durable_acquisition_workitem_when_build_is_needed(
    tmp_path,
) -> None:
    _, store, backend, changes = _changes(tmp_path)
    coordinator = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    )

    first = coordinator.admit(_goal("power"), source_revision=REVISION)
    second = coordinator.admit(_goal("power"), source_revision=REVISION)

    assert (
        first.disposition
        is CapabilityAcquisitionAdmissionDisposition.ENGINEERING_CHANGE
    )
    assert first.change is not None
    assert second.change is not None
    assert first.change.change_id == second.change.change_id
    stages = store.list_stages(first.change.change_id)
    assert len(stages) == 1
    assert stages[0].stage_key == "acquisition"
    assert first.acquisition_work_id == stages[0].work_id
    assert backend.submitted.count(stages[0].work_id) >= 1
    goal_artifact = store.latest_artifact(first.change.change_id, "capability_goal")
    admission_artifact = store.latest_artifact(
        first.change.change_id,
        "capability_acquisition_admission",
    )
    assert goal_artifact is not None
    assert admission_artifact is not None
    assert admission_artifact.payload["source_revision"] == REVISION


def test_phase9_completion_guard_requires_finalize_after_latest_evidence() -> None:
    goal_step = (
        WorkStep(
            work_id="w",
            kind="acq_inspect_goal",
            summary="inspect",
        )
        .start()
        .complete({"goal": {"goal_id": "g"}})
    )
    resolve_step = (
        WorkStep(
            work_id="w",
            kind="acq_resolve",
            summary="resolve",
        )
        .start()
        .complete({"resolved": True})
    )
    finalize_step = (
        WorkStep(
            work_id="w",
            kind="acq_finalize",
            summary="finalize",
        )
        .start()
        .complete({"finalized": True})
    )

    assert acquisition_completion_guard((goal_step, resolve_step, finalize_step)) == (
        True,
        None,
    )

    later_research = (
        WorkStep(
            work_id="w",
            kind="research_web",
            summary="new evidence",
        )
        .start()
        .complete({"ok": True})
    )
    allowed, reason = acquisition_completion_guard(
        (goal_step, resolve_step, finalize_step, later_research)
    )
    assert allowed is False
    assert reason is not None and "re-finalize" in reason


def test_completed_acquisition_derives_digest_bound_architecture(tmp_path) -> None:
    work, store, _, changes = _changes(tmp_path, handler=True)
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(_goal("power"), source_revision=REVISION)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None

    goal_artifact = store.latest_artifact(admission.change.change_id, "capability_goal")
    assert goal_artifact is not None
    goal = _goal("power")
    assert goal_artifact.payload == goal_payload(goal)

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((CustomBuildCapabilitySourceAdapter(),))
    )
    resolution = resolver.resolve(goal, _empty_context())
    candidate = resolution.selected_candidate
    assert candidate is not None
    evaluation = resolution.evaluation(candidate.candidate_id)
    assert isinstance(evaluation, AcquisitionCandidateEvaluationV1)

    resolution_artifact = store.add_artifact(
        admission.change.change_id,
        kind="acquisition_resolution",
        payload=resolution_payload(
            candidates=resolution.candidates,
            evaluations=resolution.evaluations,
            selected_candidate_id=resolution.selected_candidate_id,
        ),
    )
    plan = CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id="tv.control",
        proposed_package_id="tv.control.custom",
        proposed_package_version="1.0.0",
        rollback_summary="Disable the package and revert the candidate release.",
        changed_paths=("src/jarvis/tv_control.py",),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("tv-control-contract-v1",),
        development_test_targets=("tests/test_tv_control.py",),
        evidence_refs=("owner-goal",),
    )
    plan_artifact = store.add_artifact(
        admission.change.change_id,
        kind="acquisition_plan",
        payload={
            **plan_payload(plan),
            "resolution_artifact_id": resolution_artifact.artifact_id,
            "resolution_artifact_digest": resolution_artifact.digest,
            "selected_candidate": candidate_payload(candidate),
            "selected_evaluation": evaluation_payload(evaluation),
        },
    )

    acquisition_work = work.require(admission.acquisition_work_id)
    step = WorkStep(
        work_id=acquisition_work.work_id,
        kind="acq_finalize",
        summary="finalized",
    )
    work.add_step(step)
    work.save_step(
        step.start().complete(
            {
                "finalized": True,
                "plan_id": plan.plan_id,
                "plan_digest": plan.digest,
                "plan_artifact_id": plan_artifact.artifact_id,
                "plan_artifact_digest": plan_artifact.digest,
            }
        )
    )
    running = work.save(
        acquisition_work.transition(WorkState.RUNNING),
        expected_version=acquisition_work.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED, result={"summary": "done"}),
        expected_version=running.version,
    )

    reconciled = changes.reconcile_for_work(acquisition_work.work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.ARCHITECTURE_READY
    architecture = ensure_capability_acquisition_architecture_current(
        store,
        admission.change.change_id,
    )
    assert architecture.payload["goal_digest"] == goal.digest
    assert architecture.payload["plan_digest"] == plan.digest
    assert architecture.payload["selected_candidate_digest"] == candidate.digest
    assert architecture.payload["source_revision"] == REVISION
    assert architecture.payload["allowed_paths"] == ["src/jarvis/tv_control.py"]
    assert architecture.payload["verification_contract_ids"] == [
        "tv-control-contract-v1"
    ]
    assert architecture.payload["verification_targets"] == ["tests/test_tv_control.py"]
    assert architecture.payload["build_permitted"] is True
