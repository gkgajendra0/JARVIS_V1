import pytest

from jarvis.conversation import ConversationSession
from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_change.models import (
    ProcessContract,
    ProcessStageContract,
    ProcessStageRole,
)
from jarvis.engineering_change.service import ChangeService
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submissions.append(work_id)
        return work_id


def _research(change_id: str, attempt: int) -> WorkItem:
    return WorkItem(
        request=f"Research attempt {attempt}",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{change_id}",
        source_turn_id=f"research:{attempt}",
    )


def _complete(work: SQLiteWorkStore, item: WorkItem) -> WorkItem:
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    return work.save(
        running.transition(WorkState.COMPLETED),
        expected_version=running.version,
    )


def test_development_depends_only_on_authoritative_research_attempt(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Build TV control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    first = changes.link_work(
        change.change_id,
        "research",
        1,
        _research(change.change_id, 1),
    )
    first_item = work.require(first.work_id)
    running_first = work.save(
        first_item.transition(WorkState.RUNNING),
        expected_version=first_item.version,
    )
    work.save(
        running_first.transition(
            WorkState.FAILED,
            status_detail="historical provider overload",
        ),
        expected_version=running_first.version,
    )

    second = changes.link_work(
        change.change_id,
        "research",
        2,
        _research(change.change_id, 2),
    )
    _complete(work, work.require(second.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "target_vendor": "hisense",
            "target_platform": "vidaa",
            "transport": "vidaa_mqtt_tls",
        },
    )
    changes.record_stage_outcome(
        change.change_id,
        second.stage_key,
        second.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

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
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )

    coordinator.reconcile(change.change_id)

    development = next(
        stage
        for stage in changes.list_stages(change.change_id)
        if stage.stage_key == "development"
    )
    development_work = work.require(development.work_id)

    assert development_work.dependencies == (second.work_id,)
    assert first.work_id not in development_work.dependencies
    assert work.require(first.work_id).state is WorkState.FAILED
    assert changes.current_stage_attempt(change.change_id, "research").work_id == (
        second.work_id
    )
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING


def test_architecture_gate_uses_authoritative_research_attempt(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "gate-authority.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Build governed media control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    historical = changes.link_work(
        change.change_id,
        "research",
        1,
        _research(change.change_id, 1),
    )
    historical_item = work.require(historical.work_id)
    historical_running = work.save(
        historical_item.transition(WorkState.RUNNING),
        expected_version=historical_item.version,
    )
    work.save(
        historical_running.transition(
            WorkState.FAILED,
            status_detail="superseded historical research failure",
        ),
        expected_version=historical_running.version,
    )

    current = changes.link_work(
        change.change_id,
        "research",
        2,
        _research(change.change_id, 2),
    )
    _complete(work, work.require(current.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "current-authoritative-research"},
    )
    changes.record_stage_outcome(
        change.change_id,
        current.stage_key,
        current.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

    gate = ChangeService(
        coordinator,
        ConversationSession(session_id="owner-session"),
    ).propose_architecture(
        change.change_id,
        architecture.payload,
    )

    assert gate.artifact_id == architecture.artifact_id
    assert changes.current_stage_attempt(change.change_id, "research").work_id == (
        current.work_id
    )
    assert work.require(historical.work_id).state is WorkState.FAILED


def test_retry_rejects_superseded_research_attempt(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "superseded-retry.sqlite3")
    changes = ChangeStore(work)

    change = changes.create(
        request="Research a governed capability.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    historical = changes.link_work(
        change.change_id,
        "research",
        1,
        _research(change.change_id, 1),
    )
    historical_item = work.require(historical.work_id)
    historical_running = work.save(
        historical_item.transition(WorkState.RUNNING),
        expected_version=historical_item.version,
    )
    work.save(
        historical_running.transition(
            WorkState.FAILED,
            status_detail="old retryable failure",
        ),
        expected_version=historical_running.version,
    )

    current = changes.link_work(
        change.change_id,
        "research",
        2,
        _research(change.change_id, 2),
    )
    current_item = work.require(current.work_id)
    current_running = work.save(
        current_item.transition(WorkState.RUNNING),
        expected_version=current_item.version,
    )
    work.save(
        current_running.transition(
            WorkState.FAILED,
            status_detail="current failure",
        ),
        expected_version=current_running.version,
    )
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=change.version,
    )

    with pytest.raises(ChangeConflict, match="superseded stage attempt"):
        changes.reopen_failed_stage_for_retry(historical.work_id)

    assert changes.require(change.change_id).state is ChangeState.FAILED


def test_superseded_source_dependency_recovers_with_fresh_development_attempt(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    acquisition_process = ProcessContract(
        key="test.owner_capability_acquisition",
        version=1,
        stages=(
            ProcessStageContract(
                stage_key="acquisition",
                work_type=WorkType.RESEARCH,
                role=ProcessStageRole.ARCHITECTURE_SOURCE,
            ),
            ProcessStageContract(
                stage_key="development",
                work_type=WorkType.DEVELOPMENT,
                role=ProcessStageRole.DEVELOPMENT,
            ),
        ),
    )
    changes = ChangeStore(work, processes=(acquisition_process,))
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Build TV control.",
        process_key=acquisition_process.key,
        process_version=acquisition_process.version,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    historical_source = changes.link_work(
        change.change_id,
        "acquisition",
        1,
        _research(change.change_id, 1),
    )
    _complete(work, work.require(historical_source.work_id))

    stale_source = changes.link_work(
        change.change_id,
        "acquisition",
        2,
        _research(change.change_id, 2),
    )
    stale_item = work.require(stale_source.work_id)
    stale_running = work.save(
        stale_item.transition(WorkState.RUNNING),
        expected_version=stale_item.version,
    )
    work.save(
        stale_running.transition(
            WorkState.FAILED,
            status_detail="historical provider failure",
        ),
        expected_version=stale_running.version,
    )

    current_source = changes.link_work(
        change.change_id,
        "acquisition",
        3,
        _research(change.change_id, 3),
    )
    _complete(work, work.require(current_source.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "target_family": "media_player.control",
            "transport": "evidence_selected_transport",
        },
    )
    changes.record_stage_outcome(
        change.change_id,
        current_source.stage_key,
        current_source.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

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
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )

    poisoned = WorkItem(
        request="Develop approved capability.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="development:1",
        dependencies=(
            historical_source.work_id,
            stale_source.work_id,
            current_source.work_id,
        ),
    )
    poisoned_stage = changes.link_work(
        change.change_id,
        "development",
        1,
        poisoned,
    )
    change = changes.require(change.change_id)
    change = changes.transition(
        change.change_id,
        ChangeState.DEVELOPING,
        expected_version=change.version,
    )
    poisoned_item = work.require(poisoned_stage.work_id)
    poisoned_running = work.save(
        poisoned_item.transition(WorkState.RUNNING),
        expected_version=poisoned_item.version,
    )
    work.save(
        poisoned_running.transition(
            WorkState.FAILED,
            status_detail=(
                "dependency did not complete successfully: " + stale_source.work_id
            ),
        ),
        expected_version=poisoned_running.version,
    )
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=change.version,
    )

    generation = "authoritative-source-dependency-test-v1"
    assert changes.reopen_recoverable_superseded_dependency_failures(
        recovery_generation=generation,
        dry_run=True,
    ) == (change.change_id,)

    recovered = changes.reopen_recoverable_superseded_dependency_failures(
        recovery_generation=generation,
    )
    assert recovered == (change.change_id,)
    assert changes.require(change.change_id).state is ChangeState.APPROVED_FOR_BUILD

    coordinator.reconcile(change.change_id)

    development_attempts = [
        item
        for item in changes.list_stage_attempts(change.change_id)
        if item.stage_key == "development"
    ]
    assert len(development_attempts) == 2
    assert development_attempts[0].authoritative is False
    assert development_attempts[0].superseded_by_attempt == 2
    assert development_attempts[1].authoritative is True

    fresh_work = work.require(development_attempts[1].work_id)
    assert fresh_work.dependencies == (current_source.work_id,)
    assert stale_source.work_id not in fresh_work.dependencies
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING

    events = [
        event
        for event in changes.list_events(change.change_id)
        if event["kind"] == "superseded_dependency_compatibility_reopened"
    ]
    assert len(events) == 1
    assert events[0]["detail"]["stale_dependency_work_id"] == stale_source.work_id
    assert events[0]["detail"]["historical_dependency_work_ids"] == [
        historical_source.work_id,
        stale_source.work_id,
    ]
    assert events[0]["detail"]["authoritative_source_work_id"] == current_source.work_id


def test_superseded_source_dependency_recovery_rejects_failed_unrelated_dependency(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    acquisition_process = ProcessContract(
        key="test.owner_capability_acquisition",
        version=1,
        stages=(
            ProcessStageContract(
                stage_key="acquisition",
                work_type=WorkType.RESEARCH,
                role=ProcessStageRole.ARCHITECTURE_SOURCE,
            ),
            ProcessStageContract(
                stage_key="development",
                work_type=WorkType.DEVELOPMENT,
                role=ProcessStageRole.DEVELOPMENT,
            ),
        ),
    )
    changes = ChangeStore(work, processes=(acquisition_process,))

    change = changes.create(
        request="Build governed media control.",
        process_key=acquisition_process.key,
        process_version=acquisition_process.version,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    stale_source = changes.link_work(
        change.change_id,
        "acquisition",
        1,
        _research(change.change_id, 1),
    )
    stale_item = work.require(stale_source.work_id)
    stale_running = work.save(
        stale_item.transition(WorkState.RUNNING),
        expected_version=stale_item.version,
    )
    work.save(
        stale_running.transition(
            WorkState.FAILED,
            status_detail="historical source failure",
        ),
        expected_version=stale_running.version,
    )

    current_source = changes.link_work(
        change.change_id,
        "acquisition",
        2,
        _research(change.change_id, 2),
    )
    _complete(work, work.require(current_source.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"target_family": "media_player.control"},
    )
    changes.record_stage_outcome(
        change.change_id,
        current_source.stage_key,
        current_source.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

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
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )

    unrelated = WorkItem(
        request="Independent prerequisite.",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="other-session",
        source_turn_id="other-turn",
    )
    unrelated = work.create(unrelated)
    unrelated_running = work.save(
        unrelated.transition(WorkState.RUNNING),
        expected_version=unrelated.version,
    )
    unrelated_failed = work.save(
        unrelated_running.transition(
            WorkState.FAILED,
            status_detail="real unrelated blocker",
        ),
        expected_version=unrelated_running.version,
    )

    poisoned = WorkItem(
        request="Develop approved capability.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="development:1",
        dependencies=(
            stale_source.work_id,
            current_source.work_id,
            unrelated_failed.work_id,
        ),
    )
    poisoned_stage = changes.link_work(
        change.change_id,
        "development",
        1,
        poisoned,
    )
    change = changes.require(change.change_id)
    change = changes.transition(
        change.change_id,
        ChangeState.DEVELOPING,
        expected_version=change.version,
    )
    poisoned_item = work.require(poisoned_stage.work_id)
    poisoned_running = work.save(
        poisoned_item.transition(WorkState.RUNNING),
        expected_version=poisoned_item.version,
    )
    work.save(
        poisoned_running.transition(
            WorkState.FAILED,
            status_detail=(
                "dependency did not complete successfully: " + stale_source.work_id
            ),
        ),
        expected_version=poisoned_running.version,
    )
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=change.version,
    )

    generation = "authoritative-source-dependency-test-v1"
    diagnosis = changes.diagnose_superseded_dependency_recovery(
        change.change_id,
        recovery_generation=generation,
    )
    assert diagnosis["eligible"] is False
    assert diagnosis["failed_condition"] == "unrelated_dependency_not_completed"
    assert (
        changes.reopen_recoverable_superseded_dependency_failures(
            recovery_generation=generation,
            dry_run=True,
        )
        == ()
    )


def test_completed_response_contract_failure_after_system_retry_recovers_fresh_attempt(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Build governed media control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    source = changes.link_work(
        change.change_id,
        "research",
        1,
        _research(change.change_id, 1),
    )
    _complete(work, work.require(source.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"target_family": "media_player.control"},
    )
    changes.record_stage_outcome(
        change.change_id,
        source.stage_key,
        source.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

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
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )

    coordinator.reconcile(change.change_id)

    development = changes.current_stage_attempt(change.change_id, "development")
    assert development is not None
    item = work.require(development.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )

    engine_result = {
        "disposition": "failed",
        "summary": "Engineering response contract was invalid.",
        "reason": (
            "The approved ChatGPT-plan/Codex engineering target returned a "
            "non-retryable failure (response_contract_invalid)."
        ),
        "blocker_code": "response_contract_invalid",
    }
    engine_step = WorkStep(
        work_id=running.work_id,
        kind="dev_engine_execute",
        summary="Run governed engineering specialist",
    )
    work.add_step(engine_step)
    work.save_step(engine_step.start().complete({"development_result": engine_result}))

    system_retry = WorkStep(
        work_id=running.work_id,
        kind="system_retry",
        summary="JARVIS requested retry of retryable failed work",
        input_data={"source": "global_supervisor"},
    )
    work.add_step(system_retry)
    work.save_step(
        system_retry.start().complete(
            {"reason": "Retry deterministic retryable failed work."}
        )
    )

    completed = running.transition(
        WorkState.COMPLETED,
        status_detail="DevelopmentEngine returned failed.",
        result={"development_engine": engine_result},
    )
    work.save(completed, expected_version=running.version)

    current = changes.require(change.change_id)
    assert current.state is ChangeState.DEVELOPING
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=current.version,
    )

    generation = "phase9-system-retry-completed-child-test-v1"
    assert changes.reopen_recoverable_development_engine_failures(
        recovery_generation=generation,
        dry_run=True,
    ) == (change.change_id,)

    recovered = changes.reopen_recoverable_development_engine_failures(
        recovery_generation=generation,
    )
    assert recovered == (change.change_id,)
    assert changes.require(change.change_id).state is ChangeState.APPROVED_FOR_BUILD

    coordinator.reconcile(change.change_id)

    attempts = [
        stage
        for stage in changes.list_stage_attempts(change.change_id)
        if stage.stage_key == "development"
    ]
    assert len(attempts) == 2
    assert attempts[0].authoritative is False
    assert attempts[0].superseded_by_attempt == 2
    assert attempts[1].authoritative is True
    assert attempts[1].work_id != attempts[0].work_id
    assert work.require(attempts[0].work_id).state is WorkState.COMPLETED
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING


def test_missing_architecture_revision_evidence_failure_recovers_fresh_attempt(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Build governed media control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    source = changes.link_work(
        change.change_id,
        "research",
        1,
        _research(change.change_id, 1),
    )
    _complete(work, work.require(source.work_id))

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"target_family": "media_player.control"},
    )
    changes.record_stage_outcome(
        change.change_id,
        source.stage_key,
        source.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )

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
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )

    coordinator.reconcile(change.change_id)

    development = changes.current_stage_attempt(change.change_id, "development")
    assert development is not None
    item = work.require(development.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )

    reason = (
        "Codex requested architecture revision without exact canonical "
        "evidence references."
    )
    engine_result = {
        "disposition": "failed",
        "summary": "Architecture revision request failed evidence validation.",
        "reason": reason,
        "blocker_code": None,
    }
    engine_step = WorkStep(
        work_id=running.work_id,
        kind="dev_engine_execute",
        summary="Run governed engineering specialist",
    )
    work.add_step(engine_step)
    work.save_step(engine_step.start().complete({"development_result": engine_result}))
    work.save(
        running.transition(
            WorkState.FAILED,
            status_detail=reason,
        ),
        expected_version=running.version,
    )

    current = changes.require(change.change_id)
    assert current.state is ChangeState.DEVELOPING
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=current.version,
    )

    generation = "architecture-revision-evidence-contract-test-v1"
    assert changes.reopen_recoverable_development_engine_failures(
        recovery_generation=generation,
        dry_run=True,
    ) == (change.change_id,)

    recovered = changes.reopen_recoverable_development_engine_failures(
        recovery_generation=generation,
    )
    assert recovered == (change.change_id,)
    assert changes.require(change.change_id).state is ChangeState.APPROVED_FOR_BUILD

    coordinator.reconcile(change.change_id)

    attempts = [
        stage
        for stage in changes.list_stage_attempts(change.change_id)
        if stage.stage_key == "development"
    ]
    assert len(attempts) == 2
    assert attempts[0].authoritative is False
    assert attempts[0].superseded_by_attempt == 2
    assert attempts[1].authoritative is True
    assert attempts[1].work_id != attempts[0].work_id
    assert work.require(attempts[0].work_id).state is WorkState.FAILED
    assert changes.require(change.change_id).state is ChangeState.DEVELOPING


