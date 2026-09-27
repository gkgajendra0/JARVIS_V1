from __future__ import annotations

import pathlib
import subprocess

import pytest

from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.incident_repair.handoff import IncidentRepairProcessAdapter
from jarvis.incident_repair.models import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    ReproductionState,
)
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.development import (
    ChangeStoreDevelopmentRevisionResolver,
    DevelopmentWorkspaceManager,
)
from jarvis.work.models import WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


REVISION = "a" * 40


class Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id, *, priority):
        del priority
        self.submitted.append(work_id)
        return work_id


def _coordinator(tmp_path):
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(
        work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    backend = Backend()
    coordinator = ChangeCoordinator(
        changes,
        backend,
        process_adapters=(IncidentRepairProcessAdapter(),),
    )
    change = coordinator.start(
        f"Investigate incident incident-1 at exact source revision {REVISION}",
        "incident:incident-1",
        f"revision:{REVISION}",
        process_key="unknown_incident_repair",
        process_version=1,
    )
    diagnostics = changes.list_stages(change.change_id)[0]
    return work, changes, backend, coordinator, change, diagnostics


def _supported_diagnosis(change_id: str, work_id: str, revision: str = REVISION):
    hypothesis = DiagnosticHypothesis.create(
        statement="state commit races runtime restart",
        affected_components=("runtime.voice",),
        affected_paths=("src/jarvis/voice/runtime.py",),
        supporting_evidence_ids=("e1",),
        status=HypothesisState.SUPPORTED,
        discriminator="reproduces when restart lands before state commit",
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id=change_id,
        work_id=work_id,
        source_revision=revision,
        evidence_ids=("e1",),
        knowledge_revision_ids=("knowledge-r1",),
        reproduction_state=ReproductionState.REPRODUCED,
        hypotheses=(hypothesis,),
        selected_hypothesis_id=hypothesis.hypothesis_id,
        affected_paths=("src/jarvis/voice/runtime.py",),
        affected_components=("runtime.voice",),
        proposed_repair_scope="serialize supervisor state commit before restart",
        verification_targets=("tests/test_voice_runtime.py",),
        reason_codes=("reproduced", "supported_hypothesis"),
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=100.0,
    )
    return diagnosis, hypothesis


def _complete_supported_diagnostics(
    work: SQLiteWorkStore,
    changes: ChangeStore,
    change_id: str,
    work_id: str,
    revision: str = REVISION,
):
    diagnosis, hypothesis = _supported_diagnosis(
        change_id,
        work_id,
        revision,
    )
    payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    artifact = changes.add_artifact(
        change_id,
        kind="diagnosis",
        payload={
            "diagnosis": payload,
            "suspicious_locations": [],
            "reproduction_impossible_reason": None,
        },
    )
    item = work.require(work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    completed = work.save(
        running.transition(
            WorkState.COMPLETED,
            result={
                "diagnosis": payload,
                "diagnosis_artifact_id": artifact.artifact_id,
                "diagnosis_artifact_digest": artifact.digest,
                "suspicious_locations": [],
            },
        ),
        expected_version=running.version,
    )
    return completed, artifact, diagnosis, hypothesis


def _approve_architecture(changes, change_id, architecture):
    gates = GateService(changes, verify_owner=lambda *_: True)
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
        source_session_id="owner-session",
        source_turn_id="owner-approve",
        request_key=f"approve:{architecture.artifact_id}",
    )
    return gate


def test_supported_diagnosis_derives_architecture_but_no_development_before_gate(
    tmp_path,
) -> None:
    work, changes, _, coordinator, change, diagnostics = _coordinator(tmp_path)
    _, diagnosis_artifact, diagnosis, hypothesis = _complete_supported_diagnostics(
        work,
        changes,
        change.change_id,
        diagnostics.work_id,
    )

    coordinator.reconcile_for_work(diagnostics.work_id)

    architecture = changes.latest_artifact(change.change_id, "architecture")
    assert architecture is not None
    assert architecture.payload["source_revision"] == REVISION
    assert architecture.payload["diagnosis_artifact_id"] == diagnosis_artifact.artifact_id
    assert architecture.payload["diagnosis_artifact_digest"] == diagnosis_artifact.digest
    assert architecture.payload["diagnosis_id"] == diagnosis.diagnosis_id
    assert architecture.payload["diagnosis_digest"] == diagnosis.digest
    assert architecture.payload["selected_hypothesis_id"] == hypothesis.hypothesis_id
    assert architecture.payload["approved_changed_paths"] == [
        "src/jarvis/voice/runtime.py"
    ]
    assert architecture.payload["verification_targets"] == [
        "tests/test_voice_runtime.py"
    ]
    assert (
        changes.require(change.change_id).state
        is ChangeState.ARCHITECTURE_READY
    )
    assert len(changes.list_stages(change.change_id)) == 1
    assert work.require(diagnostics.work_id).work_type is WorkType.DIAGNOSTICS


def test_owner_rejection_creates_no_development_stage(tmp_path) -> None:
    work, changes, _, coordinator, change, diagnostics = _coordinator(tmp_path)
    _complete_supported_diagnostics(
        work,
        changes,
        change.change_id,
        diagnostics.work_id,
    )
    coordinator.reconcile_for_work(diagnostics.work_id)
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
        approved=False,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner-session",
        source_turn_id="owner-reject",
        request_key="reject:phase6e",
    )
    coordinator.reconcile(change.change_id)

    assert changes.require(change.change_id).state is ChangeState.REJECTED
    assert len(changes.list_stages(change.change_id)) == 1


