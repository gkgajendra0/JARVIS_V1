"""Deterministic Phase-9 capability-acquisition replay evaluation."""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, replace

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
    McpCapabilitySourceAdapter,
    OpenApiCapabilitySourceAdapter,
    OwnerConfiguredCapabilitySourceAdapter,
    mcp_server_evidence,
    openapi_contract_evidence,
    owner_configured_evidence,
)
from jarvis.capability_acquisition.verification import (
    CapabilityCandidateError,
    ensure_capability_substrate_requirements_current,
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
from jarvis.engineering_change.models import ChangeArtifact
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    EngineeringSubstrateChangeService,
)
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.promotion.evaluation import run_replay_suite as run_phase7_replay
from jarvis.self_model.health import HealthState
from jarvis.work.models import WorkPriority, WorkState
from jarvis.work.store import SQLiteWorkStore


class Phase9ReplayError(RuntimeError):
    """A deterministic Phase-9 replay invariant failed."""


class RealCapabilityEvidenceError(ValueError):
    """Real external capability evidence is incomplete, stale or malformed."""


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

    def payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.payload() for item in self.cases],
        }


@dataclass
class _Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


@dataclass(frozen=True, slots=True)
class _StaticAdapter:
    source_kind: object
    candidates: tuple[AcquisitionCandidateV1, ...]

    def discover(self, goal, context):
        del goal, context
        return self.candidates


def _case(
    case_id: str,
    operation: Callable[[], dict[str, object]],
) -> Phase9ReplayCase:
    try:
        return Phase9ReplayCase(case_id, True, operation())
    except (
        AssertionError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        return Phase9ReplayCase(
            case_id,
            False,
            {
                "error_type": type(exc).__name__,
                "reason": str(exc),
            },
        )


def _goal(*operations: str) -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire TV control capability",
        requested_capability="TV control",
        required_operations=operations or ("power", "volume"),
        target_hints=("living-room",),
        source_session_id="phase9-replay-session",
        source_turn_id="phase9-replay-turn",
        now_epoch=100.0,
    )


def _descriptor(*, enabled: bool = True) -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="local",
        kind=CapabilityKind.NATIVE_API,
        name="TV control",
        description="Replay TV control capability.",
        operations=("power", "volume"),
        execution_enabled=enabled,
    )


def _empty_context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _core_context() -> AcquisitionContextV1:
    descriptor = _descriptor()
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


def _managed_context() -> AcquisitionContextV1:
    descriptor = _descriptor(enabled=False)
    state = EffectiveCapabilityState(
        capability_id=descriptor.capability_id,
        capability_key=descriptor.key,
        component_id="capability.package:tv.control",
        management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        registry_generation=3,
        applied_generation=3,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="tv.control.package",
        selected_package_version="1.2.0",
        selected_package_digest="a" * 64,
        package_disposition=PackageDisposition.AVAILABLE,
        compatibility_verdict=CompatibilityVerdict.READY,
        compatibility_digest="b" * 64,
        health_state=HealthState.DISABLED,
        transition_fenced=False,
        effective_enabled=False,
        reason_codes=("desired_disabled",),
    )
    snapshot = CapabilityEffectiveSnapshot(
        release_sha="c" * 40,
        states=(state,),
        reconciled_at_epoch=100.0,
        trigger="phase9-replay",
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
        effective_snapshot=snapshot,
    )


def _candidate(
    *,
    source_identity: str = "mcp:tv",
    trust: AcquisitionTrustClass = AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
    strategy: AcquisitionStrategy = AcquisitionStrategy.WRAP,
) -> AcquisitionCandidateV1:
    return AcquisitionCandidateV1.create(
        source_kind=(
            McpCapabilitySourceAdapter.source_kind
            if strategy is AcquisitionStrategy.WRAP
            else OpenApiCapabilitySourceAdapter.source_kind
        ),
        source_identity=source_identity,
        source_version="1.0.0",
        source_digest="d" * 64,
        trust_class=trust,
        supported_operations=("power", "volume"),
        strategy=strategy,
        evidence_refs=("phase9-replay:evidence",),
        verification_requirements=("phase9-replay-contract",),
    )


