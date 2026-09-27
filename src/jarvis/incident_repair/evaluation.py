"""Deterministic Phase-6 replay evaluation.

The replay suite is portable CI evidence. It deliberately does not claim Windows,
Docker, owner-presence, or promotion acceptance; those are proven by the separate
owner-machine acceptance harness.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.architecture import (
    IncidentRepairDevelopmentRevisionResolver,
    IncidentRepairSourceCompletionHandler,
)
from jarvis.incident_repair.coordinator import (
    IncidentRepairAdmissionBlocked,
    IncidentRepairCoordinator,
)
from jarvis.incident_repair.diagnostics import (
    DiagnosticContextResolver,
    DiagnosticRetrieveKnowledgeExecutor,
)
from jarvis.incident_repair.evidence import IncidentEvidencePackager
from jarvis.incident_repair.models import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    IncidentRepairTrigger,
    ProtectedSurfaceVerdict,
    ReproductionState,
)
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.incident_repair.verification import (
    IncidentRepairDevelopmentCompletionHandler,
    SourceRepairCandidateError,
    SourceRepairCandidateVerifier,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.incidents.models import EvidenceReference
from jarvis.model_routing.strategy import derive_work_step_signals
from jarvis.self_model.health import HealthState
from jarvis.self_repair.domain import (
    RepairActionKind,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
)
from jarvis.self_repair.registry import RepairRegistry
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class Phase6EvaluationError(RuntimeError):
    """A deterministic Phase-6 replay invariant failed."""


@dataclass(frozen=True, slots=True)
class Phase6ReplayCase:
    case_id: str
    passed: bool
    evidence: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Phase6ReplayReport:
    status: str
    cases: tuple[Phase6ReplayCase, ...]
    suite_digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.to_payload() for item in self.cases],
            "suite_digest": self.suite_digest,
        }


class _Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


class _KnowledgeReader:
    def read_revision(self, revision_id: str) -> dict[str, object] | None:
        if revision_id != "knowledge-r1":
            return None
        return {
            "revision_id": revision_id,
            "title": "Accepted diagnostic note",
            "execution_authority": False,
        }


def _git(root: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:
        raise Phase6EvaluationError("Git executable is unavailable")
    try:
        return subprocess.run(
            [git, *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30.0,
            check=check,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise Phase6EvaluationError(str(exc)) from exc


def _new_repo(root: pathlib.Path) -> tuple[pathlib.Path, str]:
    repo = (root / "repo").resolve()
    repo.mkdir(parents=True, exist_ok=False)
    _git(repo, "init")
    _git(repo, "config", "user.email", "jarvis-phase6@example.invalid")
    _git(repo, "config", "user.name", "JARVIS Phase6 Replay")
    source = repo / "src" / "jarvis" / "demo"
    source.mkdir(parents=True)
    (source / "logic.py").write_text("VALUE = 1\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_demo_logic.py").write_text(
        "from src.jarvis.demo.logic import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "phase6 incident revision")
    revision = _git(repo, "rev-parse", "HEAD").stdout.strip().casefold()
    if len(revision) != 40:
        raise Phase6EvaluationError("fixture Git revision is not SHA-1")
    return repo, revision


def _completed_step(
    work_id: str,
    kind: str,
    *,
    input_data: dict[str, object] | None = None,
    observation: dict[str, object] | None = None,
) -> WorkStep:
    return (
        WorkStep(
            work_id=work_id,
            kind=kind,
            summary=kind,
            input_data=input_data or {},
        )
        .start()
        .complete(observation or {})
    )


def _case(case_id: str, callback: Callable[[], dict[str, object]]) -> Phase6ReplayCase:
    try:
        evidence = callback()
    except Exception as exc:  # noqa: BLE001 - replay must report exact failed case
        return Phase6ReplayCase(
            case_id=case_id,
            passed=False,
            evidence={
                "error_type": type(exc).__name__,
                "reason": str(exc),
            },
        )
    return Phase6ReplayCase(case_id=case_id, passed=True, evidence=evidence)


def _base_incident(
    root: pathlib.Path,
    *,
    revision: str,
    summary: str = "deterministic source failure",
) -> tuple[IncidentService, EvidenceReference, IncidentRepairTrigger]:
    root.mkdir(parents=True, exist_ok=True)
    incidents = IncidentService(SqliteIncidentStore(root / "incidents.sqlite3"))
    incident = incidents.create_manual(
        title="Phase6 controlled incident",
        symptom=summary,
        affected_components=("runtime.demo",),
        now_epoch=100.0,
    )
    evidence = EvidenceReference.create(
        kind="test_failure",
        reference="pytest:tests/test_demo_logic.py::test_value",
        summary=summary,
        component_id="runtime.demo",
        occurred_at_epoch=100.0,
    )
    incident = incidents.add_evidence(
        incident.incident_id,
        evidence,
        now_epoch=101.0,
    )
    trigger = IncidentRepairTrigger.create(
        incident_id=incident.incident_id,
        source_revision=revision,
        component_ids=("runtime.demo",),
        evidence_ids=(evidence.evidence_id,),
        reason_code="unknown_failure",
        now_epoch=102.0,
    )
    return incidents, evidence, trigger


def _change_stack(
    root: pathlib.Path,
    repository_root: pathlib.Path,
) -> tuple[
    SQLiteWorkStore,
    ChangeStore,
    ChangeCoordinator,
    DevelopmentWorkspaceManager,
    GateService,
]:
    work = SQLiteWorkStore(root / "work.sqlite3")
    changes = ChangeStore(work, processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,))
    backend = _Backend()
    manager = DevelopmentWorkspaceManager(
        repository_root=repository_root,
        workspace_root=root / "worktrees",
        base_revision_resolver=IncidentRepairDevelopmentRevisionResolver(changes),
    )
    coordinator = ChangeCoordinator(
        changes,
        backend,
        source_completion_handlers=(IncidentRepairSourceCompletionHandler(changes),),
        development_completion_handlers=(
            IncidentRepairDevelopmentCompletionHandler(changes, manager),
        ),
    )
    gates = GateService(changes, verify_owner=lambda *_: True)
    return work, changes, coordinator, manager, gates


def _admit(
    root: pathlib.Path,
    repository_root: pathlib.Path,
    revision: str,
    *,
    knowledge: object | None = None,
    repair_registry: RepairRegistry | None = None,
) -> tuple[
    SQLiteWorkStore,
    ChangeStore,
    ChangeCoordinator,
    DevelopmentWorkspaceManager,
    GateService,
    IncidentRepairCoordinator,
    object,
]:
    work, changes, coordinator, manager, gates = _change_stack(root, repository_root)
    incidents, _, trigger = _base_incident(root, revision=revision)
    admission = IncidentRepairCoordinator(
        incidents=incidents,
        changes=coordinator,
        knowledge=knowledge,
        repair_registry=repair_registry,
    )
    admitted = admission.admit(trigger)
    return work, changes, coordinator, manager, gates, admission, admitted


def _complete_diagnosis(
    *,
    work: SQLiteWorkStore,
    changes: ChangeStore,
    coordinator: ChangeCoordinator,
    change_id: str,
    diagnostics_work_id: str,
    source_revision: str,
    disposition: DiagnosisDisposition,
    supported: bool,
) -> IncidentDiagnosis:
    evidence_artifact = changes.latest_artifact(change_id, "incident_evidence")
    if evidence_artifact is None:
        raise Phase6EvaluationError("incident evidence artifact missing")
    raw_evidence = evidence_artifact.payload.get("evidence")
    evidence_ids = tuple(
        str(item.get("evidence_id"))
        for item in raw_evidence
        if isinstance(item, dict) and item.get("evidence_id")
    ) if isinstance(raw_evidence, list) else ()
    if not evidence_ids:
        raise Phase6EvaluationError("controlled incident has no admitted evidence")

    hypothesis = DiagnosticHypothesis.create(
        statement="fixture source value causes deterministic failure",
        affected_components=("runtime.demo",),
        affected_paths=("src/jarvis/demo/logic.py",),
        supporting_evidence_ids=evidence_ids if supported else (),
        status=(
            HypothesisState.SUPPORTED if supported else HypothesisState.INCONCLUSIVE
        ),
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id=str(evidence_artifact.payload["incident_id"]),
        change_id=change_id,
        work_id=diagnostics_work_id,
        source_revision=source_revision,
        evidence_ids=evidence_ids,
        reproduction_state=(
            ReproductionState.REPRODUCED
            if supported
            else ReproductionState.INCONCLUSIVE
        ),
        hypotheses=(hypothesis,),
        selected_hypothesis_id=hypothesis.hypothesis_id if supported else None,
        affected_paths=("src/jarvis/demo/logic.py",) if supported else (),
        affected_components=("runtime.demo",) if supported else (),
        proposed_repair_scope="set fixture value to 2" if supported else None,
        verification_targets=("tests/test_demo_logic.py",) if supported else (),
        reason_codes=(
            ("reproduced", "supported_hypothesis")
            if supported
            else ("reproduction_impossible",)
        ),
        disposition=disposition,
        now_epoch=103.0,
    )
    diagnosis_payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    artifact = changes.add_artifact(
        change_id,
        kind="diagnosis",
        payload={
            "diagnosis": diagnosis_payload,
            "suspicious_locations": [],
            "reproduction_impossible_reason": (
                None if supported else "controlled non-reproducible fixture"
            ),
        },
    )
    item = work.require(diagnostics_work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "diagnosis": diagnosis_payload,
            "diagnosis_artifact_id": artifact.artifact_id,
            "diagnosis_artifact_digest": artifact.digest,
            "suspicious_locations": [],
        },
    )
    work.save(completed, expected_version=running.version)
    coordinator.reconcile_for_work(diagnostics_work_id)
    return diagnosis


def _approve_architecture(
    *,
    changes: ChangeStore,
    coordinator: ChangeCoordinator,
    gates: GateService,
    change_id: str,
) -> WorkItem:
    architecture = changes.latest_artifact(change_id, "architecture")
    if architecture is None:
        raise Phase6EvaluationError("repair architecture was not derived")
    gate = gates.present(change_id, GateKind.ARCHITECTURE, architecture.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="phase6-replay-owner",
        source_session_id="phase6-replay",
        source_turn_id=f"approve:{change_id}",
        request_key=f"phase6-replay:{change_id}",
    )
    coordinator.reconcile(change_id)
    stage = next(
        (
            item
            for item in changes.list_stages(change_id)
            if item.stage_key == "development"
        ),
        None,
    )
    if stage is None:
        raise Phase6EvaluationError("approved architecture created no development work")
    return changes.work.require(stage.work_id)


def _complete_candidate(
    *,
    work: SQLiteWorkStore,
    changes: ChangeStore,
    coordinator: ChangeCoordinator,
    manager: DevelopmentWorkspaceManager,
    change_id: str,
    development_work: WorkItem,
) -> dict[str, object]:
    workspace = manager.ensure(development_work.work_id)
    source = workspace.path / "src" / "jarvis" / "demo" / "logic.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    work.add_step(
        _completed_step(
            development_work.work_id,
            "dev_write_file",
            input_data={"path": "src/jarvis/demo/logic.py"},
            observation={
                "path": "src/jarvis/demo/logic.py",
                "production_tree_modified": False,
            },
        )
    )
    work.add_step(
        _completed_step(
            development_work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_demo_logic.py"]},
            observation={
                "passed": True,
                "returncode": 0,
                "sandbox": "docker",
                "network": "disabled",
                "workspace": "read_only",
                "sandbox_profile": "test.offline.v1",
                "sandbox_profile_version": 1,
            },
        )
    )
    work.add_step(
        _completed_step(
            development_work.work_id,
            "dev_diff",
            observation={
                "branch": workspace.branch,
                "diff": "bounded fixture diff",
            },
        )
    )

    _git(workspace.path, "add", "--all")
    _git(workspace.path, "commit", "-m", "repair controlled phase6 fixture")
    commit = _git(workspace.path, "rev-parse", "HEAD").stdout.strip().casefold()
    work.add_step(
        _completed_step(
            development_work.work_id,
            "dev_commit",
            observation={
                "committed": True,
                "commit": commit,
                "branch": workspace.branch,
                "clean": True,
                "pushed": False,
                "merged": False,
                "production_tree_modified": False,
            },
        )
    )

    current = work.require(development_work.work_id)
    if current.state is WorkState.QUEUED:
        current = work.save(
            current.transition(WorkState.RUNNING),
            expected_version=current.version,
        )
    completed = current.transition(
        WorkState.COMPLETED,
        result={
            "branch": workspace.branch,
            "commit": commit,
            "verification": {"passed": True, "sandbox": "docker"},
        },
    )
    work.save(completed, expected_version=current.version)
    coordinator.reconcile(change_id)

    candidate = changes.latest_artifact(change_id, "source_repair_candidate")
    if candidate is None:
        raise Phase6EvaluationError("candidate verification produced no artifact")
    return {
        "candidate_artifact_id": candidate.artifact_id,
        "candidate_artifact_digest": candidate.digest,
        "candidate": candidate.payload,
        "commit": commit,
        "branch": workspace.branch,
    }


def _full_candidate_fixture(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    main_before = _git(repository_root, "rev-parse", "HEAD").stdout.strip().casefold()
    status_before = _git(repository_root, "status", "--porcelain=v1").stdout

    (
        work,
        changes,
        coordinator,
        manager,
        gates,
        _,
        admitted,
    ) = _admit(root, repository_root, revision)
    diagnosis = _complete_diagnosis(
        work=work,
        changes=changes,
        coordinator=coordinator,
        change_id=admitted.change.change_id,
        diagnostics_work_id=admitted.diagnostics_work_id,
        source_revision=revision,
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        supported=True,
    )
    development = _approve_architecture(
        changes=changes,
        coordinator=coordinator,
        gates=gates,
        change_id=admitted.change.change_id,
    )
    result = _complete_candidate(
        work=work,
        changes=changes,
        coordinator=coordinator,
        manager=manager,
        change_id=admitted.change.change_id,
        development_work=development,
    )

    main_after = _git(repository_root, "rev-parse", "HEAD").stdout.strip().casefold()
    status_after = _git(repository_root, "status", "--porcelain=v1").stdout
    return {
        **result,
        "source_revision": revision,
        "diagnosis_id": diagnosis.diagnosis_id,
        "diagnosis_digest": diagnosis.digest,
        "change_id": admitted.change.change_id,
        "diagnostics_work_id": admitted.diagnostics_work_id,
        "development_work_id": development.work_id,
        "protected_main_unchanged": (
            main_before == main_after == revision
            and status_before == status_after == ""
        ),
    }


def _case_repaired(root: pathlib.Path) -> dict[str, object]:
    fixture = _full_candidate_fixture(root)
    candidate = fixture["candidate"]
    if not isinstance(candidate, dict):
        raise Phase6EvaluationError("candidate payload is malformed")
    if candidate.get("protected_surface_verdict") != ProtectedSurfaceVerdict.CLEAR.value:
        raise Phase6EvaluationError("controlled source repair was not CLEAR")
    return {
        "change_id": fixture["change_id"],
        "candidate_id": candidate["candidate_id"],
        "commit": fixture["commit"],
    }


def _case_inconclusive(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    work, changes, coordinator, _, _, _, admitted = _admit(
        root,
        repository_root,
        revision,
    )
    diagnosis = _complete_diagnosis(
        work=work,
        changes=changes,
        coordinator=coordinator,
        change_id=admitted.change.change_id,
        diagnostics_work_id=admitted.diagnostics_work_id,
        source_revision=revision,
        disposition=DiagnosisDisposition.INCONCLUSIVE,
        supported=False,
    )
    if changes.latest_artifact(admitted.change.change_id, "architecture") is not None:
        raise Phase6EvaluationError("inconclusive diagnosis created architecture")
    return {
        "disposition": diagnosis.disposition.value,
        "selected_hypothesis_id": diagnosis.selected_hypothesis_id,
        "change_state": changes.require(admitted.change.change_id).state.value,
    }


def _case_wrong_first_hypothesis() -> dict[str, object]:
    wrong = DiagnosticHypothesis.create(
        statement="provider quota caused local logic defect",
        refuting_evidence_ids=("e-refute",),
        status=HypothesisState.REFUTED,
    )
    supported = DiagnosticHypothesis.create(
        statement="fixture value caused local test failure",
        supporting_evidence_ids=("e-support",),
        status=HypothesisState.SUPPORTED,
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id="incident-replay",
        change_id="change-replay",
        work_id="work-replay",
        source_revision="a" * 40,
        evidence_ids=("e-refute", "e-support"),
        reproduction_state=ReproductionState.REPRODUCED,
        hypotheses=(wrong, supported),
        selected_hypothesis_id=supported.hypothesis_id,
        proposed_repair_scope="correct local fixture",
        verification_targets=("tests/test_demo.py",),
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=100.0,
    )
    return {
        "first_status": wrong.status.value,
        "selected_hypothesis_id": diagnosis.selected_hypothesis_id,
        "selected_status": supported.status.value,
    }


def _case_knowledge_advisory(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)

    class Knowledge:
        def retrieve_revision_ids(self, package, *, now_epoch):
            del package, now_epoch
            return ("knowledge-r1",)

    _, changes, _, _, _, _, admitted = _admit(
        root,
        repository_root,
        revision,
        knowledge=Knowledge(),
    )
    resolver = DiagnosticContextResolver(changes)
    executor = DiagnosticRetrieveKnowledgeExecutor(
        resolver,
        reader=_KnowledgeReader(),
    )
    result = asyncio.run(
        executor.execute(
            work=changes.work.require(admitted.diagnostics_work_id),
            parameters={},
        )
    )
    if result.get("advisory_only") is not True:
        raise Phase6EvaluationError("retrieved knowledge became executable")
    return {
        "revision_ids": result["revision_ids"],
        "advisory_only": result["advisory_only"],
    }


def _case_provider_pressure() -> dict[str, object]:
    work_id = "work-provider-replay"
    steps = (
        _completed_step(
            work_id,
            "provider_pressure",
            observation={"provider": "gemini", "status_code": 429},
        ),
        _completed_step(
            work_id,
            "diag_record_hypothesis",
            observation={"hypothesis": {"status": "refuted"}},
        ),
    )
    signals = derive_work_step_signals(steps)
    if signals.routing_features.get("provider_pressure_count") != 1:
        raise Phase6EvaluationError("provider pressure signal was not preserved")
    if "failed_hypothesis" not in signals.failure_signals:
        raise Phase6EvaluationError("capability failure signal was lost")
    return {
        "provider_pressure_count": signals.routing_features["provider_pressure_count"],
        "failure_signals": list(signals.failure_signals),
    }


def _case_restart_diagnostics(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    work, changes, _, _, _, _, admitted = _admit(root, repository_root, revision)
    work.add_step(
        _completed_step(
            admitted.diagnostics_work_id,
            "diag_record_hypothesis",
            observation={
                "hypothesis": {
                    "hypothesis_id": "hypothesis-replay",
                    "status": "proposed",
                }
            },
        )
    )
    reopened_work = SQLiteWorkStore(work.path)
    reopened_changes = ChangeStore(
        reopened_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    stage = reopened_changes.stage_for_work(admitted.diagnostics_work_id)
    steps = reopened_work.list_steps(admitted.diagnostics_work_id)
    if stage is None or stage.change_id != admitted.change.change_id:
        raise Phase6EvaluationError("diagnostic lineage changed after restart")
    return {
        "change_id": stage.change_id,
        "work_id": admitted.diagnostics_work_id,
        "step_count": len(steps),
    }


def _case_restart_after_approval(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    work, changes, coordinator, manager, gates, _, admitted = _admit(
        root,
        repository_root,
        revision,
    )
    _complete_diagnosis(
        work=work,
        changes=changes,
        coordinator=coordinator,
        change_id=admitted.change.change_id,
        diagnostics_work_id=admitted.diagnostics_work_id,
        source_revision=revision,
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        supported=True,
    )
    architecture = changes.latest_artifact(admitted.change.change_id, "architecture")
    if architecture is None:
        raise Phase6EvaluationError("architecture missing before restart")
    gate = gates.present(
        admitted.change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="phase6-replay-owner",
        source_session_id="phase6-replay",
        source_turn_id="approve-before-restart",
        request_key="phase6-replay:restart-approval",
    )

    reopened_work = SQLiteWorkStore(work.path)
    reopened_changes = ChangeStore(
        reopened_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    reopened_manager = DevelopmentWorkspaceManager(
        repository_root=repository_root,
        workspace_root=manager.workspace_root,
        base_revision_resolver=IncidentRepairDevelopmentRevisionResolver(
            reopened_changes
        ),
    )
    reopened = ChangeCoordinator(
        reopened_changes,
        _Backend(),
        source_completion_handlers=(
            IncidentRepairSourceCompletionHandler(reopened_changes),
        ),
        development_completion_handlers=(
            IncidentRepairDevelopmentCompletionHandler(
                reopened_changes,
                reopened_manager,
            ),
        ),
    )
    reopened.reconcile(admitted.change.change_id)
    development = [
        item
        for item in reopened_changes.list_stages(admitted.change.change_id)
        if item.stage_key == "development"
    ]
    if len(development) != 1:
        raise Phase6EvaluationError("restart did not create exactly one development stage")
    return {
        "development_work_id": development[0].work_id,
        "plan_artifact_id": development[0].plan_artifact_id,
    }


def _case_restart_during_development(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    work, changes, coordinator, _, gates, _, admitted = _admit(
        root,
        repository_root,
        revision,
    )
    _complete_diagnosis(
        work=work,
        changes=changes,
        coordinator=coordinator,
        change_id=admitted.change.change_id,
        diagnostics_work_id=admitted.diagnostics_work_id,
        source_revision=revision,
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        supported=True,
    )
    development = _approve_architecture(
        changes=changes,
        coordinator=coordinator,
        gates=gates,
        change_id=admitted.change.change_id,
    )
    running = work.save(
        development.transition(WorkState.RUNNING),
        expected_version=development.version,
    )
    reopened = SQLiteWorkStore(work.path)
    same = reopened.require(running.work_id)
    if same.state is not WorkState.RUNNING:
        raise Phase6EvaluationError("development state was not durable")
    return {
        "work_id": same.work_id,
        "state": same.state.value,
        "version": same.version,
    }


def _case_failed_candidate_tests() -> dict[str, object]:
    work = WorkItem(
        request="repair",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="change:replay",
        source_turn_id="development:1",
        result={"verification": {"passed": False}},
    )
    steps = (
        _completed_step(work.work_id, "dev_write_file"),
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_demo_logic.py"]},
            observation={"passed": False},
        ),
    )
    try:
        SourceRepairCandidateVerifier._verify_workstep_order(
            work,
            steps,
            ("tests/test_demo_logic.py",),
        )
    except SourceRepairCandidateError as exc:
        return {"reason_code": exc.reason_code}
    raise Phase6EvaluationError("failed candidate tests were accepted")


def _case_protected_surface() -> dict[str, object]:
    result = RepairProtectedSurfacePolicy().assess(
        ("src/jarvis/authority/service.py",)
    )
    if result.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase6EvaluationError("protected authority path was not blocked")
    return result.to_payload()


def _case_secret_evidence(root: pathlib.Path) -> dict[str, object]:
    incidents = IncidentService(SqliteIncidentStore(root / "incidents.sqlite3"))
    incident = incidents.create_manual(
        symptom="secret-bearing evidence test",
        affected_components=("runtime.demo",),
        now_epoch=100.0,
    )
    secret = "sk-" + ("a" * 32)
    evidence = EvidenceReference.create(
        kind="structured_log",
        reference=f"token={secret}",
        summary="credential leaked into diagnostic source",
        component_id="runtime.demo",
        occurred_at_epoch=100.0,
    )
    incident = incidents.add_evidence(
        incident.incident_id,
        evidence,
        now_epoch=101.0,
    )
    package = IncidentEvidencePackager().build(
        incident=incident,
        source_revision="a" * 40,
        trigger_digest="b" * 64,
        now_epoch=102.0,
    )
    included_ids = {item.evidence_id for item in package.evidence}
    excluded_ids = {item.evidence_id for item in package.excluded_evidence}
    if evidence.evidence_id in included_ids or evidence.evidence_id not in excluded_ids:
        raise Phase6EvaluationError("secret-bearing evidence was admitted")
    return {
        "included_count": len(package.evidence),
        "excluded_count": len(package.excluded_evidence),
    }


def _case_known_repair_priority(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    policy = RepairPolicy(
        policy_id="phase6-replay-known-restart",
        version=1,
        trigger_source="replay",
        component_id="runtime.demo",
        reason_code="unknown_failure",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=(),
        max_attempts=3,
        rolling_window_seconds=300.0,
        cooldown_seconds=1.0,
        backoff_multiplier=2.0,
        verification_contract="runtime-liveness-v1",
        reversible=True,
        automatic=True,
    )
    work, changes, coordinator, _, _, _, admitted = _admit(
        root,
        repository_root,
        revision,
    )
    del work, coordinator, admitted
    incidents, evidence, trigger = _base_incident(
        root / "known",
        revision=revision,
    )
    admission = IncidentRepairCoordinator(
        incidents=incidents,
        changes=ChangeCoordinator(changes, _Backend()),
        repair_registry=RepairRegistry((policy,)),
    )
    repair_trigger = RepairTrigger.create(
        component_id="runtime.demo",
        reason_code="unknown_failure",
        source="replay",
        health_state=HealthState.FAILED,
        evidence_references=(evidence.reference,),
        observed_at_epoch=102.0,
    )
    try:
        admission.admit(trigger, repair_trigger=repair_trigger)
    except IncidentRepairAdmissionBlocked as exc:
        return {"blocked": True, "reason": str(exc)}
    raise Phase6EvaluationError("known deterministic repair did not retain priority")


def _case_duplicate_trigger(root: pathlib.Path) -> dict[str, object]:
    repository_root, revision = _new_repo(root)
    work, changes, coordinator, _, _, _, _ = _admit(
        root,
        repository_root,
        revision,
    )
    incidents, _, trigger = _base_incident(root / "duplicate", revision=revision)
    admission = IncidentRepairCoordinator(
        incidents=incidents,
        changes=coordinator,
    )
    first = admission.admit(trigger)
    second = admission.admit(trigger)
    if first.change.change_id != second.change.change_id:
        raise Phase6EvaluationError("duplicate trigger created duplicate change")
    if first.diagnostics_work_id != second.diagnostics_work_id:
        raise Phase6EvaluationError("duplicate trigger created duplicate diagnostics")
    return {
        "change_id": first.change.change_id,
        "diagnostics_work_id": first.diagnostics_work_id,
        "stage_count": len(changes.list_stages(first.change.change_id)),
        "work_store": str(work.path),
    }


def _case_protected_main(root: pathlib.Path) -> dict[str, object]:
    fixture = _full_candidate_fixture(root)
    if fixture["protected_main_unchanged"] is not True:
        raise Phase6EvaluationError("protected main changed during repair candidate build")
    return {
        "source_revision": fixture["source_revision"],
        "unchanged": True,
    }


def _case_candidate_exact_digest(root: pathlib.Path) -> dict[str, object]:
    fixture = _full_candidate_fixture(root)
    candidate = fixture["candidate"]
    if not isinstance(candidate, dict):
        raise Phase6EvaluationError("candidate payload malformed")
    if candidate.get("commit") != fixture["commit"]:
        raise Phase6EvaluationError("candidate commit is not exact worktree head")
    canonical = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_id", "digest", "source_revision", "protected_surface"}
    }
    expected = canonical_digest(canonical)
    if candidate.get("digest") != expected:
        raise Phase6EvaluationError("candidate digest is not canonical")
    return {
        "commit": fixture["commit"],
        "candidate_digest": candidate["digest"],
        "candidate_artifact_digest": fixture["candidate_artifact_digest"],
    }


def run_replay_suite(root: pathlib.Path) -> Phase6ReplayReport:
    base = pathlib.Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)

    cases = (
        _case("01_local_defect_repaired", lambda: _case_repaired(base / "case01")),
        _case("02_inconclusive", lambda: _case_inconclusive(base / "case02")),
        _case("03_wrong_first_hypothesis", _case_wrong_first_hypothesis),
        _case(
            "04_knowledge_advisory_only",
            lambda: _case_knowledge_advisory(base / "case04"),
        ),
        _case("05_provider_pressure", _case_provider_pressure),
        _case(
            "06_restart_during_diagnostics",
            lambda: _case_restart_diagnostics(base / "case06"),
        ),
        _case(
            "07_restart_after_approval",
            lambda: _case_restart_after_approval(base / "case07"),
        ),
        _case(
            "08_restart_during_development",
            lambda: _case_restart_during_development(base / "case08"),
        ),
        _case("09_failed_candidate_tests", _case_failed_candidate_tests),
        _case("10_protected_surface", _case_protected_surface),
        _case(
            "11_secret_evidence_negative_control",
            lambda: _case_secret_evidence(base / "case11"),
        ),
        _case(
            "12_known_repair_priority",
            lambda: _case_known_repair_priority(base / "case12"),
        ),
        _case(
            "13_duplicate_trigger_idempotency",
            lambda: _case_duplicate_trigger(base / "case13"),
        ),
        _case(
            "14_protected_main_unchanged",
            lambda: _case_protected_main(base / "case14"),
        ),
        _case(
            "15_candidate_exact_digest",
            lambda: _case_candidate_exact_digest(base / "case15"),
        ),
    )
    status = "PASS" if all(item.passed for item in cases) else "FAIL"
    digest_payload = {
        "status": status,
        "cases": [item.to_payload() for item in cases],
    }
    return Phase6ReplayReport(
        status=status,
        cases=cases,
        suite_digest=canonical_digest(digest_payload),
    )
