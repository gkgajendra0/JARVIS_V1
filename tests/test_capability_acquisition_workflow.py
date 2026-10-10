from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

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
    migrate_legacy_gicc_external_acceptance_contracts,
)
from jarvis.capability_acquisition.artifacts import (
    candidate_from_payload,
    candidate_payload,
    evaluation_payload,
    goal_payload,
    plan_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
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
from jarvis.capability_acquisition.workflow import (
    AcquisitionRecordCandidateExecutor,
    AcquisitionWorkContextResolver,
    acquisition_completion_guard,
)
from jarvis.capability_registry.projection import (
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.models import WorkPriority, WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore

REVISION = "a" * 40


class _RecordCandidateResolver:
    def context_for(self, work_id: str):
        assert work_id == "research-work"
        return SimpleNamespace(work_id=work_id)


def test_record_candidate_schema_keeps_governance_out_of_model_parameters() -> None:
    schema = AcquisitionRecordCandidateExecutor.descriptor.parameter_schema
    properties = set(schema["properties"])

    assert set(schema["required"]) == {
        "source_kind",
        "source_identity",
        "supported_operations",
        "evidence_refs",
    }
    assert "verification_requirements" not in properties
    assert "external_acceptance_requirements" not in properties
    assert "secret_scopes" not in properties
    assert "network_scopes" not in properties
    assert "device_scopes" not in properties
    assert "discovery_scopes" not in properties


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_kind", "expected_contract"),
    [
        ("mcp", "mcp-tools-list-contract"),
        ("openapi", "openapi-contract-test"),
        ("asyncapi", "asyncapi-contract-test"),
        ("sdk_library", "sdk-adapter-contract-test"),
    ],
)
async def test_record_candidate_assigns_deterministic_verification_contract(
    source_kind: str,
    expected_contract: str,
) -> None:
    executor = AcquisitionRecordCandidateExecutor(_RecordCandidateResolver())

    result = await executor.execute(
        work=SimpleNamespace(work_id="research-work"),
        parameters={
            "source_kind": source_kind,
            "source_identity": "example-source",
            "source_version": "1.2.3",
            "source_digest": None,
            "supported_operations": ["launch", "pair"],
            "evidence_refs": ["evidence-1"],
            "license_id": "MIT",
        },
    )

    candidate = candidate_from_payload(result["candidate"])
    assert candidate.source_kind is AcquisitionSourceKind(source_kind)
    assert candidate.verification_requirements == (expected_contract,)
    assert candidate.secret_scopes == ()
    assert candidate.network_scopes == ()
    assert candidate.device_scopes == ()
    assert candidate.discovery_scopes == ()
    assert candidate.external_acceptance_requirements == ()
    assert result["trust_assignment"] == "unverified_candidate"
    assert result["execution_authorized"] is False


@pytest.mark.asyncio
async def test_record_sdk_candidate_normalizes_pypi_project_url() -> None:
    executor = AcquisitionRecordCandidateExecutor(_RecordCandidateResolver())

    result = await executor.execute(
        work=SimpleNamespace(work_id="research-work"),
        parameters={
            "source_kind": "sdk_library",
            "source_identity": "https://pypi.org/project/samsungtvws/2.4.0/",
            "source_version": "2.4.0",
            "source_digest": None,
            "supported_operations": ["issue_supported_control"],
            "evidence_refs": ["https://pypi.org/project/samsungtvws/2.4.0/"],
            "license_id": "MIT",
        },
    )

    candidate = candidate_from_payload(result["candidate"])
    assert candidate.source_identity == "samsungtvws"


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
    if "entity_type:television" not in goal.target_hints:
        resolution = resolver.resolve(goal, _empty_context())
    else:
        # The legacy-migration fixture supplies an explicit synthetic target
        # declaration; the normal blind custom-build source remains blocked.
        original = CustomBuildCapabilitySourceAdapter().discover(
            goal, _empty_context()
        )[0]
        fixture = AcquisitionCandidateV1.create(
            source_kind=original.source_kind,
            source_identity=original.source_identity,
            source_version=original.source_version,
            source_digest=original.source_digest,
            trust_class=original.trust_class,
            supported_operations=original.supported_operations,
            strategy=original.strategy,
            evidence_refs=(
                *original.evidence_refs,
                "test-fixture:explicit-device-compatibility-contract",
            ),
            verification_requirements=original.verification_requirements,
            device_scopes=("entity_type:television",),
            reason_codes=original.reason_codes,
        )
        resolution = resolver.resolve_candidates(goal, (fixture,), _empty_context())
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


def test_legacy_gicc_acceptance_contract_migration_reopens_exact_owner_gate(
    tmp_path,
) -> None:
    work, store, _, changes = _changes(tmp_path, handler=True)
    goal = OwnerCapabilityGoalV1.create(
        request="Acquire reusable media-player control.",
        requested_capability="media_player.control",
        required_operations=("power",),
        target_hints=(
            "entity_type:television",
            "entity_id:living-room",
        ),
        source_session_id="gicc:legacy-goal",
        source_turn_id="gap:legacy-gap",
        now_epoch=100.0,
    )
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(goal, source_revision=REVISION)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None
    change_id = admission.change.change_id
    store.add_artifact(
        change_id,
        kind="gicc_capability_gap_link",
        payload={
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": "legacy-request",
            "request_digest": "r" * 64,
            "motivating_goal_id": "legacy-goal",
            "gap_id": "legacy-gap",
            "engineering_change_id": change_id,
            "reusable_capability_family": "media_player.control",
            "minimum_required_operations": ["power"],
            "target_entity_type": "television",
            "target_entity_id": "living-room",
            "monitor_event_contract_required": False,
            "monitor_event_contract": None,
        },
    )
    store.add_artifact(
        change_id,
        kind="gicc_target_context",
        payload={
            "schema": "gicc_target_context.v1",
            "target_entity_type": "television",
            "target_entity_id": "living-room",
            "canonical_name": "Living room TV fixture",
            "provenance_refs": ["owner_inventory:verified_fixture_television"],
            "target_hints": [
                "entity_type:television",
                "entity_name:Living room TV fixture",
            ],
        },
    )
    plan, plan_artifact = _persist_plan(
        store,
        change_id=change_id,
        goal=goal,
        package_version="1.0.0",
        changed_path="src/jarvis/tv_control.py",
    )
    _complete_acquisition_work(
        work,
        work_id=admission.acquisition_work_id,
        plan=plan,
        plan_artifact=plan_artifact,
    )
    changes.reconcile_for_work(admission.acquisition_work_id)
    current = ensure_capability_acquisition_architecture_current(store, change_id)
    assert (
        PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
        in current.payload["owner_acceptance_contract_ids"]
    )

    expected_semantic_contract = current.payload["semantic_capability_contract"]
    legacy_payload = dict(current.payload)
    legacy_payload["owner_acceptance_contract_ids"] = []
    legacy_payload["semantic_capability_contract"] = {
        **expected_semantic_contract,
        "target_entity_type": "stale-television-type",
    }
    legacy_payload.pop("external_runtime_contract", None)
    legacy = store.add_artifact(
        change_id,
        kind="architecture",
        payload=legacy_payload,
    )
    with work._lock, work._connect() as db:
        db.execute(
            """UPDATE engineering_changes
            SET state=?, version=version+1
            WHERE change_id=?""",
            (ChangeState.APPROVED_FOR_BUILD.value, change_id),
        )

    before_revision = legacy.revision
    assert migrate_legacy_gicc_external_acceptance_contracts(
        store,
        dry_run=True,
    ) == (change_id,)
    assert store.latest_artifact(change_id, "architecture").revision == before_revision
    assert store.require(change_id).state is ChangeState.APPROVED_FOR_BUILD

    assert migrate_legacy_gicc_external_acceptance_contracts(store) == (change_id,)
    migrated = store.latest_artifact(change_id, "architecture")
    assert migrated is not None
    assert migrated.revision == before_revision + 1
    assert (
        PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
        in migrated.payload["owner_acceptance_contract_ids"]
    )
    assert (
        migrated.payload["semantic_capability_contract"] == expected_semantic_contract
    )
    assert store.require(change_id).state is ChangeState.ARCHITECTURE_READY

    gate_ids = reconcile_owner_change_gates(
        changes,
        change_ids=(change_id,),
    )
    assert len(gate_ids) == 1
    assert store.require(change_id).state is ChangeState.WAITING_OWNER_APPROVAL
    gate = GateService(store, verify_owner=lambda *_: False).get(gate_ids[0])
    challenge = getattr(gate, "challenge", gate)
    assert challenge.artifact_id == migrated.artifact_id
    assert challenge.artifact_digest == migrated.digest


def test_architecture_cannot_create_canonical_device_facts(tmp_path) -> None:
    """An approved or proposed Roku adapter cannot self-prove TV identity."""

    _, store, _, changes = _changes(tmp_path)
    goal = _goal("power")
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(goal, source_revision=REVISION)
    assert admission.change is not None
    change_id = admission.change.change_id

    store.add_artifact(
        change_id,
        kind="gicc_capability_gap_link",
        payload={"target_entity_type": "television"},
    )
    store.add_artifact(
        change_id,
        kind="gicc_target_context",
        payload={
            "target_hints": [
                "entity_type:television",
                "entity_name:living room TV",
            ],
        },
    )
    store.add_artifact(
        change_id,
        kind="architecture",
        payload={
            "target_entity_type": "television",
            "target_vendor": "unverified-vendor",
            "target_platform": "unverified-platform",
            "target_protocol": "unverified-protocol",
            "target_model": "unverified-model",
        },
    )

    from types import SimpleNamespace

    context = SimpleNamespace(change_id=change_id, goal=goal)
    hints = AcquisitionWorkContextResolver(store).canonical_target_hints(context)

    assert "entity_type:television" in hints
    assert "entity_name:living room tv" in hints
    assert not any(
        value in hints
        for value in (
            "vendor:unverified-vendor",
            "platform:unverified-platform",
            "protocol:unverified-protocol",
            "model:unverified-model",
        )
    )


def test_canonical_target_context_does_not_reimport_stale_goal_platform(
    tmp_path,
) -> None:
    """Owner claims and observed target facts must remain independent."""
    _, store, _, changes = _changes(tmp_path)
    goal = OwnerCapabilityGoalV1.create(
        request="Control my television",
        requested_capability="media_player.control",
        required_operations=("power",),
        target_hints=("entity_type:television", "platform:roku"),
        source_session_id="stale-roku-session",
        source_turn_id="original-stale-roku-claim",
        now_epoch=100.0,
    )
    admission = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(goal, source_revision=REVISION)
    assert admission.change is not None
    change_id = admission.change.change_id
    store.add_artifact(
        change_id,
        kind="gicc_capability_gap_link",
        payload={"target_entity_type": "television"},
    )
    store.add_artifact(
        change_id,
        kind="gicc_target_context",
        payload={
            "target_hints": (
                "entity_type:television",
                "entity_name:confirmed owner TV",
                "platform:vidaa",
            )
        },
    )
    context = SimpleNamespace(change_id=change_id, goal=goal)
    independently_reviewed = AcquisitionWorkContextResolver(
        store
    ).canonical_target_hints(context)
    assert "platform:vidaa" in independently_reviewed
    assert "platform:roku" not in independently_reviewed
    assert "entity_name:confirmed owner tv" in independently_reviewed
    assert "platform:roku" in goal.target_hints