def _plan() -> CapabilityAcquisitionPlanV1:
    goal = _goal()
    candidate = _candidate()
    evaluation = AcquisitionCandidateEvaluationV1.create(
        candidate,
        requested_operations=goal.required_operations,
        evidence_complete=True,
        trust_allowed=True,
        requirements_compatible=True,
    )
    return CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id="tv.control",
        proposed_package_id="tv.control.package",
        proposed_package_version="1.0.0",
        rollback_summary="Disable the package and restore the prior release.",
        changed_paths=("src/jarvis/tv_control.py",),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("tv.verify.v1",),
        development_test_targets=("tests/test_tv_control.py",),
        evidence_refs=("phase9-replay:evidence",),
    )


def _phase9_store(
    root: pathlib.Path,
) -> tuple[ChangeStore, ChangeCoordinator, _Backend]:
    store = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend([])
    return store, ChangeCoordinator(store, backend), backend


def _started_phase9(root: pathlib.Path):
    store, coordinator, backend = _phase9_store(root)
    change = coordinator.start(
        "Acquire TV control",
        "phase9-replay-session",
        "phase9-replay-turn",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
    )
    stage = store.list_stages(change.change_id)[0]
    return store, coordinator, backend, change, stage


def _set_change_state(store: ChangeStore, change_id: str, state: ChangeState) -> None:
    with store.work._lock, store.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=?, version=version+1 "
            "WHERE change_id=?",
            (state.value, change_id),
        )


def _generic_gate_store(root: pathlib.Path):
    store = ChangeStore(SQLiteWorkStore(root / "work.sqlite3"))
    change = store.create(
        request="Replay architecture gate",
        process_key="engineering.change",
        process_version=1,
        source_session_id="phase9-gate",
        source_turn_id="phase9-gate-turn",
    )
    artifact = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "schema": "phase9-replay-architecture.v1",
            "plan_digest": "a" * 64,
        },
    )
    _set_change_state(store, change.change_id, ChangeState.ARCHITECTURE_READY)
    gates = GateService(store, verify_owner=lambda *_args: True)
    return store, change, artifact, gates


def _find_case(report, case_id: str):
    return next(item for item in report.cases if item.case_id == case_id)


def _01_existing_capability() -> dict[str, object]:
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((ExistingCapabilitySourceAdapter(),))
    )
    result = resolver.resolve(_goal(), _core_context())
    selected = result.selected_candidate
    if selected is None or selected.strategy is not AcquisitionStrategy.REUSE:
        raise Phase9ReplayError("existing capability did not resolve to reuse")
    return {
        "strategy": selected.strategy.value,
        "candidate_count": len(result.candidates),
        "build_required": False,
    }


def _02_disabled_package_lifecycle() -> dict[str, object]:
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((ExistingCapabilitySourceAdapter(),))
    )
    result = resolver.resolve(_goal(), _managed_context())
    selected = result.selected_candidate
    if selected is None:
        raise Phase9ReplayError("compatible disabled package was not selected")
    evaluation = result.evaluation(selected.candidate_id)
    if "existing_package_lifecycle_reuse" not in evaluation.reason_codes:
        raise Phase9ReplayError("disabled package did not route to lifecycle reuse")
    return {
        "strategy": selected.strategy.value,
        "reason_codes": evaluation.reason_codes,
        "build_required": False,
    }


def _03_duplicate_dedup() -> dict[str, object]:
    candidate = _candidate()
    adapter = _StaticAdapter(
        source_kind=McpCapabilitySourceAdapter.source_kind,
        candidates=(candidate, candidate),
    )
    result = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((adapter,))
    ).resolve(_goal(), _empty_context())
    if len(result.candidates) != 1:
        raise Phase9ReplayError("exact duplicate candidates were not deduplicated")
    return {
        "candidate_count": len(result.candidates),
        "candidate_id": result.candidates[0].candidate_id,
    }


