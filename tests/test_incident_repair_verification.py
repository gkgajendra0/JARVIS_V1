from __future__ import annotations

import pathlib
import subprocess
from dataclasses import dataclass

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.incident_repair.architecture import (
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
)
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkPriority, WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore


@dataclass
class Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def _git(root: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


def _repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "JARVIS Test")
    _git(root, "config", "user.email", "jarvis-test@example.invalid")

    voice = root / "src" / "jarvis" / "voice"
    voice.mkdir(parents=True)
    (root / "src" / "jarvis" / "__init__.py").write_text("", encoding="utf-8")
    (voice / "__init__.py").write_text("", encoding="utf-8")
    (voice / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (voice / "other.py").write_text("OTHER = 1\n", encoding="utf-8")

    authority = root / "src" / "jarvis" / "authority"
    authority.mkdir()
    (authority / "__init__.py").write_text("", encoding="utf-8")
    (authority / "service.py").write_text("AUTHORITY = 1\n", encoding="utf-8")

    tests = root / "tests"
    tests.mkdir()
    (tests / "test_voice_runtime.py").write_text(
        "def test_runtime():\n    assert True\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    return root, _git(root, "rev-parse", "HEAD").lower()


def _completed_step(
    store: SQLiteWorkStore,
    *,
    work_id: str,
    kind: str,
    observation: dict,
    input_data: dict | None = None,
) -> None:
    step = WorkStep(
        work_id=work_id,
        kind=kind,
        summary=kind,
        input_data=dict(input_data or {}),
    )
    store.add_step(step)
    store.save_step(step.start().complete(observation))


def _prepare_change(
    tmp_path: pathlib.Path,
    *,
    affected_path: str = "src/jarvis/voice/runtime.py",
) -> tuple[
    pathlib.Path,
    str,
    SQLiteWorkStore,
    ChangeStore,
    ChangeCoordinator,
    DevelopmentWorkspaceManager,
    str,
    str,
]:
    repo, revision = _repo(tmp_path)
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(
        work_store,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    workspace_manager = DevelopmentWorkspaceManager(
        repository_root=repo,
        workspace_root=tmp_path / "worktrees",
    )
    backend = Backend([])
    coordinator = ChangeCoordinator(
        changes,
        backend,
        source_completion_handlers=(
            IncidentRepairSourceCompletionHandler(changes),
        ),
        development_completion_handlers=(
            IncidentRepairDevelopmentCompletionHandler(
                changes,
                workspace_manager,
            ),
        ),
    )
    change = coordinator.start(
        f"Investigate incident incident-1 at exact source revision {revision}",
        "incident:incident-1",
        f"revision:{revision}",
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
    )
    diagnostic_stage = changes.list_stages(change.change_id)[0]
    diagnostic_work = work_store.require(diagnostic_stage.work_id)

    trigger = IncidentRepairTrigger.create(
        incident_id="incident-1",
        source_revision=revision,
        component_ids=("runtime.voice",),
        evidence_ids=("evidence-1",),
        reason_code="unknown_failure",
        now_epoch=100.0,
    )
    changes.add_artifact(
        change.change_id,
        kind="incident_repair_trigger",
        payload={
            "trigger_id": trigger.trigger_id,
            **trigger.canonical_payload(),
            "digest": trigger.digest,
        },
    )
    hypothesis = DiagnosticHypothesis.create(
        statement="runtime state bug",
        affected_components=("runtime.voice",),
        affected_paths=(affected_path,),
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
        affected_paths=(affected_path,),
        affected_components=("runtime.voice",),
        proposed_repair_scope="repair runtime state",
        verification_targets=("tests/test_voice_runtime.py::test_runtime",),
        reason_codes=("reproduced", "supported_hypothesis"),
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=200.0,
    )
    diagnosis_payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    diagnosis_artifact = changes.add_artifact(
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
    coordinator.reconcile_for_work(diagnostic_work.work_id)

    architecture = changes.latest_artifact(change.change_id, "architecture")
    assert architecture is not None
    gates = GateService(changes, verify_owner=lambda *_: True)
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
        source_session_id="owner",
        source_turn_id="approve",
        request_key=f"approve:{change.change_id}",
    )
    coordinator.reconcile(change.change_id)
    development = changes.list_stages(change.change_id)[1]
    return (
        repo,
        revision,
        work_store,
        changes,
        coordinator,
        workspace_manager,
        change.change_id,
        development.work_id,
    )


def _complete_development(
    *,
    repo: pathlib.Path,
    store: SQLiteWorkStore,
    manager: DevelopmentWorkspaceManager,
    work_id: str,
    changed_path: str,
    tests_after_write: bool = True,
    executed_target: str = "tests/test_voice_runtime.py::test_runtime",
) -> tuple[str, str]:
    work = store.require(work_id)
    workspace = manager.ensure(work_id)
    target = workspace.path / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if not tests_after_write:
        _completed_step(
            store,
            work_id=work_id,
            kind="dev_run_tests",
            input_data={"targets": [executed_target]},
            observation={
                "passed": True,
                "sandbox": "docker",
                "network": "disabled",
                "workspace": "read_only",
                "sandbox_profile": "test.offline.v1",
                "sandbox_profile_version": 1,
            },
        )

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(original + "# repaired\n", encoding="utf-8")
    _completed_step(
        store,
        work_id=work_id,
        kind="dev_write_file",
        input_data={"path": changed_path},
        observation={"path": changed_path, "production_tree_modified": False},
    )

    if tests_after_write:
        _completed_step(
            store,
            work_id=work_id,
            kind="dev_run_tests",
            input_data={"targets": [executed_target]},
            observation={
                "passed": True,
                "sandbox": "docker",
                "network": "disabled",
                "workspace": "read_only",
                "sandbox_profile": "test.offline.v1",
                "sandbox_profile_version": 1,
            },
        )

    diff = _git(workspace.path, "diff", "--no-ext-diff", "--no-textconv", "--")
    _completed_step(
        store,
        work_id=work_id,
        kind="dev_diff",
        observation={"branch": workspace.branch, "diff": diff, "truncated": False},
    )
    _git(workspace.path, "add", "--all")
    _git(workspace.path, "commit", "-m", "Repair incident")
    commit = _git(workspace.path, "rev-parse", "HEAD").lower()
    _completed_step(
        store,
        work_id=work_id,
        kind="dev_commit",
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

    running = work.transition(WorkState.RUNNING)
    store.save(running, expected_version=work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "branch": workspace.branch,
            "commit": commit,
            "verification": {"passed": True, "sandbox": "docker"},
        },
    )
    store.save(completed, expected_version=running.version)
    assert _git(repo, "status", "--porcelain") == ""
    return workspace.branch, commit


def test_clear_candidate_creates_owner_reviewable_acceptance_evidence(tmp_path) -> None:
    (
        repo,
        revision,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(tmp_path)
    branch, commit = _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="src/jarvis/voice/runtime.py",
    )

    reconciled = coordinator.reconcile_for_work(work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.VERIFYING
    candidate = changes.latest_artifact(change_id, "source_repair_candidate")
    acceptance = changes.latest_artifact(change_id, "acceptance")
    verification = changes.latest_artifact(change_id, "source_repair_verification")
    assert candidate is not None
    assert acceptance is not None
    assert verification is not None
    assert verification.payload["passed"] is True
    assert candidate.payload["source_revision"] == revision
    assert candidate.payload["branch"] == branch
    assert candidate.payload["commit"] == commit
    assert candidate.payload["changed_paths"] == [
        "src/jarvis/voice/runtime.py"
    ]
    assert candidate.payload["verification_targets"] == [
        "tests/test_voice_runtime.py::test_runtime"
    ]
    assert candidate.payload["protected_surface"]["verdict"] == "clear"

    gates = GateService(changes, verify_owner=lambda *_: True)
    challenge = gates.present(
        change_id,
        GateKind.ACCEPTANCE,
        acceptance.artifact_id,
    )
    assert challenge.artifact_digest == acceptance.digest
    assert changes.require(change_id).state is ChangeState.WAITING_OWNER_ACCEPTANCE


def test_out_of_scope_commit_fails_before_owner_acceptance(tmp_path) -> None:
    (
        repo,
        _,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(
        tmp_path,
        affected_path="src/jarvis/voice/runtime.py",
    )
    _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="src/jarvis/voice/other.py",
    )

    result = coordinator.reconcile_for_work(work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    failure = changes.latest_artifact(change_id, "source_repair_verification")
    assert failure is not None
    assert failure.payload["reason_code"] == "changed_path_outside_approved_scope"
    assert changes.latest_artifact(change_id, "acceptance") is None


def test_stale_pre_edit_test_does_not_create_candidate(tmp_path) -> None:
    (
        repo,
        _,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(tmp_path)
    _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="src/jarvis/voice/runtime.py",
        tests_after_write=False,
    )

    result = coordinator.reconcile_for_work(work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    failure = changes.latest_artifact(change_id, "source_repair_verification")
    assert failure is not None
    assert failure.payload["reason_code"] == "post_edit_tests_missing"
    assert changes.latest_artifact(change_id, "source_repair_candidate") is None


def test_protected_surface_commit_requires_separate_authorized_change(tmp_path) -> None:
    (
        repo,
        _,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(
        tmp_path,
        affected_path="src/jarvis/authority/service.py",
    )
    _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="src/jarvis/authority/service.py",
    )

    result = coordinator.reconcile_for_work(work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    failure = changes.latest_artifact(change_id, "source_repair_verification")
    assert failure is not None
    assert failure.payload["reason_code"] == "protected_change_required"
    assert changes.latest_artifact(change_id, "acceptance") is None

def test_wrong_post_edit_test_does_not_satisfy_approved_target(tmp_path) -> None:
    (
        repo,
        _,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(tmp_path)
    _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="src/jarvis/voice/runtime.py",
        executed_target="tests/test_voice_runtime.py::test_other",
    )

    result = coordinator.reconcile_for_work(work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    failure = changes.latest_artifact(change_id, "source_repair_verification")
    assert failure is not None
    assert failure.payload["reason_code"] == "required_verification_missing"
    assert changes.latest_artifact(change_id, "acceptance") is None


def test_unknown_repository_surface_fails_closed_before_acceptance(tmp_path) -> None:
    (
        repo,
        _,
        store,
        changes,
        coordinator,
        manager,
        change_id,
        work_id,
    ) = _prepare_change(
        tmp_path,
        affected_path="scripts/release.py",
    )
    _complete_development(
        repo=repo,
        store=store,
        manager=manager,
        work_id=work_id,
        changed_path="scripts/release.py",
    )

    result = coordinator.reconcile_for_work(work_id)

    assert result is not None
    assert result.state is ChangeState.FAILED
    failure = changes.latest_artifact(change_id, "source_repair_verification")
    assert failure is not None
    assert failure.payload["reason_code"] == "protected_surface_unknown"
    assert changes.latest_artifact(change_id, "acceptance") is None

