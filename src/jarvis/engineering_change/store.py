"""Canonical change records alongside WorkItems in the protected work database."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime

import rfc8785

from jarvis.work.models import WorkItem
from jarvis.work.store import SQLiteWorkStore

from .models import (
    TRANSITIONS,
    ChangeArtifact,
    ChangeConflict,
    ChangeStage,
    ChangeState,
    EngineeringChange,
    UnsupportedProcess,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


class ChangeStore:
    """Transactional change/work ownership; DBOS is still the execution backend."""

    SUPPORTED = frozenset({("engineering.change", 1)})

    def __init__(self, work: SQLiteWorkStore) -> None:
        self.work = work
        with work._lock, work._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS engineering_changes (
                    change_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    process_key TEXT NOT NULL,
                    process_version INTEGER NOT NULL CHECK(process_version > 0),
                    source_session_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_session_id, source_turn_id, process_key)
                );
                CREATE TABLE IF NOT EXISTS engineering_change_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
                    kind TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    digest TEXT NOT NULL CHECK(length(digest) = 64),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(change_id, kind, revision)
                );
                CREATE TABLE IF NOT EXISTS engineering_change_stages (
                    change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
                    stage_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK(attempt > 0),
                    work_id TEXT NOT NULL UNIQUE REFERENCES work_items(work_id),
                    PRIMARY KEY(change_id, stage_key, attempt)
                );
                CREATE TABLE IF NOT EXISTS engineering_change_events (
                    event_id TEXT PRIMARY KEY,
                    change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
                    event_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(change_id, event_key)
                );
                CREATE INDEX IF NOT EXISTS idx_change_state_updated
                    ON engineering_changes(state, updated_at);
                CREATE TABLE IF NOT EXISTS engineering_change_gates (
                    gate_id TEXT PRIMARY KEY,
                    change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
                    kind TEXT NOT NULL,
                    artifact_id TEXT NOT NULL REFERENCES engineering_change_artifacts(artifact_id),
                    artifact_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(change_id, kind, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_change_decisions (
                    gate_id TEXT PRIMARY KEY REFERENCES engineering_change_gates(gate_id),
                    approved INTEGER NOT NULL CHECK(approved IN (0, 1)),
                    actor_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    request_key TEXT NOT NULL UNIQUE,
                    decided_at TEXT NOT NULL
                );
                """
            )

    def _from_row(self, row: sqlite3.Row) -> EngineeringChange:
        result = EngineeringChange(
            change_id=row["change_id"],
            request=self.work._decode_text(row["request"]),
            process_key=row["process_key"],
            process_version=row["process_version"],
            source_session_id=row["source_session_id"],
            source_turn_id=row["source_turn_id"],
            state=ChangeState(row["state"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        self._assert_supported(result.process_key, result.process_version)
        return result

    @classmethod
    def _assert_supported(cls, key: str, version: int) -> None:
        if (key, version) not in cls.SUPPORTED:
            raise UnsupportedProcess(f"unsupported change process: {key}/{version}")

    def create(
        self,
        *,
        request: str,
        process_key: str,
        process_version: int,
        source_session_id: str,
        source_turn_id: str,
    ) -> EngineeringChange:
        self._assert_supported(process_key, process_version)
        if not all(
            (request.strip(), source_session_id.strip(), source_turn_id.strip())
        ):
            raise ChangeConflict("change request and source must not be empty")
        with self.work._lock, self.work._connect() as connection:
            existing = connection.execute(
                """SELECT * FROM engineering_changes
                WHERE source_session_id=? AND source_turn_id=? AND process_key=?""",
                (source_session_id, source_turn_id, process_key),
            ).fetchone()
            if existing is not None:
                item = self._from_row(existing)
                if item.request != request or item.process_version != process_version:
                    raise ChangeConflict("source turn already owns a different change")
                return item
            change_id = "change_" + uuid.uuid4().hex[:16]
            timestamp = _now()
            connection.execute(
                """INSERT INTO engineering_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    change_id,
                    self.work._encode_text(request),
                    process_key,
                    process_version,
                    source_session_id,
                    source_turn_id,
                    ChangeState.PROPOSED.value,
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            return self._from_row(
                connection.execute(
                    "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
                ).fetchone()
            )

    def get(self, change_id: str) -> EngineeringChange | None:
        with self.work._lock, self.work._connect() as connection:
            row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
            ).fetchone()
            return None if row is None else self._from_row(row)

    def require(self, change_id: str) -> EngineeringChange:
        result = self.get(change_id)
        if result is None:
            raise ChangeConflict(f"unknown change: {change_id}")
        return result

    def find_by_source(
        self, source_session_id: str, source_turn_id: str, process_key: str
    ) -> EngineeringChange | None:
        with self.work._lock, self.work._connect() as db:
            row = db.execute(
                """SELECT * FROM engineering_changes WHERE source_session_id=?
                AND source_turn_id=? AND process_key=?""",
                (source_session_id, source_turn_id, process_key),
            ).fetchone()
            return None if row is None else self._from_row(row)

    def active_ids(self) -> tuple[str, ...]:
        terminal = ("closed", "rejected", "failed", "superseded", "rolled_back")
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT change_id FROM engineering_changes
                WHERE state NOT IN (?, ?, ?, ?, ?) ORDER BY created_at""",
                terminal,
            ).fetchall()
        return tuple(row["change_id"] for row in rows)

    def latest_artifact(self, change_id: str, kind: str) -> ChangeArtifact | None:
        with self.work._lock, self.work._connect() as db:
            row = db.execute(
                """SELECT artifact_id FROM engineering_change_artifacts
                WHERE change_id=? AND kind=? ORDER BY revision DESC LIMIT 1""",
                (change_id, kind),
            ).fetchone()
        return None if row is None else self.get_artifact(row["artifact_id"])

    def list_stages(self, change_id: str) -> tuple[ChangeStage, ...]:
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT * FROM engineering_change_stages WHERE change_id=?
                ORDER BY rowid""",
                (change_id,),
            ).fetchall()
        return tuple(
            ChangeStage(
                row["change_id"], row["stage_key"], row["attempt"], row["work_id"]
            )
            for row in rows
        )

    def stage_for_work(self, work_id: str) -> ChangeStage | None:
        with self.work._lock, self.work._connect() as db:
            row = db.execute(
                "SELECT * FROM engineering_change_stages WHERE work_id=?", (work_id,)
            ).fetchone()
        return (
            None
            if row is None
            else ChangeStage(
                row["change_id"], row["stage_key"], row["attempt"], row["work_id"]
            )
        )

    def work_admitted(self, work_id: str) -> bool:
        """Existing direct WorkItems are unaffected; change WorkItems need current gates."""
        with self.work._lock, self.work._connect() as db:
            stage = db.execute(
                "SELECT change_id, stage_key FROM engineering_change_stages WHERE work_id=?",
                (work_id,),
            ).fetchone()
            if stage is None:
                return True
            row = db.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (stage["change_id"],),
            ).fetchone()
            if row is None:
                return False
            try:
                self._admit_stage(db, self._from_row(row), stage["stage_key"])
            except (ChangeConflict, UnsupportedProcess):
                return False
            return True

    @staticmethod
    def _admit_stage(
        db: sqlite3.Connection, change: EngineeringChange, stage_key: str
    ) -> None:
        if stage_key == "research":
            if change.state is not ChangeState.RESEARCHING:
                raise ChangeConflict("research stage is not admitted")
            return
        if stage_key != "development" or change.state not in {
            ChangeState.APPROVED_FOR_BUILD,
            ChangeState.DEVELOPING,
        }:
            raise ChangeConflict("stage is not admitted by change lifecycle")
        latest = db.execute(
            """SELECT artifact_id, digest FROM engineering_change_artifacts
            WHERE change_id=? AND kind='architecture' ORDER BY revision DESC LIMIT 1""",
            (change.change_id,),
        ).fetchone()
        if (
            latest is None
            or db.execute(
                """SELECT 1 FROM engineering_change_gates AS gate
            JOIN engineering_change_decisions AS decision USING (gate_id)
            WHERE gate.change_id=? AND gate.kind='architecture'
            AND gate.artifact_id=? AND gate.artifact_digest=? AND decision.approved=1""",
                (change.change_id, latest["artifact_id"], latest["digest"]),
            ).fetchone()
            is None
        ):
            raise ChangeConflict("current architecture has no owner approval")

    def transition(
        self, change_id: str, state: ChangeState, *, expected_version: int
    ) -> EngineeringChange:
        with self.work._lock, self.work._connect() as connection:
            row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
            ).fetchone()
            if row is None:
                raise ChangeConflict("unknown change")
            current = self._from_row(row)
            if (
                current.version != expected_version
                or state not in TRANSITIONS[current.state]
            ):
                raise ChangeConflict("stale or invalid change transition")
            if state in {
                ChangeState.APPROVED_FOR_BUILD,
                ChangeState.READY_FOR_PROMOTION,
                ChangeState.PROMOTED,
            }:
                raise ChangeConflict(
                    "gate-controlled transition requires verified evidence"
                )
            connection.execute(
                """UPDATE engineering_changes SET state=?, version=?, updated_at=?
                WHERE change_id=? AND version=?""",
                (state.value, current.version + 1, _now(), change_id, expected_version),
            )
            return self._from_row(
                connection.execute(
                    "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
                ).fetchone()
            )

    def add_artifact(
        self, change_id: str, *, kind: str, payload: dict[str, object]
    ) -> ChangeArtifact:
        if not kind.strip() or not isinstance(payload, dict):
            raise ChangeConflict("artifact kind and object payload are required")
        digest = _digest(payload)
        with self.work._lock, self.work._connect() as connection:
            self._require_row(connection, change_id)
            revision = connection.execute(
                """SELECT COALESCE(MAX(revision), 0) + 1
                FROM engineering_change_artifacts WHERE change_id=? AND kind=?""",
                (change_id, kind),
            ).fetchone()[0]
            artifact = ChangeArtifact(
                artifact_id="artifact_" + uuid.uuid4().hex[:16],
                change_id=change_id,
                kind=kind,
                revision=revision,
                digest=digest,
                payload=dict(payload),
                created_at=_now(),
            )
            connection.execute(
                """INSERT INTO engineering_change_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    change_id,
                    kind,
                    revision,
                    digest,
                    self.work._encode_json(payload),
                    artifact.created_at,
                ),
            )
            return artifact

    def get_artifact(self, artifact_id: str) -> ChangeArtifact | None:
        with self.work._lock, self.work._connect() as connection:
            row = connection.execute(
                "SELECT * FROM engineering_change_artifacts WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                return None
            payload = self.work._decode_json(row["payload"])
            if _digest(payload) != row["digest"]:
                raise ChangeConflict("artifact integrity mismatch")
            return ChangeArtifact(
                row["artifact_id"],
                row["change_id"],
                row["kind"],
                row["revision"],
                row["digest"],
                payload,
                row["created_at"],
            )

    @staticmethod
    def _require_row(connection: sqlite3.Connection, change_id: str) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM engineering_changes WHERE change_id=?", (change_id,)
            ).fetchone()
            is None
        ):
            raise ChangeConflict("unknown change")

    def link_work(
        self, change_id: str, stage_key: str, attempt: int, item: WorkItem
    ) -> ChangeStage:
        if not stage_key.strip() or attempt < 1:
            raise ChangeConflict("invalid stage attempt")
        with self.work._lock, self.work._connect() as connection:
            change_row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
            ).fetchone()
            if change_row is None:
                raise ChangeConflict("unknown change")
            self._admit_stage(connection, self._from_row(change_row), stage_key)
            row = connection.execute(
                """SELECT work_id FROM engineering_change_stages
                WHERE change_id=? AND stage_key=? AND attempt=?""",
                (change_id, stage_key, attempt),
            ).fetchone()
            if row is not None:
                if row["work_id"] != item.work_id:
                    raise ChangeConflict(
                        "stage attempt already owns a different work item"
                    )
                return ChangeStage(change_id, stage_key, attempt, item.work_id)
            self.work._validate_dependency_graph(connection, item)
            try:
                self.work._insert_item(connection, item)
                connection.execute(
                    "INSERT INTO engineering_change_stages VALUES (?, ?, ?, ?)",
                    (change_id, stage_key, attempt, item.work_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ChangeConflict("stage WorkItem link violates identity") from exc
            return ChangeStage(change_id, stage_key, attempt, item.work_id)
