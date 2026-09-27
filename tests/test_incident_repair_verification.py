from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.incident_repair.architecture import (
    IncidentRepairDevelopmentRevisionResolver,
    IncidentRepairSourceCompletionHandler,
)
from jarvis.incident_repair.models import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    IncidentRepairTrigger,
    ReproductionState,
)
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.incident_repair.verification import (
    IncidentRepairDevelopmentCompletionHandler,
    SourceRepairCandidateError,
    SourceRepairCandidateVerifier,
)
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture()
def repair_repo(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("git") is None:
        pytest.skip("Git is required for source-repair candidate tests")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis-tests@example.invalid")
    _git(root, "config", "user.name", "JARVIS Tests")

    source = root / "src" / "jarvis" / "voice"
    source.mkdir(parents=True)
    (source / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_voice_runtime.py").write_text(
        "from src.jarvis.voice.runtime import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 1\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "incident revision")
    revision = _git(root, "rev-parse", "HEAD").stdout.strip().lower()
    return root, revision


def _completed_step(
    work_id: str,
    kind: str,
    *,
    input_data: dict | None = None,
    observation: dict | None = None,
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


def _build_change(
    tmp_path: Path,
    repository_root: Path,
    revision: str,
):
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    change_store = ChangeStore(
        work_store,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    backend = Backend()
    manager = DevelopmentWorkspaceManager(
        repository_root=repository_root,
        workspace_root=tmp_path / "worktrees",
        base_revision_resolver=IncidentRepairDevelopmentRevisionResolver(change_store),
    )
    coordinator = ChangeCoordinator(
        change_store,
        backend,
        source_completion_handlers=(
            IncidentRepairSourceCompletionHandler(change_store),
        ),
        development_completion_handlers=(
            IncidentRepairDevelopmentCompletionHandler(
                change_store,
                manager,
            ),
        ),
    )

    change = coordinator.start(
        "Repair incident incident-1",
        "incident:incident-1",
        "revision:" + revision,
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
    )
    diagnostic_stage = change_store.list_stages(change.change_id)[0]
    diagnostic_work = work_store.require(diagnostic_stage.work_id)

    trigger = IncidentRepairTrigger.create(
        incident_id="incident-1",
        source_revision=revision,
        component_ids=("runtime.voice",),
        evidence_ids=("evidence-1",),
        reason_code="unknown_failure",
        now_epoch=100.0,
    )
    change_store.add_artifact(
        change.change_id,
        kind="incident_repair_trigger",
        payload={
            "trigger_id": trigger.trigger_id,
            **trigger.canonical_payload(),
            "digest": trigger.digest,
        },
    )

    hypothesis = DiagnosticHypothesis.create(
        statement="voice runtime value is wrong",
        affected_components=("runtime.voice",),
        affected_paths=("src/jarvis/voice/runtime.py",),
        supporting_evidence_ids=("evidence-1",),
        status=HypothesisState.SUPPORTED,
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id=change.change_id,
        work_id=diagnostic_work.work_id,
        source_revision=revision,
        evidence_ids=("evidence-1",),
        reproduction_state=ReproductionState.REPRODUCED,
        hypotheses=(hypothesis,),
        selected_hypothesis_id=hypothesis.hypothesis_id,
        affected_paths=("src/jarvis/voice/runtime.py",),
        affected_components=("runtime.voice",),
        proposed_repair_scope="correct runtime value",
        verification_targets=("tests/test_voice_runtime.py",),
        reason_codes=("reproduced", "supported_hypothesis"),
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=101.0,
    )
    diagnosis_payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    diagnosis_artifact = change_store.add_artifact(
        change.change_id,
        kind="diagnosis",
        payload={
            "diagnosis": diagnosis_payload,
            "suspicious_locations": [],
            "reproduction_impossible_reason": None,
        },
    )

    running = diagnostic_work.transition(WorkState.RUNNING)
    work_store.save(running, expected_version=diagnostic_work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "diagnosis": diagnosis_payload,
            "diagnosis_artifact_id": diagnosis_artifact.artifact_id,
            "diagnosis_artifact_digest": diagnosis_artifact.digest,
            "suspicious_locations": [],
        },
    )
    work_store.save(completed, expected_version=running.version)

    ready = coordinator.reconcile_for_work(diagnostic_work.work_id)
    assert ready is not None
    assert ready.state is ChangeState.ARCHITECTURE_READY
    architecture = change_store.latest_artifact(change.change_id, "architecture")
    assert architecture is not None

    gates = GateService(change_store, verify_owner=lambda *_: True)
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
        source_session_id="owner-session",
        source_turn_id="approve-architecture",
        request_key="phase6f:architecture",
    )
    developing = coordinator.reconcile(change.change_id)
    assert developing.state is ChangeState.DEVELOPING

    development_stage = next(
        item
        for item in change_store.list_stages(change.change_id)
        if item.stage_key == "development"
    )
    development_work = work_store.require(development_stage.work_id)
    return (
        work_store,
        change_store,
        coordinator,
        manager,
        gates,
        change.change_id,
        diagnosis,
        architecture,
        development_work,
    )


def _complete_valid_development(
    work_store: SQLiteWorkStore,
    manager: DevelopmentWorkspaceManager,
    work: WorkItem,
) -> tuple[str, str]:
    workspace = manager.ensure(work.work_id)
    source = workspace.path / "src" / "jarvis" / "voice" / "runtime.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_write_file",
            input_data={"path": "src/jarvis/voice/runtime.py"},
            observation={
                "path": "src/jarvis/voice/runtime.py",
                "production_tree_modified": False,
            },
        )
    )
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_voice_runtime.py"]},
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
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_diff",
            observation={"branch": workspace.branch, "diff": "bounded diff"},
        )
    )

    _git(workspace.path, "add", "--all")
    _git(workspace.path, "commit", "-m", "repair runtime value")
    commit = _git(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
    assert _git(workspace.path, "status", "--porcelain=v1").stdout == ""

    work_store.add_step(
        _completed_step(
            work.work_id,
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

    running = work.transition(WorkState.RUNNING)
    work_store.save(running, expected_version=work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "branch": workspace.branch,
            "commit": commit,
            "verification": {
                "passed": True,
                "sandbox": "docker",
            },
        },
    )
    work_store.save(completed, expected_version=running.version)
    return workspace.branch, commit


def test_workstep_order_rejects_tests_before_latest_edit() -> None:
    work = WorkItem(
        request="repair",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="change:1",
        source_turn_id="development:1",
        result={"verification": {"passed": True}},
    )
    steps = (
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_voice_runtime.py"]},
            observation={"passed": True},
        ),
        _completed_step(
            work.work_id,
            "dev_write_file",
            observation={"path": "src/jarvis/voice/runtime.py"},
        ),
        _completed_step(work.work_id, "dev_diff"),
        _completed_step(
            work.work_id,
            "dev_commit",
            observation={"committed": True, "clean": True},
        ),
    )

    with pytest.raises(
        SourceRepairCandidateError,
        match="passing sandboxed tests after latest edit",
    ):
        SourceRepairCandidateVerifier._verify_workstep_order(
            work,
            steps,
            ("tests/test_voice_runtime.py",),
        )


def test_workstep_order_requires_final_diff_and_clean_commit() -> None:
    work = WorkItem(
        request="repair",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="change:1",
        source_turn_id="development:1",
        result={"verification": {"passed": True}},
    )
    base = (
        _completed_step(work.work_id, "dev_write_file"),
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_voice_runtime.py"]},
            observation={
                "passed": True,
                "network": "disabled",
                "workspace": "read_only",
                "sandbox_profile": "test.offline.v1",
                "sandbox_profile_version": 1,
            },
        ),
    )
    with pytest.raises(SourceRepairCandidateError, match="final diff inspection"):
        SourceRepairCandidateVerifier._verify_workstep_order(
            work,
            base,
            ("tests/test_voice_runtime.py",),
        )

    with pytest.raises(SourceRepairCandidateError, match="clean local commit"):
        SourceRepairCandidateVerifier._verify_workstep_order(
            work,
            (*base, _completed_step(work.work_id, "dev_diff")),
            ("tests/test_voice_runtime.py",),
        )


