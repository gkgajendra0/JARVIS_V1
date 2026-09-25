from __future__ import annotations

import sqlite3

import pytest

from jarvis.engineering_change import (
    ChangeConflict,
    ChangeState,
    ChangeStore,
    UnsupportedProcess,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.models import ProcessContract
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


def test_one_owner_goal_has_durable_identity_and_rejects_duplicate(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    first = changes.create(
        request="Add CCTV alerts",
        process_key="engineering.change",
        process_version=1,
        source_session_id="session-1",
        source_turn_id="turn-1",
    )
    assert first.state is ChangeState.PROPOSED
    assert ChangeStore(SQLiteWorkStore(work.path)).get(first.change_id) == first
    assert (
        changes.create(
            request="Add CCTV alerts",
            process_key="engineering.change",
            process_version=1,
            source_session_id="session-1",
            source_turn_id="turn-1",
        )
        == first
    )
    with pytest.raises(ChangeConflict):
        changes.create(
            request="Different request",
            process_key="engineering.change",
            process_version=1,
            source_session_id="session-1",
            source_turn_id="turn-1",
        )


def test_unknown_process_version_and_invalid_transition_fail_closed(tmp_path) -> None:
    changes = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    with pytest.raises(UnsupportedProcess):
        changes.create(
            request="Goal",
            process_key="engineering.change",
            process_version=99,
            source_session_id="s",
            source_turn_id="t",
        )
    item = changes.create(
        request="Goal",
        process_key="engineering.change",
        process_version=1,
        source_session_id="s",
        source_turn_id="t",
    )
    with pytest.raises(ChangeConflict):
        changes.transition(item.change_id, ChangeState.DEVELOPING, expected_version=1)


def test_registered_versioned_process_is_open_ended_and_fail_closed_on_restart(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    registry = (ProcessContract("investigation.unknown", 2),)
    changes = ChangeStore(work, processes=registry)
    change = changes.create(
        request="Investigate new crash",
        process_key="investigation.unknown",
        process_version=2,
        source_session_id="s",
        source_turn_id="t",
    )
    assert changes.get(change.change_id) == change
    without_handler = ChangeStore(SQLiteWorkStore(work.path))
    with pytest.raises(UnsupportedProcess):
        without_handler.require(change.change_id)
    ChangeCoordinator(without_handler, backend=object()).reconcile_active()


def test_artifacts_are_immutable_digest_bound_and_work_link_is_atomic(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    change = changes.create(
        request="Implement alert",
        process_key="engineering.change",
        process_version=1,
        source_session_id="s",
        source_turn_id="t",
    )
    artifact = changes.add_artifact(
        change.change_id, kind="architecture", payload={"scope": "camera", "risk": 2}
    )
    assert len(artifact.digest) == 64
    assert changes.get_artifact(artifact.artifact_id) == artifact
    next_artifact = changes.add_artifact(
        change.change_id, kind="architecture", payload={"scope": "gate", "risk": 2}
    )
    assert next_artifact.revision == 2
    child = WorkItem(
        request="Research API",
        work_type=WorkType.RESEARCH,
        source_session_id="change:" + change.change_id,
        source_turn_id="research:1",
    )
    changes.transition(change.change_id, ChangeState.RESEARCHING, expected_version=1)
    stage = changes.link_work(change.change_id, "research", 1, child)
    assert stage.work_id == child.work_id
    assert work.require(child.work_id) == child
    assert changes.link_work(change.change_id, "research", 1, child) == stage
    with pytest.raises(ChangeConflict):
        changes.link_work(
            change.change_id,
            "research",
            1,
            WorkItem(
                request="Other",
                work_type=WorkType.RESEARCH,
                source_session_id="other",
                source_turn_id="other",
            ),
        )
    with sqlite3.connect(work.path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_change_schema_checksum_rejects_unknown_migration(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    ChangeStore(work)
    with sqlite3.connect(work.path) as db:
        db.execute(
            "UPDATE engineering_change_schema SET checksum='tampered' WHERE version=2"
        )
    with pytest.raises(ChangeConflict, match="schema checksum"):
        ChangeStore(SQLiteWorkStore(work.path))


def test_prior_draft_stage_schema_migrates_additively(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    ChangeStore(work)
    with sqlite3.connect(work.path) as db:
        db.execute("DELETE FROM engineering_change_schema")
        db.execute("ALTER TABLE engineering_change_stages DROP COLUMN plan_artifact_id")
    ChangeStore(SQLiteWorkStore(work.path))
    with sqlite3.connect(work.path) as db:
        assert "plan_artifact_id" in {
            column[1]
            for column in db.execute("PRAGMA table_info(engineering_change_stages)")
        }


def test_change_events_are_append_only_and_follow_canonical_operations(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    change = changes.create(
        request="Investigate",
        process_key="engineering.change",
        process_version=1,
        source_session_id="s",
        source_turn_id="t",
    )
    changes.transition(change.change_id, ChangeState.RESEARCHING, expected_version=1)
    changes.add_artifact(
        change.change_id, kind="architecture", payload={"plan": "review"}
    )
    events = changes.list_events(change.change_id)
    assert [event["kind"] for event in events] == ["created", "transition", "artifact"]
    assert len({event["event_key"] for event in events}) == 3
    with pytest.raises(sqlite3.IntegrityError), sqlite3.connect(work.path) as db:
        db.execute(
            "INSERT INTO engineering_change_events VALUES (?, ?, ?, ?, ?, ?)",
            (
                "duplicate",
                change.change_id,
                events[0]["event_key"],
                "fake",
                "{}",
                "now",
            ),
        )
