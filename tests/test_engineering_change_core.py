from __future__ import annotations

import sqlite3

import pytest

from jarvis.engineering_change import (
    ChangeConflict,
    ChangeState,
    ChangeStore,
    UnsupportedProcess,
)
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
