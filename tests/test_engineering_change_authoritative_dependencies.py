from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkType
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


def test_superseded_source_dependency_recovers_with_fresh_development_attempt(
    tmp_path,
) -> None:
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

    stale_source = changes.link_work(
        change.change_id,
        "research",
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
            status_detail="historical provider failure",
        ),
        expected_version=stale_running.version,
    )

    current_source = changes.link_work(
        change.change_id,
        "research",
        2,
        _research(change.change_id, 2),
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
        dependencies=(stale_source.work_id,),
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
    assert events[0]["detail"]["authoritative_source_work_id"] == current_source.work_id