def test_approved_scope_rejects_outside_diff() -> None:
    architecture = SimpleNamespace(
        payload={
            "allowed_paths": ["src/jarvis/voice/runtime.py"],
            "verification_targets": ["tests/test_voice_runtime.py"],
        }
    )

    with pytest.raises(
        SourceRepairCandidateError,
        match="outside owner-approved architecture",
    ):
        SourceRepairCandidateVerifier._verify_approved_scope(
            architecture,
            ("src/jarvis/voice/other.py",),
        )


def test_valid_candidate_binds_git_diagnosis_architecture_and_acceptance_gate(
    tmp_path: Path,
    repair_repo: tuple[Path, str],
) -> None:
    repository_root, revision = repair_repo
    (
        work_store,
        change_store,
        coordinator,
        manager,
        gates,
        change_id,
        diagnosis,
        architecture,
        development_work,
    ) = _build_change(tmp_path, repository_root, revision)

    branch, commit = _complete_valid_development(
        work_store,
        manager,
        development_work,
    )
    verifying = coordinator.reconcile(change_id)

    assert verifying.state is ChangeState.VERIFYING
    candidate_artifact = change_store.latest_artifact(
        change_id,
        "source_repair_candidate",
    )
    acceptance = change_store.latest_artifact(change_id, "acceptance")
    verification = change_store.latest_artifact(
        change_id,
        "source_repair_verification",
    )
    assert candidate_artifact is not None
    assert acceptance is not None
    assert verification is not None
    assert verification.payload["passed"] is True

    candidate = candidate_artifact.payload
    assert candidate["commit"] == commit
    assert candidate["branch"] == branch
    assert candidate["source_revision"] == revision
    assert candidate["diagnosis_id"] == diagnosis.diagnosis_id
    assert candidate["diagnosis_digest"] == diagnosis.digest
    assert candidate["architecture_artifact_id"] == architecture.artifact_id
    assert candidate["architecture_digest"] == architecture.digest
    assert candidate["changed_paths"] == ["src/jarvis/voice/runtime.py"]
    assert len(candidate["diff_digest"]) == 64
    assert candidate["protected_surface_verdict"] == "clear"

    gate = gates.present(change_id, GateKind.ACCEPTANCE, acceptance.artifact_id)
    assert gate.artifact_digest == acceptance.digest
    assert change_store.require(change_id).state is ChangeState.WAITING_OWNER_ACCEPTANCE
