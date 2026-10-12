from jarvis.engineering_change import (
    ChangeState,
    ChangeStore,
    StageAttemptStatus,
)
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


def _research_item(change_id: str, attempt: int) -> WorkItem:
    return WorkItem(
        request=f"Research architecture attempt {attempt}.",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{change_id}",
        source_turn_id=f"research:{attempt}",
    )


def test_replacement_stage_attempt_supersedes_without_rewriting_history(
    tmp_path,
) -> None:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(path)
    changes = ChangeStore(work)
    change = changes.create(
        request="Build TV control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="session",
        source_turn_id="turn",
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
        _research_item(change.change_id, 1),
    )
    failed = work.require(first.work_id)
    work.save(
        failed.transition(WorkState.FAILED, status_detail="provider overloaded"),
        expected_version=failed.version,
    )

    second = changes.link_work(
        change.change_id,
        "research",
        2,
        _research_item(change.change_id, 2),
    )

    attempts = changes.list_stage_attempts(change.change_id)
    assert [(item.attempt, item.status, item.authoritative) for item in attempts] == [
        (1, StageAttemptStatus.SUPERSEDED, False),
        (2, StageAttemptStatus.CURRENT, True),
    ]
    assert attempts[0].superseded_by_attempt == 2
    assert work.require(first.work_id).state is WorkState.FAILED
    assert work.require(second.work_id).state is WorkState.QUEUED

    supersession_events = [
        event
        for event in changes.list_events(change.change_id)
        if event["kind"] == "stage_attempt_superseded"
    ]
    assert len(supersession_events) == 1
    assert supersession_events[0]["detail"] == {
        "stage_key": "research",
        "attempt": 1,
        "work_id": first.work_id,
        "superseded_by_attempt": 2,
        "superseded_by_work_id": second.work_id,
    }


def test_stage_output_binding_is_idempotent_and_restart_durable(tmp_path) -> None:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(path)
    changes = ChangeStore(work)
    change = changes.create(
        request="Build TV control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="session",
        source_turn_id="turn",
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )
    stage = changes.link_work(
        change.change_id,
        "research",
        1,
        _research_item(change.change_id, 1),
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"transport": "vidaa_mqtt_tls"},
    )

    first = changes.record_stage_outcome(
        change.change_id,
        stage.stage_key,
        stage.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    repeated = changes.record_stage_outcome(
        change.change_id,
        stage.stage_key,
        stage.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )

    assert repeated == first
    assert first.status is StageAttemptStatus.ACCEPTED
    assert first.authoritative is True
    assert first.produced_artifact_ids == (architecture.artifact_id,)
    assert changes.current_stage_attempt(change.change_id, "research") == first

    reopened = ChangeStore(SQLiteWorkStore(path))
    assert reopened.list_stage_attempts(change.change_id) == (first,)
    assert reopened.current_stage_attempt(change.change_id, "research") == first
    outcome_events = [
        event
        for event in reopened.list_events(change.change_id)
        if event["kind"] == "stage_attempt_outcome"
    ]
    assert len(outcome_events) == 1


def test_new_attempt_supersedes_previously_accepted_attempt(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    change = changes.create(
        request="Build TV control.",
        process_key="engineering.change",
        process_version=1,
        source_session_id="session",
        source_turn_id="turn",
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
        _research_item(change.change_id, 1),
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"revision": 1},
    )
    accepted = changes.record_stage_outcome(
        change.change_id,
        first.stage_key,
        first.attempt,
        produced_artifact_id=architecture.artifact_id,
        accepted=True,
    )
    assert accepted.status is StageAttemptStatus.ACCEPTED

    second = changes.link_work(
        change.change_id,
        "research",
        2,
        _research_item(change.change_id, 2),
    )
    attempts = changes.list_stage_attempts(change.change_id)

    assert attempts[0].status is StageAttemptStatus.SUPERSEDED
    assert attempts[0].authoritative is False
    assert attempts[0].produced_artifact_ids == (architecture.artifact_id,)
    assert attempts[1].work_id == second.work_id
    assert attempts[1].status is StageAttemptStatus.CURRENT
    assert attempts[1].authoritative is True
