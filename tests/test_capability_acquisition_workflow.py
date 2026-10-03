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
from jarvis.engineering_change.gates import GateKind, GateService
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


def _persist_plan(
    store: ChangeStore,
    *,
    change_id: str,
    goal: OwnerCapabilityGoalV1,
    package_version: str,
    changed_path: str,
):
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((CustomBuildCapabilitySourceAdapter(),))
    )
    resolution = resolver.resolve(goal, _empty_context())
    candidate = resolution.selected_candidate
    assert candidate is not None
    evaluation = resolution.evaluation(candidate.candidate_id)
    assert isinstance(evaluation, AcquisitionCandidateEvaluationV1)

    resolution_artifact = store.latest_artifact(
        change_id,
        "acquisition_resolution",
    )
    if resolution_artifact is None:
        resolution_artifact = store.add_artifact(
            change_id,
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
        proposed_package_version=package_version,
        rollback_summary="Disable the package and revert the candidate release.",
        changed_paths=(changed_path,),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("tv-control-contract-v1",),
        development_test_targets=("tests/test_tv_control.py",),
        evidence_refs=("owner-goal",),
    )
    plan_artifact = store.add_artifact(
        change_id,
        kind="acquisition_plan",
        payload={
            **plan_payload(plan),
            "resolution_artifact_id": resolution_artifact.artifact_id,
            "resolution_artifact_digest": resolution_artifact.digest,
            "selected_candidate": candidate_payload(candidate),
            "selected_evaluation": evaluation_payload(evaluation),
        },
    )
    return plan, plan_artifact


def _complete_acquisition_work(
    work: SQLiteWorkStore,
    *,
    work_id: str,
    plan,
    plan_artifact,
) -> None:
    item = work.require(work_id)
    step = WorkStep(
        work_id=work_id,
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
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED, result={"summary": "done"}),
        expected_version=running.version,
    )


def _approve_architecture(
    store: ChangeStore,
    *,
    change_id: str,
    architecture,
    suffix: str,
) -> None:
    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(
        change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id=f"session-{suffix}",
        source_turn_id=f"turn-{suffix}",
        request_key=f"request-{suffix}",
    )


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


def test_phase9_completion_guard_requires_resolve_after_latest_source_evidence() -> (
    None
):
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
    assert reason is not None and "re-resolve" in reason


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


def test_phase9_research_revision_binds_architecture_to_exact_second_attempt(
    tmp_path,
) -> None:
    work, store, _, changes = _changes(tmp_path, handler=True)
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(_goal("power"), source_revision=REVISION)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None
    change_id = admission.change.change_id
    goal = _goal("power")

    plan1, plan_artifact1 = _persist_plan(
        store,
        change_id=change_id,
        goal=goal,
        package_version="1.0.0",
        changed_path="src/jarvis/tv_control.py",
    )
    _complete_acquisition_work(
        work,
        work_id=admission.acquisition_work_id,
        plan=plan1,
        plan_artifact=plan_artifact1,
    )
    changes.reconcile_for_work(admission.acquisition_work_id)
    architecture1 = ensure_capability_acquisition_architecture_current(
        store,
        change_id,
    )
    _approve_architecture(
        store,
        change_id=change_id,
        architecture=architecture1,
        suffix="architecture-1",
    )
    changes.reconcile(change_id)

    development = next(
        stage
        for stage in store.list_stages(change_id)
        if stage.stage_key
        == OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
    )
    store.request_architecture_revision_for_work(
        development.work_id,
        reason="The approved device transport is insufficient.",
    )
    changes.reconcile(change_id)
    source_attempts = [
        stage
        for stage in store.list_stages(change_id)
        if stage.stage_key
        == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
    ]
    assert [stage.attempt for stage in source_attempts] == [1, 2]
    source2 = source_attempts[-1]

    plan2, plan_artifact2 = _persist_plan(
        store,
        change_id=change_id,
        goal=goal,
        package_version="1.1.0",
        changed_path="src/jarvis/tv_control_v2.py",
    )
    _complete_acquisition_work(
        work,
        work_id=source2.work_id,
        plan=plan2,
        plan_artifact=plan_artifact2,
    )
    reconciled = changes.reconcile_for_work(source2.work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.ARCHITECTURE_READY
    architecture2 = ensure_capability_acquisition_architecture_current(
        store,
        change_id,
    )
    assert architecture2.artifact_id != architecture1.artifact_id
    assert architecture2.payload["plan_artifact_id"] == plan_artifact2.artifact_id
    assert architecture2.payload["proposed_package_version"] == "1.1.0"
    assert architecture2.payload["allowed_paths"] == ["src/jarvis/tv_control_v2.py"]

    # Restart-style replay after the replacement artifact already exists must
    # continue to resolve the exact second source attempt.
    replayed = changes.reconcile(change_id)
    assert replayed.state is ChangeState.ARCHITECTURE_READY
    assert (
        ensure_capability_acquisition_architecture_current(
            store,
            change_id,
        ).artifact_id
        == architecture2.artifact_id
    )


def test_phase9_revision_with_unchanged_architecture_fails_closed(
    tmp_path,
) -> None:
    work, store, _, changes = _changes(tmp_path, handler=True)
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(_goal("power"), source_revision=REVISION)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None
    change_id = admission.change.change_id
    goal = _goal("power")

    plan1, plan_artifact1 = _persist_plan(
        store,
        change_id=change_id,
        goal=goal,
        package_version="1.0.0",
        changed_path="src/jarvis/tv_control.py",
    )
    _complete_acquisition_work(
        work,
        work_id=admission.acquisition_work_id,
        plan=plan1,
        plan_artifact=plan_artifact1,
    )
    changes.reconcile_for_work(admission.acquisition_work_id)
    architecture1 = ensure_capability_acquisition_architecture_current(
        store,
        change_id,
    )
    _approve_architecture(
        store,
        change_id=change_id,
        architecture=architecture1,
        suffix="same-architecture",
    )
    changes.reconcile(change_id)

    development = next(
        stage
        for stage in store.list_stages(change_id)
        if stage.stage_key
        == OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
    )
    store.request_architecture_revision_for_work(
        development.work_id,
        reason="Re-research the device transport before continuing.",
    )
    changes.reconcile(change_id)
    source2 = [
        stage
        for stage in store.list_stages(change_id)
        if stage.stage_key
        == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
    ][-1]

    # Real acq_finalize reuses an unchanged plan artifact. Bind attempt 2 to that
    # exact existing artifact to prove the same architecture cannot be re-approved.
    _complete_acquisition_work(
        work,
        work_id=source2.work_id,
        plan=plan1,
        plan_artifact=plan_artifact1,
    )
    reconciled = changes.reconcile_for_work(source2.work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.FAILED
    no_progress = store.latest_artifact(
        change_id,
        "architecture_revision_no_progress",
    )
    assert no_progress is not None
    assert no_progress.payload["source_attempt"] == 2
    assert no_progress.payload["source_work_id"] == source2.work_id
    assert (
        no_progress.payload["unchanged_architecture_artifact_id"]
        == architecture1.artifact_id
    )