def test_owner_approval_creates_one_development_bound_to_diagnosis_and_architecture(
    tmp_path,
) -> None:
    work, changes, backend, coordinator, change, diagnostics = _coordinator(tmp_path)
    _complete_supported_diagnostics(
        work,
        changes,
        change.change_id,
        diagnostics.work_id,
    )
    coordinator.reconcile_for_work(diagnostics.work_id)
    architecture = changes.latest_artifact(change.change_id, "architecture")
    assert architecture is not None
    _approve_architecture(changes, change.change_id, architecture)

    coordinator.reconcile(change.change_id)
    coordinator.reconcile(change.change_id)

    stages = changes.list_stages(change.change_id)
    development_stages = [item for item in stages if item.stage_key == "development"]
    assert len(development_stages) == 1
    development = development_stages[0]
    item = work.require(development.work_id)
    assert item.work_type is WorkType.DEVELOPMENT
    assert item.dependencies == (diagnostics.work_id,)
    assert development.plan_artifact_id == architecture.artifact_id
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING
    assert architecture.artifact_id in item.request
    assert architecture.digest in item.request
    assert architecture.payload["diagnosis_artifact_id"] in item.request
    assert architecture.payload["diagnosis_digest"] in item.request
    assert REVISION in item.request
    assert backend.submitted.count(development.work_id) >= 1


def test_stale_phase6_architecture_approval_is_rejected(tmp_path) -> None:
    work, changes, _, coordinator, change, diagnostics = _coordinator(tmp_path)
    _complete_supported_diagnostics(
        work,
        changes,
        change.change_id,
        diagnostics.work_id,
    )
    coordinator.reconcile_for_work(diagnostics.work_id)
    first = changes.latest_artifact(change.change_id, "architecture")
    assert first is not None
    gates = GateService(changes, verify_owner=lambda *_: True)
    challenge = gates.present(
        change.change_id,
        GateKind.ARCHITECTURE,
        first.artifact_id,
    )

    second = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={**first.payload, "rollback_disable_notes": "revised owner scope"},
    )
    assert second.revision == first.revision + 1

    with pytest.raises(ChangeConflict, match="superseded"):
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest=first.digest,
            actor_id="owner",
            source_session_id="owner-session",
            source_turn_id="owner-approve",
            request_key="stale:phase6e",
        )
    assert len(changes.list_stages(change.change_id)) == 1


