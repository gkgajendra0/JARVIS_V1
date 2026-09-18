"""SQLite canonical store for JARVIS WorkItems and WorkSteps."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Iterable

from jarvis.work.models import (
    DeliveryPolicy,
    WorkDelivery,
    WorkDeliveryKind,
    WorkDeliveryState,
    WorkItem,
    WorkPriority,
    WorkState,
    WorkStep,
    WorkStepState,
    WorkType,
)


class WorkStoreError(RuntimeError):
    pass


def default_work_state_dir() -> pathlib.Path:
    if os.name == "nt":
        base = pathlib.Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(pathlib.Path.home() / "AppData" / "Local"),
            )
        )
    else:
        base = pathlib.Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(pathlib.Path.home() / ".local" / "state"),
            )
        )
    path = base / "JARVIS" / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def default_work_store_path() -> pathlib.Path:
    return default_work_state_dir() / "work.sqlite3"


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkStoreError("stored work timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


class SQLiteWorkStore:
    """JARVIS-owned durable domain truth; DBOS remains the execution engine."""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    work_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    work_type TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    delivery_policy TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    paused_from_state TEXT,
                    current_step_id TEXT,
                    result_json TEXT NOT NULL,
                    status_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    policy TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id),
                    UNIQUE(work_id, event_key)
                );

                CREATE TABLE IF NOT EXISTS work_steps (
                    step_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    state TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_work_items_state
                    ON work_items(state, priority DESC, created_at ASC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_work_items_source_turn_type
                    ON work_items(source_session_id, source_turn_id, work_type);
                CREATE INDEX IF NOT EXISTS idx_work_steps_work
                    ON work_steps(work_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_work_deliveries_pending
                    ON work_deliveries(state, created_at ASC);
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(work_items)").fetchall()
            }
            if "dependencies_json" not in columns:
                connection.execute(
                    "ALTER TABLE work_items "
                    "ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "paused_from_state" not in columns:
                connection.execute(
                    "ALTER TABLE work_items ADD COLUMN paused_from_state TEXT"
                )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> WorkItem:
        created_at = _parse_dt(row["created_at"])
        updated_at = _parse_dt(row["updated_at"])
        if created_at is None or updated_at is None:
            raise WorkStoreError("stored work item is missing timestamps")
        return WorkItem(
            work_id=row["work_id"],
            request=row["request"],
            work_type=WorkType(row["work_type"]),
            source_session_id=row["source_session_id"],
            source_turn_id=row["source_turn_id"],
            state=WorkState(row["state"]),
            priority=WorkPriority(row["priority"]),
            delivery_policy=DeliveryPolicy(row["delivery_policy"]),
            dependencies=tuple(json.loads(row["dependencies_json"])),
            paused_from_state=(
                WorkState(row["paused_from_state"])
                if row["paused_from_state"] is not None
                else None
            ),
            current_step_id=row["current_step_id"],
            result=json.loads(row["result_json"]),
            status_detail=row["status_detail"],
            created_at=created_at,
            updated_at=updated_at,
            version=row["version"],
        )

    @staticmethod
    def _delivery_from_row(row: sqlite3.Row) -> WorkDelivery:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise WorkStoreError("stored work delivery is missing created_at")
        return WorkDelivery(
            delivery_id=row["delivery_id"],
            work_id=row["work_id"],
            kind=WorkDeliveryKind(row["kind"]),
            message=row["message"],
            policy=DeliveryPolicy(row["policy"]),
            event_key=row["event_key"],
            state=WorkDeliveryState(row["state"]),
            created_at=created_at,
            delivered_at=_parse_dt(row["delivered_at"]),
        )

    @staticmethod
    def _step_from_row(row: sqlite3.Row) -> WorkStep:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise WorkStoreError("stored work step is missing created_at")
        return WorkStep(
            step_id=row["step_id"],
            work_id=row["work_id"],
            kind=row["kind"],
            summary=row["summary"],
            state=WorkStepState(row["state"]),
            input_data=json.loads(row["input_json"]),
            observation=json.loads(row["observation_json"]),
            error=row["error"],
            created_at=created_at,
            started_at=_parse_dt(row["started_at"]),
            completed_at=_parse_dt(row["completed_at"]),
        )

    def create(self, item: WorkItem) -> WorkItem:
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO work_items (
                        work_id, request, work_type, source_session_id, source_turn_id,
                        state, priority, delivery_policy, dependencies_json,
                        paused_from_state, current_step_id, result_json, status_detail,
                        created_at, updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.work_id,
                        item.request,
                        item.work_type.value,
                        item.source_session_id,
                        item.source_turn_id,
                        item.state.value,
                        int(item.priority),
                        item.delivery_policy.value,
                        json.dumps(item.dependencies),
                        (
                            item.paused_from_state.value
                            if item.paused_from_state is not None
                            else None
                        ),
                        item.current_step_id,
                        json.dumps(item.result, sort_keys=True),
                        item.status_detail,
                        _dt(item.created_at),
                        _dt(item.updated_at),
                        item.version,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkStoreError(f"work already exists: {item.work_id}") from exc
        return item

    def get(self, work_id: str) -> WorkItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_id = ?", (work_id,)
            ).fetchone()
        return None if row is None else self._item_from_row(row)

    def find_by_source_turn(
        self,
        *,
        source_session_id: str,
        source_turn_id: str,
        work_type: WorkType,
    ) -> WorkItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM work_items
                WHERE source_session_id = ? AND source_turn_id = ? AND work_type = ?
                """,
                (source_session_id, source_turn_id, work_type.value),
            ).fetchone()
        return None if row is None else self._item_from_row(row)

    def require(self, work_id: str) -> WorkItem:
        item = self.get(work_id)
        if item is None:
            raise WorkStoreError(f"unknown work item: {work_id}")
        return item

    def save(self, item: WorkItem, *, expected_version: int) -> WorkItem:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE work_items SET
                    state = ?, priority = ?, delivery_policy = ?,
                    paused_from_state = ?, current_step_id = ?, result_json = ?,
                    status_detail = ?, updated_at = ?, version = ?
                WHERE work_id = ? AND version = ?
                """,
                (
                    item.state.value,
                    int(item.priority),
                    item.delivery_policy.value,
                    (
                        item.paused_from_state.value
                        if item.paused_from_state is not None
                        else None
                    ),
                    item.current_step_id,
                    json.dumps(item.result, sort_keys=True),
                    item.status_detail,
                    _dt(item.updated_at),
                    item.version,
                    item.work_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkStoreError(
                    f"stale work update rejected: {item.work_id} expected v{expected_version}"
                )
        return item

    def enqueue_delivery(
        self,
        *,
        work: WorkItem,
        kind: WorkDeliveryKind,
        message: str,
        event_key: str,
    ) -> WorkDelivery | None:
        if work.delivery_policy is DeliveryPolicy.SILENT:
            return None
        delivery = WorkDelivery(
            work_id=work.work_id,
            kind=kind,
            message=message,
            policy=work.delivery_policy,
            event_key=event_key,
        )
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM work_deliveries
                WHERE work_id = ? AND event_key = ?
                """,
                (work.work_id, event_key),
            ).fetchone()
            if existing is not None:
                return self._delivery_from_row(existing)
            connection.execute(
                """
                INSERT INTO work_deliveries (
                    delivery_id, work_id, kind, message, policy, event_key,
                    state, created_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.delivery_id,
                    delivery.work_id,
                    delivery.kind.value,
                    delivery.message,
                    delivery.policy.value,
                    delivery.event_key,
                    delivery.state.value,
                    _dt(delivery.created_at),
                    _dt(delivery.delivered_at),
                ),
            )
        return delivery

    def list_pending_deliveries(self, *, limit: int = 20) -> tuple[WorkDelivery, ...]:
        if limit <= 0:
            raise ValueError("delivery limit must be positive")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM work_deliveries
                WHERE state = ?
                ORDER BY
                    CASE policy
                        WHEN 'interrupt' THEN 0
                        WHEN 'when_idle' THEN 1
                        ELSE 2
                    END,
                    created_at ASC
                LIMIT ?
                """,
                (WorkDeliveryState.PENDING.value, limit),
            ).fetchall()
        return tuple(self._delivery_from_row(row) for row in rows)

    def mark_delivery_delivered(self, delivery_id: str) -> WorkDelivery:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is None:
                raise WorkStoreError(f"unknown work delivery: {delivery_id}")
            delivery = self._delivery_from_row(row)
            updated = delivery.delivered()
            connection.execute(
                """
                UPDATE work_deliveries
                SET state = ?, delivered_at = ?
                WHERE delivery_id = ?
                """,
                (
                    updated.state.value,
                    _dt(updated.delivered_at),
                    updated.delivery_id,
                ),
            )
        return updated

    def add_step(self, step: WorkStep) -> WorkStep:
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO work_steps (
                        step_id, work_id, kind, summary, state, input_json,
                        observation_json, error, created_at, started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step.step_id,
                        step.work_id,
                        step.kind,
                        step.summary,
                        step.state.value,
                        json.dumps(step.input_data, sort_keys=True),
                        json.dumps(step.observation, sort_keys=True),
                        step.error,
                        _dt(step.created_at),
                        _dt(step.started_at),
                        _dt(step.completed_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkStoreError(f"step cannot be created: {step.step_id}") from exc
        return step

    def save_step(self, step: WorkStep) -> WorkStep:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE work_steps SET
                    state = ?, observation_json = ?, error = ?, started_at = ?,
                    completed_at = ?
                WHERE step_id = ? AND work_id = ?
                """,
                (
                    step.state.value,
                    json.dumps(step.observation, sort_keys=True),
                    step.error,
                    _dt(step.started_at),
                    _dt(step.completed_at),
                    step.step_id,
                    step.work_id,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkStoreError(f"unknown work step: {step.step_id}")
        return step

    def list_steps(self, work_id: str) -> tuple[WorkStep, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM work_steps WHERE work_id = ? ORDER BY created_at, step_id",
                (work_id,),
            ).fetchall()
        return tuple(self._step_from_row(row) for row in rows)

    def list(
        self,
        *,
        states: Iterable[WorkState] | None = None,
        limit: int = 100,
    ) -> tuple[WorkItem, ...]:
        if limit <= 0:
            raise ValueError("work list limit must be positive")
        state_values = tuple(state.value for state in states or ())
        query = "SELECT * FROM work_items"
        parameters: list[object] = []
        if state_values:
            marks = ",".join("?" for _ in state_values)
            query += f" WHERE state IN ({marks})"
            parameters.extend(state_values)
        query += " ORDER BY priority DESC, created_at ASC LIMIT ?"
        parameters.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._item_from_row(row) for row in rows)
