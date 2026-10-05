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