def _04_stronger_evidence_wins() -> dict[str, object]:
    owner = owner_configured_evidence(
        source_identity="home-assistant:tv",
        source_version="1",
        source_digest="1" * 64,
        supported_operations=("power", "volume"),
        evidence_refs=("owner-config:tv",),
        verification_requirements=("owner-config-contract",),
    )
    mcp = mcp_server_evidence(
        server_identity="https://tv.example/mcp",
        server_version="1",
        tools=(
            {"name": "power", "inputSchema": {"type": "object"}},
            {"name": "volume", "inputSchema": {"type": "object"}},
        ),
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:mcp",),
    )
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(
            (
                OwnerConfiguredCapabilitySourceAdapter((owner,)),
                McpCapabilitySourceAdapter((mcp,)),
            )
        )
    )
    selected = resolver.resolve(_goal(), _empty_context()).selected_candidate
    if (
        selected is None
        or selected.trust_class is not AcquisitionTrustClass.OWNER_CONFIGURED
    ):
        raise Phase9ReplayError("stronger same-strategy evidence did not win")
    return {
        "selected_source": selected.source_kind.value,
        "trust_class": selected.trust_class.value,
    }


def _05_wrap_preference() -> dict[str, object]:
    mcp = mcp_server_evidence(
        server_identity="https://tv.example/mcp",
        tools=(
            {"name": "power", "inputSchema": {"type": "object"}},
            {"name": "volume", "inputSchema": {"type": "object"}},
        ),
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:mcp",),
    )
    openapi = openapi_contract_evidence(
        source_identity="https://tv.example/openapi.json",
        document={
            "openapi": "3.1.0",
            "paths": {
                "/power": {"post": {"operationId": "power"}},
                "/volume": {"post": {"operationId": "volume"}},
            },
        },
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:openapi",),
    )
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(
            (
                McpCapabilitySourceAdapter((mcp,)),
                OpenApiCapabilitySourceAdapter((openapi,)),
                CustomBuildCapabilitySourceAdapter(),
            )
        )
    )
    selected = resolver.resolve(_goal(), _empty_context()).selected_candidate
    if selected is None or selected.strategy is not AcquisitionStrategy.WRAP:
        raise Phase9ReplayError("wrap did not beat generated/custom strategy")
    return {"selected_strategy": selected.strategy.value}


def _06_unverified_blocked() -> dict[str, object]:
    mcp = mcp_server_evidence(
        server_identity="https://unknown.example/mcp",
        tools=({"name": "power", "inputSchema": {"type": "object"}},),
        trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        evidence_refs=("registry:unverified",),
    )
    result = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((McpCapabilitySourceAdapter((mcp,)),))
    ).resolve(_goal("power"), _empty_context())
    if result.selected_candidate is not None:
        raise Phase9ReplayError("unverified source was auto-selected")
    return {
        "selected_candidate_id": None,
        "reason_codes": result.evaluations[0].reason_codes,
    }


def _07_no_safe_route() -> dict[str, object]:
    result = CapabilityAcquisitionResolver(CapabilitySourceRegistry()).resolve(
        _goal("power"),
        _empty_context(),
    )
    if result.candidates or result.selected_candidate_id is not None:
        raise Phase9ReplayError("empty source set did not produce no-safe-route")
    return {"candidate_count": 0, "selected_candidate_id": None}


def _08_stale_candidate_invalidates_plan() -> dict[str, object]:
    plan = _plan()
    try:
        replace(plan, candidate_digest="0" * 64)
    except ValueError:
        return {"stale_candidate_rejected": True, "plan_digest": plan.digest}
    raise Phase9ReplayError("tampered candidate digest did not invalidate plan")


def _09_restart_during_research(root: pathlib.Path) -> dict[str, object]:
    store, _, _, change, stage = _started_phase9(root)
    item = store.work.require(stage.work_id)
    waiting = item.transition(
        WorkState.WAITING_RESOURCE,
        status_detail="source provider pressure",
    )
    store.work.save(waiting, expected_version=item.version)

    restarted_store = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    restarted = restarted_store.require(change.change_id)
    restarted_stage = restarted_store.list_stages(change.change_id)[0]
    recovered = restarted_store.work.require(restarted_stage.work_id)
    if (
        restarted.change_id != change.change_id
        or restarted_stage.work_id != stage.work_id
        or recovered.state is not WorkState.WAITING_RESOURCE
    ):
        raise Phase9ReplayError("restart changed acquisition research lineage")
    return {
        "change_id": restarted.change_id,
        "work_id": recovered.work_id,
        "state": recovered.state.value,
    }


