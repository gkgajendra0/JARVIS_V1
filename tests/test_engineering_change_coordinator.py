from __future__ import annotations

import pytest

from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.models import WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def __init__(self) -> None:
        self.submissions: list[str] = []
        self.fail_once = False

    def submit(self, work_id, *, priority):
        del priority
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("backend temporarily unavailable")
        self.submissions.append(work_id)
        return work_id


def _complete(work, item):
    running = work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    return work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )


def test_restart_reconciles_submission_without_duplicate_stage(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)
    backend.fail_once = True
    with pytest.raises(RuntimeError, match="unavailable"):
        coordinator.start("Investigate camera", "session", "turn")
    change = changes.find_by_source("session", "turn", "engineering.change")
    assert change is not None
    stages = changes.list_stages(change.change_id)
    assert len(stages) == 1
    assert backend.submissions == []
    coordinator.reconcile(change.change_id)
    coordinator.reconcile(change.change_id)
    assert changes.list_stages(change.change_id) == stages
    assert backend.submissions == [stages[0].work_id]
    assert work.get_execution_id(stages[0].work_id) == stages[0].work_id


def test_change_stage_uses_shared_terminal_recovery_and_persists_binding(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)

    class RecoveringBackend(RecordingBackend):
        def __init__(self) -> None:
            super().__init__()
            self.recoveries: list[tuple[str, str, str]] = []

        def recover_execution(
            self,
            execution_id: str,
            *,
            work_id: str,
            priority,
            recovery_token: str,
        ) -> str:
            del priority
            self.recoveries.append((execution_id, work_id, recovery_token))
            return f"{work_id}__retry_{recovery_token}"

    backend = RecoveringBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = coordinator.start("Recover camera stage", "session", "turn")
    stage = changes.list_stages(change.change_id)[0]

    assert backend.submissions == []
    assert len(backend.recoveries) == 1
    source_execution, work_id, recovery_token = backend.recoveries[0]
    assert source_execution == stage.work_id
    assert work_id == stage.work_id
    assert recovery_token.startswith("startup_recovery_")
    assert work.get_execution_id(stage.work_id) == (
        f"{stage.work_id}__retry_{recovery_token}"
    )


def test_independent_changes_can_have_ready_research_workitems_in_parallel(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    first = coordinator.start("Research camera transport", "session", "turn-1")
    second = coordinator.start("Research phone gateway", "session", "turn-2")
    first_stage = changes.list_stages(first.change_id)[0]
    second_stage = changes.list_stages(second.change_id)[0]

    assert first_stage.work_id != second_stage.work_id
    assert backend.submissions == [first_stage.work_id, second_stage.work_id]
    assert work.require(first_stage.work_id).dependencies == ()
    assert work.require(second_stage.work_id).dependencies == ()
    assert work.require(first_stage.work_id).state is WorkState.QUEUED
    assert work.require(second_stage.work_id).state is WorkState.QUEUED


def test_research_then_approved_build_uses_dependent_workitem(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)
    change = coordinator.start("Build camera adapter", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    _complete(work, work.require(research.work_id))
    coordinator.reconcile_for_work(research.work_id)
    assert changes.require(change.change_id).state is ChangeState.RESEARCHING
    artifact = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"decision": "typed local adapter"},
    )
    coordinator.reconcile(change.change_id)
    assert changes.require(change.change_id).state is ChangeState.ARCHITECTURE_READY
    gates = GateService(changes, verify_owner=lambda *_: True)
    gate = gates.present(change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="session",
        source_turn_id="approval",
        request_key="session:approval",
    )
    coordinator.reconcile(change.change_id)
    development = changes.list_stages(change.change_id)[1]
    assert work.require(development.work_id).dependencies == (research.work_id,)
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING
    _complete(work, work.require(development.work_id))
    coordinator.reconcile_for_work(development.work_id)
    assert changes.require(change.change_id).state is ChangeState.VERIFYING
    assert all(item != gate.gate_id for item in backend.submissions)


