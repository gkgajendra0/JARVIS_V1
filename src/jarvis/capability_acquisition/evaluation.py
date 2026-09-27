"""Deterministic Phase-9 owner-requested capability acquisition replay."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Callable

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
)
from jarvis.capability_acquisition.artifacts import (
    candidate_payload,
    evaluation_payload,
    plan_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.external_acceptance import (
    Phase9ExternalAcceptanceError,
    validate_external_acceptance,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionDisposition,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.runtime_context import StaticAcquisitionContextProvider
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
    McpCapabilitySourceAdapter,
    OpenApiCapabilitySourceAdapter,
    mcp_server_evidence,
    openapi_contract_evidence,
)
from jarvis.capability_registry.compatibility import CompatibilityVerdict
from jarvis.capability_registry.evaluation import run_replay_suite as run_phase8_replay
from jarvis.capability_registry.models import (
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityInventoryEntry,
    CapabilityManagementMode,
    EffectiveCapabilityState,
)
from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    EngineeringSubstrateChangeService,
    ensure_substrate_acceptance_current,
)
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.promotion.evaluation import run_replay_suite as run_phase7_replay
from jarvis.self_model.health import HealthState
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore

_REVISION = "a" * 40


@dataclass(frozen=True, slots=True)
class Phase9ReplayCase:
    case_id: str
    passed: bool
    evidence: dict[str, object]

    def payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Phase9ReplayReport:
    cases: tuple[Phase9ReplayCase, ...]
    status: str
    suite_digest: str
    phase7_suite_digest: str
    phase8_suite_digest: str

    def payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.payload() for item in self.cases],
            "phase7_suite_digest": self.phase7_suite_digest,
            "phase8_suite_digest": self.phase8_suite_digest,
        }


@dataclass
class _Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


@dataclass
class _StaticAdapter:
    source_kind: AcquisitionSourceKind
    candidates: tuple[AcquisitionCandidateV1, ...]

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]:
        del context
        required = set(goal.required_operations)
        return tuple(
            item
            for item in self.candidates
            if required.issubset(item.supported_operations)
        )


def _case(
    case_id: str,
    callback: Callable[[], dict[str, object]],
) -> Phase9ReplayCase:
    try:
        evidence = callback()
    except Exception as exc:  # noqa: BLE001 - replay preserves exact failure evidence
        return Phase9ReplayCase(
            case_id=case_id,
            passed=False,
            evidence={"error_type": type(exc).__name__, "reason": str(exc)},
        )
    return Phase9ReplayCase(case_id=case_id, passed=True, evidence=evidence)


def _goal(
    *operations: str,
    turn_id: str = "turn-phase9-replay",
) -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire TV control capability",
        requested_capability="TV control",
        required_operations=operations or ("power",),
        target_hints=("replay-target",),
        source_session_id="phase9-replay",
        source_turn_id=turn_id,
        now_epoch=1_800_000_000.0,
    )


def _empty_context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _core_context(*, enabled: bool = True) -> AcquisitionContextV1:
    descriptor = CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="phase9.replay",
        kind=CapabilityKind.NATIVE_API,
        name="Replay TV control",
        description="Existing replay capability.",
        operations=("power", "volume"),
        execution_enabled=enabled,
    )
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=(descriptor,)),
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.CORE_PINNED,
            ),
        ),
    )


def _managed_disabled_context() -> AcquisitionContextV1:
    descriptor = CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="phase9.replay",
        kind=CapabilityKind.NATIVE_API,
        name="Replay TV control",
        description="Package-managed replay capability.",
        operations=("power", "volume"),
        execution_enabled=False,
    )
    state = EffectiveCapabilityState(
        capability_id=descriptor.capability_id,
        capability_key=descriptor.key,
        component_id="capability.package:tv.control",
        management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        registry_generation=2,
        applied_generation=2,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="tv.control.package",
        selected_package_version="1.0.0",
        selected_package_digest="b" * 64,
        package_disposition=PackageDisposition.AVAILABLE,
        compatibility_verdict=CompatibilityVerdict.READY,
        compatibility_digest="c" * 64,
        health_state=HealthState.DISABLED,
        transition_fenced=False,
        effective_enabled=False,
        reason_codes=("desired_disabled",),
    )
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=(descriptor,)),
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
            ),
        ),
        effective_snapshot=CapabilityEffectiveSnapshot(
            release_sha="d" * 40,
            states=(state,),
            reconciled_at_epoch=1_800_000_000.0,
            trigger="phase9_replay",
        ),
    )


def _candidate(
    *,
    source_kind: AcquisitionSourceKind = AcquisitionSourceKind.MCP,
    source_identity: str = "mcp:tv",
    trust: AcquisitionTrustClass = AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
    strategy: AcquisitionStrategy = AcquisitionStrategy.WRAP,
    source_digest: str | None = "e" * 64,
) -> AcquisitionCandidateV1:
    return AcquisitionCandidateV1.create(
        source_kind=source_kind,
        source_identity=source_identity,
        source_digest=source_digest,
        trust_class=trust,
        supported_operations=("power", "volume"),
        strategy=strategy,
        evidence_refs=("phase9-replay:evidence",),
        verification_requirements=("phase9-replay:verify",),
    )


def _resolver(*adapters) -> CapabilityAcquisitionResolver:
    return CapabilityAcquisitionResolver(CapabilitySourceRegistry(tuple(adapters)))


def _01_existing_reuse() -> dict[str, object]:
    result = _resolver(ExistingCapabilitySourceAdapter()).resolve(
        _goal("power"),
        _core_context(),
    )
    candidate = result.selected_candidate
    if candidate is None or candidate.strategy is not AcquisitionStrategy.REUSE:
        raise AssertionError("existing ready capability was not reused")
    return {"candidate_id": candidate.candidate_id, "strategy": candidate.strategy.value}


def _02_disabled_package_lifecycle_reuse() -> dict[str, object]:
    result = _resolver(ExistingCapabilitySourceAdapter()).resolve(
        _goal("power"),
        _managed_disabled_context(),
    )
    candidate = result.selected_candidate
    if candidate is None:
        raise AssertionError("compatible disabled package was not reusable")
    evaluation = result.evaluation(candidate.candidate_id)
    if "existing_package_lifecycle_reuse" not in evaluation.reason_codes:
        raise AssertionError("disabled package did not route to lifecycle reuse")
    return {"reason_codes": list(evaluation.reason_codes)}


def _03_duplicate_candidates() -> dict[str, object]:
    candidate = _candidate()
    result = _resolver(
        _StaticAdapter(AcquisitionSourceKind.MCP, (candidate, candidate)),
    ).resolve(_goal("power"), _empty_context())
    if len(result.candidates) != 1:
        raise AssertionError("exact duplicate candidates were not deduplicated")
    return {"candidate_count": len(result.candidates)}


def _04_stronger_evidence() -> dict[str, object]:
    owner = _candidate(
        source_kind=AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL,
        source_identity="owner:home-assistant",
        trust=AcquisitionTrustClass.OWNER_CONFIGURED,
        source_digest="1" * 64,
    )
    remote = _candidate(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity="mcp:vendor",
        trust=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        source_digest="2" * 64,
    )
    result = _resolver(
        _StaticAdapter(AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL, (owner,)),
        _StaticAdapter(AcquisitionSourceKind.MCP, (remote,)),
    ).resolve(_goal("power"), _empty_context())
    if result.selected_candidate != owner:
        raise AssertionError("stronger trust evidence did not win equal strategy")
    return {"selected_trust": owner.trust_class.value}


def _05_wrap_beats_custom() -> dict[str, object]:
    evidence = mcp_server_evidence(
        server_identity="mcp:verified",
        tools=({"name": "power", "inputSchema": {"type": "object"}},),
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:mcp",),
    )
    result = _resolver(
        McpCapabilitySourceAdapter((evidence,)),
        CustomBuildCapabilitySourceAdapter(),
    ).resolve(_goal("power"), _empty_context())
    selected = result.selected_candidate
    if selected is None or selected.strategy is not AcquisitionStrategy.WRAP:
        raise AssertionError("verified wrap did not beat custom build")
    return {"strategy": selected.strategy.value}


def _06_unverified_blocked() -> dict[str, object]:
    candidate = _candidate(
        trust=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        source_digest=None,
    )
    result = _resolver(
        _StaticAdapter(AcquisitionSourceKind.MCP, (candidate,)),
    ).resolve(_goal("power"), _empty_context())
    if result.selected_candidate is not None:
        raise AssertionError("unverified candidate became selectable")
    evaluation = result.evaluations[0]
    if evaluation.disposition is not AcquisitionDisposition.BLOCKED:
        raise AssertionError("unverified candidate was not blocked")
    return {"reason_codes": list(evaluation.reason_codes)}


def _07_no_safe_route() -> dict[str, object]:
    result = _resolver().resolve(_goal("power"), _empty_context())
    if result.selected_candidate is not None or result.candidates:
        raise AssertionError("empty source set produced a candidate")
    return {"selected_candidate_id": None, "candidate_count": 0}


def _08_stale_candidate_plan() -> dict[str, object]:
    goal = _goal("power")
    first = _candidate(source_identity="mcp:first", source_digest="3" * 64)
    second = _candidate(source_identity="mcp:second", source_digest="4" * 64)
    evaluation = AcquisitionCandidateEvaluationV1.create(
        first,
        requested_operations=goal.required_operations,
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )
    try:
        CapabilityAcquisitionPlanV1.create(
            goal,
            second,
            evaluation,
            proposed_capability_id="tv.control",
            proposed_package_id="tv.control.package",
            proposed_package_version="1.0.0",
            rollback_summary="Disable.",
            changed_paths=("src/jarvis/tv_control.py",),
            sandbox_profile_ids=("test.offline.v1",),
            verification_contract_ids=("verify.tv.v1",),
            development_test_targets=("tests/test_tv_control.py",),
            evidence_refs=("phase9-replay",),
        )
    except ValueError:
        return {"stale_binding_rejected": True}
    raise AssertionError("plan accepted evaluation for another candidate")


def _admission_environment(root: pathlib.Path, *, turn_id: str):
    store = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend([])
    coordinator = ChangeCoordinator(store, backend)
    acquisition = CapabilityAcquisitionCoordinator(
        changes=coordinator,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    )
    admission = acquisition.admit(
        _goal("power", turn_id=turn_id),
        source_revision=_REVISION,
    )
    return store, backend, admission


def _architecture_ready(root: pathlib.Path, *, turn_id: str):
    root.mkdir(parents=True, exist_ok=True)
    work = SQLiteWorkStore(root / "work.sqlite3")
    store = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend([])
    coordinator = ChangeCoordinator(
        store,
        backend,
        source_completion_handlers=(
            CapabilityAcquisitionSourceCompletionHandler(store),
        ),
    )
    acquisition = CapabilityAcquisitionCoordinator(
        changes=coordinator,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    )
    goal = _goal("power", turn_id=turn_id)
    admission = acquisition.admit(goal, source_revision=_REVISION)
    if admission.change is None or admission.acquisition_work_id is None:
        raise AssertionError("expected build acquisition EngineeringChange")

    resolver = _resolver(CustomBuildCapabilitySourceAdapter())
    resolution = resolver.resolve(goal, _empty_context())
    candidate = resolution.selected_candidate
    if candidate is None:
        raise AssertionError("custom build fallback was not selected")
    evaluation = resolution.evaluation(candidate.candidate_id)
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
        proposed_package_id="tv.control.package",
        proposed_package_version="1.0.0",
        rollback_summary="Disable package and revert promoted release.",
        changed_paths=(
            "src/jarvis/tv_control.py",
            "tests/test_tv_control.py",
            "capability_packages/tv.control.package.json",
        ),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("verify.tv.v1",),
        development_test_targets=("tests/test_tv_control.py",),
        owner_acceptance_contract_ids=("owner.tv.effect.v1",),
        evidence_refs=("phase9-replay:owner-goal",),
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
    source_work = work.require(admission.acquisition_work_id)
    step = WorkStep(
        work_id=source_work.work_id,
        kind="acq_finalize",
        summary="finalize exact Phase-9 plan",
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
        source_work.transition(WorkState.RUNNING),
        expected_version=source_work.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED, result={"summary": "plan complete"}),
        expected_version=running.version,
    )
    change = coordinator.reconcile_for_work(source_work.work_id)
    if change is None or change.state is not ChangeState.ARCHITECTURE_READY:
        raise AssertionError("Phase-9 architecture did not become ready")
    architecture = store.latest_artifact(change.change_id, "architecture")
    if architecture is None:
        raise AssertionError("Phase-9 architecture artifact is missing")
    return work, store, backend, coordinator, change, plan, architecture


def _09_idempotent_admission(root: pathlib.Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    store, backend, first = _admission_environment(root, turn_id="idempotent")
    if first.change is None or first.acquisition_work_id is None:
        raise AssertionError("engineering acquisition was not created")

    item = store.work.require(first.acquisition_work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )

    reopened_store = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    reopened_backend = _Backend([])
    acquisition = CapabilityAcquisitionCoordinator(
        changes=ChangeCoordinator(reopened_store, reopened_backend),
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    )
    second = acquisition.admit(
        _goal("power", turn_id="idempotent"),
        source_revision=_REVISION,
    )
    if second.change is None or second.acquisition_work_id is None:
        raise AssertionError("reopened acquisition was not available")
    observed = reopened_store.work.require(second.acquisition_work_id)
    if (
        first.change.change_id != second.change.change_id
        or first.acquisition_work_id != second.acquisition_work_id
        or observed.work_id != running.work_id
        or observed.state is not WorkState.RUNNING
    ):
        raise AssertionError("restart changed acquisition research identity/state")
    return {
        "change_id": first.change.change_id,
        "work_id": first.acquisition_work_id,
        "state": observed.state.value,
        "reopened_submit_count": len(reopened_backend.submitted),
    }


def _10_waiting_resource_identity(root: pathlib.Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    store, _, admission = _admission_environment(root, turn_id="resource")
    if admission.acquisition_work_id is None:
        raise AssertionError("resource replay lacks acquisition WorkItem")
    delivery = EngineeringSubstrateChangeService(store).block_work_resource(
        admission.acquisition_work_id,
        component="model-provider",
        reason_code="rate_limited",
        message="Provider pressure requires bounded retry.",
    )
    reopened = SQLiteWorkStore(root / "work.sqlite3").require(
        admission.acquisition_work_id
    )
    if reopened.state is not WorkState.WAITING_RESOURCE:
        raise AssertionError("provider pressure did not persist WAITING_RESOURCE")
    return {
        "work_id": reopened.work_id,
        "wait_state": reopened.state.value,
        "delivery_id": delivery.delivery_id,
    }


def _11_waiting_owner_identity(root: pathlib.Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    store, _, admission = _admission_environment(root, turn_id="owner")
    if admission.acquisition_work_id is None:
        raise AssertionError("owner-input replay lacks acquisition WorkItem")
    item = store.work.require(admission.acquisition_work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    waiting = store.work.save(
        running.transition(
            WorkState.WAITING_FOR_OWNER,
            status_detail="device_pairing_or_credential_required",
        ),
        expected_version=running.version,
    )
    reopened = SQLiteWorkStore(root / "work.sqlite3").require(waiting.work_id)
    if reopened.state is not WorkState.WAITING_FOR_OWNER:
        raise AssertionError("missing owner input did not persist WAITING_FOR_OWNER")
    return {
        "work_id": reopened.work_id,
        "wait_state": reopened.state.value,
    }


def _gate_fixture(root: pathlib.Path, *, turn: str):
    store = ChangeStore(SQLiteWorkStore(root / "work.sqlite3"))
    change = store.create(
        request="Shared owner gate replay",
        process_key="engineering.change",
        process_version=1,
        source_session_id="phase9-replay",
        source_turn_id=turn,
    )
    with store.work._lock, store.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (ChangeState.ARCHITECTURE_READY.value, change.change_id),
        )
    artifact = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"schema": "phase9-replay-architecture", "plan_digest": "5" * 64},
    )
    gates = GateService(store, verify_owner=lambda *_: True)
    return store, change, artifact, gates


def _12_exact_architecture_digest(root: pathlib.Path) -> dict[str, object]:
    _, store, _, _, change, plan, architecture = _architecture_ready(
        root,
        turn_id="exact-gate",
    )
    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    try:
        gates.decide(
            gate.gate_id,
            approved=True,
            artifact_digest="9" * 64,
            actor_id="owner",
            source_session_id="phase9-replay",
            source_turn_id="wrong-digest",
            request_key="phase9-replay:wrong",
        )
    except ChangeConflict:
        pass
    else:
        raise AssertionError("wrong architecture digest was approved")
    decision = gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="phase9-replay",
        source_turn_id="approve",
        request_key="phase9-replay:exact",
    )
    current = store.require(change.change_id)
    if (
        not decision.approved
        or current.state is not ChangeState.APPROVED_FOR_BUILD
        or architecture.payload.get("plan_digest") != plan.digest
    ):
        raise AssertionError("Phase-9 architecture approval lost exact plan binding")
    return {
        "approved": True,
        "artifact_digest": architecture.digest,
        "plan_digest": plan.digest,
    }


def _13_superseded_architecture(root: pathlib.Path) -> dict[str, object]:
    _, store, _, _, change, _, architecture = _architecture_ready(
        root,
        turn_id="superseded",
    )
    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            **architecture.payload,
            "rollback_strategy": "superseded replay revision",
        },
    )
    try:
        gates.decide(
            gate.gate_id,
            approved=True,
            artifact_digest=architecture.digest,
            actor_id="owner",
            source_session_id="phase9-replay",
            source_turn_id="approve-old",
            request_key="phase9-replay:old",
        )
    except ChangeConflict:
        return {"superseded_approval_rejected": True}
    raise AssertionError("superseded Phase-9 architecture approval was accepted")


def _14_no_development_before_gate(root: pathlib.Path) -> dict[str, object]:
    _, _, _, coordinator, change, _, _ = _architecture_ready(
        root,
        turn_id="no-dev",
    )
    try:
        coordinator.submit_stage(change.change_id, "development", 1)
    except ChangeConflict:
        return {"development_before_approval": "rejected"}
    raise AssertionError("DEVELOPMENT started before Phase-9 architecture approval")


def _15_phase8_supply_chain(root: pathlib.Path) -> dict[str, object]:
    _, store, _, _, change, _, architecture = _architecture_ready(
        root,
        turn_id="substrate-failure",
    )
    gates = GateService(store, verify_owner=lambda *_: True)
    gate = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="phase9-replay",
        source_turn_id="approve-substrate",
        request_key="phase9-replay:substrate",
    )
    store.add_artifact(
        change.change_id,
        kind="substrate_manifest",
        payload={
            "schema": "phase9-replay-stale-substrate",
            "manifest_digest": "f" * 64,
        },
    )
    try:
        ensure_substrate_acceptance_current(store, change.change_id)
    except ChangeConflict:
        return {"dependency_or_provenance_verification": "blocked"}
    raise AssertionError("stale Phase-5 substrate evidence did not block acceptance")


def _15_phase8_supply_chain(phase8) -> dict[str, object]:
    if phase8.status != "PASS" or len(phase8.cases) != 45:
        raise AssertionError("accepted Phase-8 supply-chain replay is not green")
    return {"phase8_cases": len(phase8.cases), "suite_digest": phase8.suite_digest}


def _16_plaintext_secret_rejected() -> dict[str, object]:
    try:
        AcquisitionCandidateV1.create(
            source_kind=AcquisitionSourceKind.MCP,
            source_identity="mcp:secret-test",
            source_digest="7" * 64,
            trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
            supported_operations=("power",),
            strategy=AcquisitionStrategy.WRAP,
            evidence_refs=("phase9-replay",),
            verification_requirements=("verify",),
            plaintext_secret="do-not-store",  # type: ignore[call-arg]
        )
    except TypeError:
        return {"plaintext_secret_field": "rejected"}
    raise AssertionError("candidate contract accepted plaintext secret field")


def _17_external_metadata_inert() -> dict[str, object]:
    evidence = openapi_contract_evidence(
        source_identity="https://example.invalid/openapi.json",
        document={
            "openapi": "3.1.0",
            "command": "rm -rf /",
            "paths": {
                "/power": {
                    "post": {
                        "operationId": "power",
                        "x-executable": "malicious.exe",
                    }
                }
            },
        },
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("phase9-replay:openapi",),
    )
    candidate = OpenApiCapabilitySourceAdapter((evidence,)).discover(
        _goal("power"),
        _empty_context(),
    )[0]
    forbidden = ("command", "argv", "executable", "import_path")
    if any(hasattr(candidate, field) for field in forbidden):
        raise AssertionError("external metadata created execution authority")
    return {"candidate_fields_inert": True, "operations": list(candidate.supported_operations)}


def _18_protected_surface() -> dict[str, object]:
    assessment = RepairProtectedSurfacePolicy().assess(
        ("src/jarvis/capability_acquisition/verification.py",)
    )
    if assessment.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise AssertionError("Phase-9 governance surface was not protected")
    return {
        "policy_version": assessment.policy_version,
        "verdict": assessment.verdict.value,
    }


def _19_no_auto_enable(phase8) -> dict[str, object]:
    if phase8.status != "PASS":
        raise AssertionError("Phase-8 lifecycle replay failed")
    return {
        "phase8_suite_digest": phase8.suite_digest,
        "invariant": "package_admission_does_not_authorize_activation",
    }


def _20_compatibility_fail_closed(phase8) -> dict[str, object]:
    if phase8.status != "PASS":
        raise AssertionError("Phase-8 compatibility replay failed")
    return {
        "phase8_suite_digest": phase8.suite_digest,
        "invariant": "blocked_or_quarantined_package_not_effective",
    }


def _21_phase7_only_promotion(phase7) -> dict[str, object]:
    if phase7.status != "PASS" or len(phase7.cases) != 14:
        raise AssertionError("accepted Phase-7 promotion replay is not green")
    return {"phase7_cases": len(phase7.cases), "suite_digest": phase7.suite_digest}


def _22_rollback_safe(phase7, phase8) -> dict[str, object]:
    if phase7.status != "PASS" or phase8.status != "PASS":
        raise AssertionError("rollback/lifecycle dependency replay failed")
    return {
        "phase7_suite_digest": phase7.suite_digest,
        "phase8_suite_digest": phase8.suite_digest,
        "rollback_invariant": "governed_rollback_or_disable_only",
    }


def _23_real_external_required() -> dict[str, object]:
    fake = {
        "schema": "phase9_external_acceptance.v1",
        "capability_id": "tv.control",
        "package_id": "tv.control.package",
        "package_version": "1.0.0",
        "package_digest": "8" * 64,
        "target_kind": "device",
        "target_identity": "replay-device",
        "operations": [
            {
                "operation": "power",
                "verified": True,
                "external_effect_observed": False,
                "observation": "No external effect was actually observed.",
                "evidence_refs": ["replay:no-effect"],
            }
        ],
        "effective_enabled_verified": True,
        "disable_rollback_verified": True,
        "owner_confirmed": True,
        "recorded_at": "2026-09-27T00:00:00Z",
        "source": "phase9-replay",
    }
    try:
        validate_external_acceptance(fake)
    except Phase9ExternalAcceptanceError:
        return {"synthetic_no_effect_rejected": True}
    raise AssertionError("external acceptance passed without a real observed effect")


def _24_cold_restart_identity(root: pathlib.Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    _, _, first = _admission_environment(root, turn_id="cold-restart")
    if first.change is None or first.acquisition_work_id is None:
        raise AssertionError("initial acquisition was not durable")
    reopened = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend([])
    acquisition = CapabilityAcquisitionCoordinator(
        changes=ChangeCoordinator(reopened, backend),
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    )
    second = acquisition.admit(
        _goal("power", turn_id="cold-restart"),
        source_revision=_REVISION,
    )
    if second.change is None:
        raise AssertionError("reopened acquisition was unavailable")
    if (
        second.change.change_id != first.change.change_id
        or second.acquisition_work_id != first.acquisition_work_id
    ):
        raise AssertionError("cold restart changed canonical acquisition identity")
    return {
        "change_id": first.change.change_id,
        "work_id": first.acquisition_work_id,
    }


def run_replay_suite(root: pathlib.Path) -> Phase9ReplayReport:
    replay_root = pathlib.Path(root).resolve()
    replay_root.mkdir(parents=True, exist_ok=True)

    phase7 = run_phase7_replay(replay_root / "phase7")
    phase8 = run_phase8_replay(replay_root / "phase8")

    cases = (
        _case("01_existing_capability_reuse", _01_existing_reuse),
        _case("02_disabled_package_lifecycle_reuse", _02_disabled_package_lifecycle_reuse),
        _case("03_duplicate_candidates_deduplicate", _03_duplicate_candidates),
        _case("04_stronger_verified_evidence_wins", _04_stronger_evidence),
        _case("05_wrap_beats_custom_build", _05_wrap_beats_custom),
        _case("06_unverified_source_cannot_select", _06_unverified_blocked),
        _case("07_no_candidate_truthful_no_safe_route", _07_no_safe_route),
        _case("08_stale_candidate_invalidates_plan", _08_stale_candidate_plan),
        _case("09_acquisition_admission_idempotent", lambda: _09_idempotent_admission(replay_root / "09")),
        _case(
            "10_waiting_resource_preserves_identity",
            lambda: _10_waiting_resource_identity(replay_root / "10"),
        ),
        _case(
            "11_waiting_owner_preserves_identity",
            lambda: _11_waiting_owner_identity(replay_root / "11"),
        ),
        _case("12_architecture_approval_exact_digest", lambda: _12_exact_architecture_digest(replay_root / "12")),
        _case("13_architecture_revision_invalidates_approval", lambda: _13_superseded_architecture(replay_root / "13")),
        _case("14_development_blocked_before_approval", lambda: _14_no_development_before_gate(replay_root / "14")),
        _case(
            "15_dependency_provenance_fail_closed",
            lambda: _15_phase8_supply_chain(replay_root / "15"),
        ),
        _case("16_plaintext_secret_injection_rejected", _16_plaintext_secret_rejected),
        _case("17_external_metadata_cannot_inject_execution", _17_external_metadata_inert),
        _case("18_acquisition_governance_surface_protected", _18_protected_surface),
        _case("19_package_registration_does_not_auto_enable", lambda: _19_no_auto_enable(phase8)),
        _case("20_package_compatibility_failure_unavailable", lambda: _20_compatibility_fail_closed(phase8)),
        _case("21_source_promotion_reuses_phase7", lambda: _21_phase7_only_promotion(phase7)),
        _case("22_rollback_disable_restores_safe_state", lambda: _22_rollback_safe(phase7, phase8)),
        _case("23_real_external_effect_is_mandatory", _23_real_external_required),
        _case("24_cold_restart_preserves_canonical_identity", lambda: _24_cold_restart_identity(replay_root / "24")),
    )
    status = "PASS" if all(item.passed for item in cases) else "FAIL"
    payload = {
        "status": status,
        "cases": [item.payload() for item in cases],
        "phase7_suite_digest": phase7.suite_digest,
        "phase8_suite_digest": phase8.suite_digest,
    }
    return Phase9ReplayReport(
        cases=cases,
        status=status,
        suite_digest=canonical_digest(payload),
        phase7_suite_digest=phase7.suite_digest,
        phase8_suite_digest=phase8.suite_digest,
    )