def _10_resource_pressure(root: pathlib.Path) -> dict[str, object]:
    store, _, _, _, stage = _started_phase9(root)
    delivery = EngineeringSubstrateChangeService(store).block_work_resource(
        stage.work_id,
        component="mcp_registry",
        reason_code="provider_pressure",
        message="Phase-9 replay source provider unavailable",
    )
    work = store.work.require(stage.work_id)
    if work.state is not WorkState.WAITING_RESOURCE:
        raise Phase9ReplayError("resource pressure did not enter WAITING_RESOURCE")
    return {
        "state": work.state.value,
        "delivery_kind": delivery.kind.value,
    }


def _11_owner_input_wait(root: pathlib.Path) -> dict[str, object]:
    store, _, _, _, stage = _started_phase9(root)
    item = store.work.require(stage.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    waiting = store.work.save(
        running.transition(
            WorkState.WAITING_FOR_OWNER,
            status_detail="pairing PIN required",
        ),
        expected_version=running.version,
    )
    if waiting.state is not WorkState.WAITING_FOR_OWNER:
        raise Phase9ReplayError("missing owner input did not preserve waiting state")
    return {"state": waiting.state.value, "work_id": waiting.work_id}


def _12_exact_plan_gate(root: pathlib.Path) -> dict[str, object]:
    _, _, artifact, gates = _generic_gate_store(root)
    challenge = gates.present(
        artifact.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    decision = gates.decide(
        challenge.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="phase9-replay",
        source_turn_id="approve",
        request_key="phase9-replay:approve",
    )
    if not decision.approved or decision.challenge.artifact_digest != artifact.digest:
        raise Phase9ReplayError("architecture gate did not bind exact artifact digest")
    return {
        "plan_digest": artifact.payload["plan_digest"],
        "architecture_digest": artifact.digest,
        "approved": decision.approved,
    }


def _13_revised_architecture_invalidates(root: pathlib.Path) -> dict[str, object]:
    store, change, artifact, gates = _generic_gate_store(root)
    challenge = gates.present(
        change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "schema": "phase9-replay-architecture.v1",
            "plan_digest": "b" * 64,
        },
    )
    try:
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest=artifact.digest,
            actor_id="owner",
            source_session_id="phase9-replay",
            source_turn_id="stale-approve",
            request_key="phase9-replay:stale-approve",
        )
    except ChangeConflict:
        return {"stale_approval_rejected": True}
    raise Phase9ReplayError("superseded architecture approval was accepted")


def _14_development_before_approval(root: pathlib.Path) -> dict[str, object]:
    store, coordinator, _, change, _ = _started_phase9(root)
    try:
        coordinator.submit_stage(change.change_id, "development", 1)
    except ChangeConflict:
        if any(
            stage.stage_key == "development"
            for stage in store.list_stages(change.change_id)
        ):
            raise Phase9ReplayError("blocked DEVELOPMENT still created a stage")
        return {"development_admitted": False}
    raise Phase9ReplayError("DEVELOPMENT started without architecture approval")


def _15_dependency_provenance_required(root: pathlib.Path) -> dict[str, object]:
    store = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = store.create(
        request="Acquire dependency-backed capability",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="phase9-replay",
        source_turn_id="dependency",
    )
    architecture = ChangeArtifact(
        artifact_id="artifact_phase9_dependency",
        change_id=change.change_id,
        kind="architecture",
        revision=1,
        digest="e" * 64,
        payload={
            "dependency_refs": ["vendor-sdk==1.0.0"],
            "secret_scopes": [],
            "discovery_scopes": [],
        },
        created_at="2026-09-27T00:00:00+00:00",
    )
    try:
        ensure_capability_substrate_requirements_current(
            store,
            change.change_id,
            architecture,
        )
    except CapabilityCandidateError as exc:
        if exc.reason_code != "substrate_manifest_missing":
            raise
        return {"blocked": True, "reason_code": exc.reason_code}
    raise Phase9ReplayError("dependency candidate passed without Phase-5 evidence")