def test_dev_stage_cannot_be_created_before_approval_or_after_revision_change(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)
    change = coordinator.start("Goal", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    with pytest.raises(ChangeConflict):
        coordinator.submit_stage(change.change_id, "development", 1)
    _complete(work, work.require(research.work_id))
    artifact = changes.add_artifact(
        change.change_id, kind="architecture", payload={"v": 1}
    )
    coordinator.reconcile(change.change_id)
    gates = GateService(changes, verify_owner=lambda *_: True)
    gate = gates.present(change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="session",
        source_turn_id="approval",
        request_key="approval",
    )
    changes.add_artifact(change.change_id, kind="architecture", payload={"v": 2})
    with pytest.raises(ChangeConflict):
        coordinator.submit_stage(change.change_id, "development", 1)


def test_startup_reconciles_terminal_research_and_unsubmitted_stage(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)
    change = coordinator.start("Goal", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    _complete(work, work.require(research.work_id))
    changes.add_artifact(
        change.change_id, kind="architecture", payload={"plan": "review"}
    )
    restarted = ChangeCoordinator(ChangeStore(SQLiteWorkStore(work.path)), backend)
    restarted.reconcile_active()
    assert (
        restarted.store.require(change.change_id).state
        is ChangeState.ARCHITECTURE_READY
    )


def test_changed_architecture_cannot_verify_completed_old_development(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, RecordingBackend())
    change = coordinator.start("Goal", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    _complete(work, work.require(research.work_id))
    artifact = changes.add_artifact(
        change.change_id, kind="architecture", payload={"v": 1}
    )
    coordinator.reconcile(change.change_id)
    gates = GateService(changes, verify_owner=lambda *_: True)
    gate = gates.present(change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="session",
        source_turn_id="yes",
        request_key="session:yes",
    )
    coordinator.reconcile(change.change_id)
    development = changes.list_stages(change.change_id)[1]
    _complete(work, work.require(development.work_id))
    changes.add_artifact(change.change_id, kind="architecture", payload={"v": 2})
    assert changes.require(change.change_id).state is ChangeState.ARCHITECTURE_READY
    assert not changes.work_admitted(development.work_id)
    coordinator.reconcile_for_work(development.work_id)
    new_architecture = changes.latest_artifact(change.change_id, "architecture")
    assert new_architecture is not None
    new_gate = gates.present(
        change.change_id, GateKind.ARCHITECTURE, new_architecture.artifact_id
    )
    gates.decide(
        new_gate.gate_id,
        approved=True,
        artifact_digest=new_architecture.digest,
        actor_id="owner",
        source_session_id="session",
        source_turn_id="new-approval",
        request_key="session:new-approval",
    )
    coordinator.reconcile(change.change_id)
    new_development = changes.list_stages(change.change_id)[2]
    assert new_development.attempt == 2
    assert new_development.work_id != development.work_id
    assert not changes.work_admitted(development.work_id)
    assert changes.work_admitted(new_development.work_id)


def test_development_can_reopen_governed_architecture_research(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)
    change = coordinator.start("Build media adapter", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    _complete(work, work.require(research.work_id))
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"v": 1, "transport": "initial"},
    )
    coordinator.reconcile(change.change_id)
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
        source_session_id="session",
        source_turn_id="approval",
        request_key="session:approval",
    )
    coordinator.reconcile(change.change_id)
    development = next(
        stage
        for stage in changes.list_stages(change.change_id)
        if stage.stage_key == "development"
    )

    reopened = changes.request_architecture_revision_for_work(
        development.work_id,
        reason="Dependency graph changed after verification.",
    )

    assert reopened.state is ChangeState.RESEARCHING

    replayed = changes.request_architecture_revision_for_work(
        development.work_id,
        reason="Replay after a process interruption.",
    )
    assert replayed == reopened
    revision_requests = changes.list_artifacts(
        change.change_id,
        kind="architecture_revision_request",
    )
    assert len(revision_requests) == 1

    coordinator.reconcile(change.change_id)
    research_stages = [
        stage
        for stage in changes.list_stages(change.change_id)
        if stage.stage_key == "research"
    ]
    assert [stage.attempt for stage in research_stages] == [1, 2]
    replacement = work.require(research_stages[-1].work_id)
    assert "Dependency graph changed after verification." in replacement.request
    assert replacement.work_id != research.work_id
    revision = changes.latest_artifact(
        change.change_id,
        "architecture_revision_request",
    )
    assert revision is not None
    assert (
        revision.payload["previous_architecture_artifact_id"]
        == architecture.artifact_id
    )
    assert revision.payload["source_attempt"] == 2


def test_failed_research_is_recorded_without_starting_development(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, RecordingBackend())
    change = coordinator.start("Goal", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    item = work.require(research.work_id)
    work.save(item.transition(WorkState.FAILED), expected_version=item.version)
    coordinator.reconcile_for_work(research.work_id)
    assert changes.require(change.change_id).state is ChangeState.FAILED
    assert len(changes.list_stages(change.change_id)) == 1


def test_contract_failure_recovery_reuses_approved_architecture_once(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = coordinator.start("Build media adapter", "session", "turn")
    research = changes.list_stages(change.change_id)[0]
    _complete(work, work.require(research.work_id))
    coordinator.reconcile_for_work(research.work_id)

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"transport": "approved"},
    )
    coordinator.reconcile(change.change_id)
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
        source_session_id="session",
        source_turn_id="approval",
        request_key="session:approval",
        verification_id="verification_demo",
        verifier_id="test_verifier",
    )
    coordinator.reconcile(change.change_id)

    development = changes.list_stages(change.change_id)[1]
    item = work.require(development.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    step = WorkStep(
        work_id=running.work_id,
        kind="phase9_development_engine",
        summary="Run DevelopmentEngine",
    )
    work.add_step(step)
    completed_step = step.start().complete(
        {
            "development_result": {
                "disposition": "failed",
                "reason": (
                    "The approved ChatGPT-plan/Codex engineering target returned a "
                    "non-retryable failure (response_contract_invalid)."
                ),
            }
        }
    )
    work.save_step(completed_step)
    failed = work.save(
        running.transition(
            WorkState.FAILED,
            status_detail="response contract invalid",
            current_step_id=step.step_id,
        ),
        expected_version=running.version,
    )
    coordinator.reconcile_for_work(failed.work_id)
    assert changes.require(change.change_id).state is ChangeState.FAILED

    recovered = changes.reopen_recoverable_development_engine_failures(
        recovery_generation="codex-contract-repair-v1",
    )
    assert recovered == (change.change_id,)

    coordinator.reconcile(change.change_id)
    stages = changes.list_stages(change.change_id)
    assert len(stages) == 3
    assert stages[-1].stage_key == development.stage_key
    assert stages[-1].attempt == development.attempt + 1
    assert stages[-1].work_id != development.work_id
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING

    # The same runtime generation cannot silently reopen the same historical failure
    # again on another restart.
    assert (
        changes.reopen_recoverable_development_engine_failures(
            recovery_generation="codex-contract-repair-v1",
        )
        == ()
    )