def test_provisional_candidate_collision_recovery_creates_fresh_source_attempt(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    acquisition_process = ProcessContract(
        key="test.owner_capability_acquisition.provisional-recovery",
        version=1,
        stages=(
            ProcessStageContract(
                stage_key="acquisition",
                work_type=WorkType.RESEARCH,
                role=ProcessStageRole.ARCHITECTURE_SOURCE,
            ),
            ProcessStageContract(
                stage_key="development",
                work_type=WorkType.DEVELOPMENT,
                role=ProcessStageRole.DEVELOPMENT,
            ),
        ),
    )
    changes = ChangeStore(work, processes=(acquisition_process,))
    backend = RecordingBackend()
    coordinator = ChangeCoordinator(changes, backend)

    change = changes.create(
        request="Acquire governed media control.",
        process_key=acquisition_process.key,
        process_version=acquisition_process.version,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )

    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"target_family": "media_player.control"},
    )
    changes.add_artifact(
        change.change_id,
        kind="architecture_revision_request",
        payload={
            "previous_architecture_artifact_id": architecture.artifact_id,
            "source_attempt": 1,
            "reason": "Development requires a replacement dependency lock.",
        },
    )

    source = changes.link_work(
        change.change_id,
        "acquisition",
        1,
        _research(change.change_id, 1),
    )
    item = work.require(source.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    contradiction = (
        "AcquisitionResolutionError: one immutable source identity produced "
        "contradictory candidate evidence"
    )
    resolve_step = WorkStep(
        work_id=running.work_id,
        kind="acq_resolve",
        summary="Resolve acquisition candidates",
    )
    work.add_step(resolve_step)
    work.save_step(resolve_step.start().fail(contradiction))
    work.save(
        running.transition(
            WorkState.FAILED,
            status_detail=f"step failed: acq_resolve: {contradiction}",
        ),
        expected_version=running.version,
    )

    current = changes.require(change.change_id)
    changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=current.version,
    )

    generation = "phase9-provisional-candidate-resolution-test-v1"
    assert changes.reopen_recoverable_provisional_candidate_resolution_failures(
        recovery_generation=generation,
        dry_run=True,
    ) == (change.change_id,)

    recovered = changes.reopen_recoverable_provisional_candidate_resolution_failures(
        recovery_generation=generation,
    )
    assert recovered == (change.change_id,)
    assert changes.require(change.change_id).state is ChangeState.RESEARCHING
    assert work.require(source.work_id).state is WorkState.FAILED

    coordinator.reconcile(change.change_id)

    attempts = [
        stage
        for stage in changes.list_stage_attempts(change.change_id)
        if stage.stage_key == "acquisition"
    ]
    assert len(attempts) == 2
    assert attempts[0].authoritative is False
    assert attempts[0].superseded_by_attempt == 2
    assert attempts[1].attempt == 2
    assert attempts[1].authoritative is True
    assert attempts[1].work_id != attempts[0].work_id
    assert work.require(attempts[0].work_id).state is WorkState.FAILED

    events = [
        event
        for event in changes.list_events(change.change_id)
        if event["kind"] == "provisional_candidate_resolution_compatibility_reopened"
    ]
    assert len(events) == 1
    assert events[0]["detail"]["failed_source_attempt"] == 1
    assert events[0]["detail"]["replacement_source_attempt"] == 2