def _16_plaintext_secret_rejected() -> dict[str, object]:
    try:
        AcquisitionCandidateV1.create(
            source_kind=McpCapabilitySourceAdapter.source_kind,
            source_identity="mcp:tv",
            source_digest="f" * 64,
            trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
            supported_operations=("power",),
            strategy=AcquisitionStrategy.WRAP,
            evidence_refs=("vendor:mcp",),
            verification_requirements=("mcp-contract",),
            secret_value="plaintext-secret",
        )
    except TypeError:
        return {"plaintext_secret_field_accepted": False}
    raise Phase9ReplayError("candidate accepted plaintext secret material")


def _17_metadata_inert() -> dict[str, object]:
    evidence = openapi_contract_evidence(
        source_identity="https://tv.example/openapi.json",
        document={
            "openapi": "3.1.0",
            "x-command": "rm -rf /",
            "x-import": "evil.module",
            "x-executable": "evil.exe",
            "paths": {"/power": {"post": {"operationId": "power"}}},
        },
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:openapi",),
    )
    candidate = OpenApiCapabilitySourceAdapter((evidence,)).discover(
        _goal("power"),
        _empty_context(),
    )[0]
    forbidden = {"command", "argv", "import_path", "executable_path"}
    payload = candidate.canonical_payload()
    if forbidden & set(payload):
        raise Phase9ReplayError("external metadata entered executable candidate fields")
    return {"forbidden_fields_present": sorted(forbidden & set(payload))}


def _18_protected_surface() -> dict[str, object]:
    assessment = RepairProtectedSurfacePolicy().assess(
        ("src/jarvis/capability_acquisition/verification.py",)
    )
    if assessment.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase9ReplayError("Phase-9 governance path was not protected")
    return {
        "verdict": assessment.verdict.value,
        "category": assessment.protected[0].category,
    }


def _19_no_auto_enable(phase8) -> dict[str, object]:
    case = _find_case(phase8, "11_registration_does_not_enable")
    if not case.passed:
        raise Phase9ReplayError("Phase-8 registration no-enable replay failed")
    return {
        "phase8_suite_digest": phase8.suite_digest,
        "phase8_case": case.case_id,
        "evidence": case.evidence,
    }


def _20_compatibility_unavailable(phase8) -> dict[str, object]:
    cases = (
        _find_case(phase8, "09_runtime_api_mismatch_blocked"),
        _find_case(phase8, "12_enable_requires_ready"),
    )
    if any(not case.passed for case in cases):
        raise Phase9ReplayError("Phase-8 compatibility fail-closed replay failed")
    return {
        "phase8_suite_digest": phase8.suite_digest,
        "phase8_cases": [case.case_id for case in cases],
    }


def _21_phase7_only_protected_main(phase7) -> dict[str, object]:
    cases = (
        _find_case(phase7, "03_moved_pr_head_rejected"),
        _find_case(phase7, "04_wrong_ci_app_rejected"),
        _find_case(phase7, "06_exact_authorized_merge"),
    )
    if any(not case.passed for case in cases):
        raise Phase9ReplayError("Phase-7 protected-main replay failed")
    return {
        "phase7_suite_digest": phase7.suite_digest,
        "phase7_cases": [case.case_id for case in cases],
    }


def _22_rollback_disable(phase7, phase8) -> dict[str, object]:
    cases = (
        _find_case(phase7, "10_candidate_failure_rolls_back_lkg"),
        _find_case(phase8, "15_disable_removes_routing"),
        _find_case(phase8, "19_supported_rollback_succeeds"),
    )
    if any(not case.passed for case in cases):
        raise Phase9ReplayError("rollback/disable replay failed")
    return {
        "phase7_suite_digest": phase7.suite_digest,
        "phase8_suite_digest": phase8.suite_digest,
        "cases": [case.case_id for case in cases],
    }


_ALLOWED_OBSERVATION_METHODS = frozenset(
    {
        "owner_observed",
        "device_state_readback",
        "external_system_readback",
    }
)