def test_restart_cannot_skip_owner_architecture_gate(tmp_path) -> None:
    work, changes, _, coordinator, change, diagnostics = _coordinator(tmp_path)
    _complete_supported_diagnostics(
        work,
        changes,
        change.change_id,
        diagnostics.work_id,
    )
    coordinator.reconcile_for_work(diagnostics.work_id)
    architecture = changes.latest_artifact(change.change_id, "architecture")
    assert architecture is not None

    restarted_work = SQLiteWorkStore(work.path)
    restarted_store = ChangeStore(
        restarted_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    restarted = ChangeCoordinator(
        restarted_store,
        Backend(),
        process_adapters=(IncidentRepairProcessAdapter(),),
    )
    restarted.reconcile_active()

    assert (
        restarted_store.require(change.change_id).state
        is ChangeState.ARCHITECTURE_READY
    )
    assert len(restarted_store.list_stages(change.change_id)) == 1


def test_inconclusive_diagnosis_cannot_derive_write_architecture(tmp_path) -> None:
    work, changes, _, coordinator, change, diagnostics = _coordinator(tmp_path)
    hypothesis = DiagnosticHypothesis.create(
        statement="hardware timing may be involved",
        status=HypothesisState.INCONCLUSIVE,
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id=change.change_id,
        work_id=diagnostics.work_id,
        source_revision=REVISION,
        evidence_ids=("e1",),
        reproduction_state=ReproductionState.INCONCLUSIVE,
        hypotheses=(hypothesis,),
        reason_codes=("reproduction_impossible",),
        disposition=DiagnosisDisposition.INCONCLUSIVE,
        now_epoch=100.0,
    )
    payload = {
        "diagnosis_id": diagnosis.diagnosis_id,
        **diagnosis.canonical_payload(),
        "digest": diagnosis.digest,
    }
    artifact = changes.add_artifact(
        change.change_id,
        kind="diagnosis",
        payload={
            "diagnosis": payload,
            "suspicious_locations": [],
            "reproduction_impossible_reason": "hardware unavailable",
        },
    )
    item = work.require(diagnostics.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(
            WorkState.COMPLETED,
            result={
                "diagnosis": payload,
                "diagnosis_artifact_id": artifact.artifact_id,
                "diagnosis_artifact_digest": artifact.digest,
                "suspicious_locations": [],
            },
        ),
        expected_version=running.version,
    )

    coordinator.reconcile_for_work(diagnostics.work_id)

    assert changes.latest_artifact(change.change_id, "architecture") is None
    assert changes.require(change.change_id).state is ChangeState.RESEARCHING
    assert len(changes.list_stages(change.change_id)) == 1


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


def test_phase6_development_worktree_starts_from_diagnosed_revision(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "JARVIS Test")
    _git(repo, "config", "user.email", "jarvis-test@example.invalid")
    (repo / "example.py").write_text("VALUE = 'diagnosed'\n", encoding="utf-8")
    _git(repo, "add", "example.py")
    _git(repo, "commit", "-m", "diagnosed")
    diagnosed_revision = _git(repo, "rev-parse", "HEAD").lower()
    (repo / "example.py").write_text("VALUE = 'later-main'\n", encoding="utf-8")
    _git(repo, "add", "example.py")
    _git(repo, "commit", "-m", "later")
    later_revision = _git(repo, "rev-parse", "HEAD").lower()
    assert later_revision != diagnosed_revision

    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(
        work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    backend = Backend()
    coordinator = ChangeCoordinator(changes, backend)
    change = coordinator.start(
        "repair exact source",
        "incident:exact",
        f"revision:{diagnosed_revision}",
        process_key="unknown_incident_repair",
        process_version=1,
    )
    diagnostics = changes.list_stages(change.change_id)[0]
    diagnostic_item = work.require(diagnostics.work_id)
    running = work.save(
        diagnostic_item.transition(WorkState.RUNNING),
        expected_version=diagnostic_item.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED),
        expected_version=running.version,
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "source_revision": diagnosed_revision,
            "diagnosis_artifact_id": "diagnosis-artifact",
            "diagnosis_artifact_digest": "d" * 64,
            "diagnosis_id": "diagnosis-test",
            "diagnosis_digest": "e" * 64,
            "incident_id": "incident-exact",
            "repair_scope": "change example",
            "approved_changed_paths": ["example.py"],
            "approved_components": [],
            "verification_targets": ["tests/test_example.py"],
        },
    )
    coordinator.reconcile(change.change_id)
    _approve_architecture(changes, change.change_id, architecture)
    coordinator.reconcile(change.change_id)
    development = [
        stage
        for stage in changes.list_stages(change.change_id)
        if stage.stage_key == "development"
    ][0]

    manager = DevelopmentWorkspaceManager(
        repository_root=repo,
        workspace_root=tmp_path / "dev-worktrees",
        revision_resolver=ChangeStoreDevelopmentRevisionResolver(changes),
    )
    workspace = manager.ensure(development.work_id)

    assert _git(workspace.path, "rev-parse", "HEAD").lower() == diagnosed_revision
    assert (workspace.path / "example.py").read_text(encoding="utf-8") == (
        "VALUE = 'diagnosed'\n"
    )
    assert _git(repo, "rev-parse", "HEAD").lower() == later_revision