def validate_real_capability_evidence(
    payload: object,
    *,
    tested_commit: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RealCapabilityEvidenceError("real capability evidence must be an object")
    commit = str(tested_commit).strip().casefold()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise RealCapabilityEvidenceError("tested_commit must be an exact Git SHA")
    required = (
        "change_id",
        "acquisition_work_id",
        "development_work_id",
        "goal_digest",
        "plan_digest",
        "architecture_digest",
        "candidate_digest",
        "capability_id",
        "package_id",
        "package_version",
        "package_digest",
        "promotion_attempt_id",
        "active_release_sha",
        "lifecycle_evidence_ref",
        "operation",
        "target",
        "observed_effect",
        "observation_method",
        "production_observation_ref",
        "rollback_disable_evidence_ref",
        "recorded_at",
    )
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    if body.get("schema") != "phase9_real_capability_evidence.v1":
        raise RealCapabilityEvidenceError("real capability evidence schema mismatch")
    if body.get("tested_commit") != commit:
        raise RealCapabilityEvidenceError(
            "real capability evidence is not bound to tested commit"
        )
    for field in required:
        if not str(body.get(field) or "").strip():
            raise RealCapabilityEvidenceError(
                f"real capability evidence requires {field}"
            )
    for field in (
        "goal_digest",
        "plan_digest",
        "architecture_digest",
        "candidate_digest",
        "package_digest",
    ):
        value = str(body[field]).strip().casefold()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise RealCapabilityEvidenceError(f"{field} must be SHA-256")
    active_sha = str(body["active_release_sha"]).strip().casefold()
    if len(active_sha) != 40 or any(
        char not in "0123456789abcdef" for char in active_sha
    ):
        raise RealCapabilityEvidenceError("active_release_sha must be exact Git SHA")
    if active_sha != commit:
        raise RealCapabilityEvidenceError(
            "real capability evidence active release differs from tested commit"
        )
    if body.get("owner_confirmed") is not True:
        raise RealCapabilityEvidenceError(
            "real external capability requires explicit owner confirmation"
        )
    if body.get("production_observed") is not True:
        raise RealCapabilityEvidenceError(
            "real capability evidence requires production observation"
        )
    if body.get("rollback_disable_verified") is not True:
        raise RealCapabilityEvidenceError(
            "real capability evidence requires rollback/disable verification"
        )
    method = str(body["observation_method"]).strip().casefold()
    if method not in _ALLOWED_OBSERVATION_METHODS:
        raise RealCapabilityEvidenceError("unsupported real observation method")
    digest = canonical_digest(body)
    if payload.get("evidence_digest") != digest:
        raise RealCapabilityEvidenceError("real capability evidence digest mismatch")
    return {**body, "evidence_digest": digest}


def build_real_capability_evidence(**fields: object) -> dict[str, object]:
    body = {
        "schema": "phase9_real_capability_evidence.v1",
        **fields,
    }
    body["evidence_digest"] = canonical_digest(body)
    return body


def _23_real_external_required() -> dict[str, object]:
    try:
        validate_real_capability_evidence(
            {
                "schema": "phase9_real_capability_evidence.v1",
                "tested_commit": "a" * 40,
                "owner_confirmed": False,
            },
            tested_commit="a" * 40,
        )
    except RealCapabilityEvidenceError:
        return {"synthetic_or_unconfirmed_effect_rejected": True}
    raise Phase9ReplayError("real external effect could be self-approved")


def _24_cold_restart_identity(root: pathlib.Path) -> dict[str, object]:
    store, _, _, change, stage = _started_phase9(root)
    item = store.work.require(stage.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    waiting = store.work.save(
        running.transition(
            WorkState.WAITING_FOR_OWNER,
            status_detail="owner pairing required",
        ),
        expected_version=running.version,
    )
    reopened = ChangeStore(
        SQLiteWorkStore(root / "work.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    recovered_change = reopened.require(change.change_id)
    recovered_stage = reopened.list_stages(change.change_id)[0]
    recovered_work = reopened.work.require(recovered_stage.work_id)
    if (
        recovered_change.change_id != change.change_id
        or recovered_stage.work_id != stage.work_id
        or recovered_work.work_id != waiting.work_id
        or recovered_work.version != waiting.version
        or recovered_work.state is not WorkState.WAITING_FOR_OWNER
    ):
        raise Phase9ReplayError("cold restart changed canonical acquisition identity")
    return {
        "change_id": recovered_change.change_id,
        "work_id": recovered_work.work_id,
        "state": recovered_work.state.value,
        "version": recovered_work.version,
    }


def run_replay_suite(root: pathlib.Path) -> Phase9ReplayReport:
    replay_root = pathlib.Path(root).resolve()
    replay_root.mkdir(parents=True, exist_ok=True)

    phase7 = run_phase7_replay(replay_root / "phase7")
    phase8 = run_phase8_replay(replay_root / "phase8")
    if phase7.status != "PASS":
        raise Phase9ReplayError("inherited Phase-7 replay is not green")
    if phase8.status != "PASS":
        raise Phase9ReplayError("inherited Phase-8 replay is not green")

    operations: tuple[
        tuple[str, Callable[[], dict[str, object]]],
        ...,
    ] = (
        ("01_existing_capability_no_build", _01_existing_capability),
        ("02_disabled_package_lifecycle_reuse", _02_disabled_package_lifecycle),
        ("03_duplicate_candidates_deduplicate", _03_duplicate_dedup),
        ("04_stronger_verified_evidence_wins", _04_stronger_evidence_wins),
        ("05_wrap_beats_generate_custom", _05_wrap_preference),
        ("06_unverified_source_not_selected", _06_unverified_blocked),
        ("07_no_candidate_no_safe_route", _07_no_safe_route),
        ("08_stale_candidate_invalidates_plan", _08_stale_candidate_invalidates_plan),
        (
            "09_restart_during_acquisition_research",
            lambda: _09_restart_during_research(replay_root / "09"),
        ),
        (
            "10_provider_pressure_waiting_resource",
            lambda: _10_resource_pressure(replay_root / "10"),
        ),
        (
            "11_owner_pairing_waiting_for_owner",
            lambda: _11_owner_input_wait(replay_root / "11"),
        ),
        (
            "12_architecture_approval_exact_plan_digest",
            lambda: _12_exact_plan_gate(replay_root / "12"),
        ),
        (
            "13_architecture_revision_invalidates_approval",
            lambda: _13_revised_architecture_invalidates(replay_root / "13"),
        ),
        (
            "14_development_blocked_before_approval",
            lambda: _14_development_before_approval(replay_root / "14"),
        ),
        (
            "15_dependency_provenance_failure_blocks",
            lambda: _15_dependency_provenance_required(replay_root / "15"),
        ),
        ("16_plaintext_secret_injection_rejected", _16_plaintext_secret_rejected),
        ("17_external_metadata_cannot_execute", _17_metadata_inert),
        ("18_protected_surface_fails_closed", _18_protected_surface),
        ("19_package_registration_no_auto_enable", lambda: _19_no_auto_enable(phase8)),
        (
            "20_package_compatibility_failure_unavailable",
            lambda: _20_compatibility_unavailable(phase8),
        ),
        (
            "21_protected_main_only_phase7",
            lambda: _21_phase7_only_protected_main(phase7),
        ),
        (
            "22_rollback_disable_restores_safe_state",
            lambda: _22_rollback_disable(phase7, phase8),
        ),
        ("23_real_external_owner_evidence_required", _23_real_external_required),
        (
            "24_cold_restart_preserves_identity",
            lambda: _24_cold_restart_identity(replay_root / "24"),
        ),
    )
    cases = tuple(_case(case_id, operation) for case_id, operation in operations)
    status = "PASS" if all(item.passed for item in cases) else "FAIL"
    payload = {
        "status": status,
        "phase7_suite_digest": phase7.suite_digest,
        "phase8_suite_digest": phase8.suite_digest,
        "cases": [item.payload() for item in cases],
    }
    return Phase9ReplayReport(
        cases=cases,
        status=status,
        suite_digest=canonical_digest(payload),
    )
