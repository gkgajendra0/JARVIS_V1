"""SQLite canonical store for JARVIS WorkItems and WorkSteps."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

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
from jarvis.work.privacy import PlaintextWorkPayloadCodec, WorkPayloadCodec


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

    def __init__(
        self,
        path: str | pathlib.Path,
        *,
        payload_codec: WorkPayloadCodec | None = None,
    ) -> None:
        self.path = pathlib.Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._payload_codec = payload_codec or PlaintextWorkPayloadCodec()
        self._lock = threading.RLock()
        self._initialize()

    @property
    def payload_protected(self) -> bool:
        return bool(self._payload_codec.protects_at_rest)

    @contextmanager
    def extension_transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide a locked transaction for additive JARVIS domain tables."""

        with self._lock, self._connect() as connection:
            yield connection

    def encode_extension_text(self, value: str) -> str:
        """Protect extension payload text with the canonical WorkStore codec."""

        return self._encode_text(value)

    def decode_extension_text(self, value: str) -> str:
        """Decode extension payload text with the canonical WorkStore codec."""

        return self._decode_text(value)

    def encode_extension_json(self, value: object) -> str:
        """Protect extension JSON with the canonical WorkStore codec."""

        return self._encode_json(value)

    def decode_extension_json(self, value: str):
        """Decode extension JSON with the canonical WorkStore codec."""

        return self._decode_json(value)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        finally:
            connection.close()

    def _encode_text(self, value: str) -> str:
        return self._payload_codec.encode(value)

    def _decode_text(self, value: str) -> str:
        return self._payload_codec.decode(value)

    def _encode_optional_text(self, value: str | None) -> str | None:
        return None if value is None else self._encode_text(value)

    def _decode_optional_text(self, value: str | None) -> str | None:
        return None if value is None else self._decode_text(value)

    def _encode_json(self, value: object) -> str:
        return self._encode_text(json.dumps(value, sort_keys=True))

    def _decode_json(self, value: str):
        return json.loads(self._decode_text(value))

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
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_failure_reason TEXT,
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

                CREATE TABLE IF NOT EXISTS work_execution_refs (
                    work_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE TABLE IF NOT EXISTS work_status_updates (
                    work_id TEXT PRIMARY KEY,
                    interval_seconds INTEGER NOT NULL,
                    next_due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_work_status_updates_due
                    ON work_status_updates(next_due_at);

                CREATE TABLE IF NOT EXISTS work_sensitive_inputs (
                    work_id TEXT NOT NULL,
                    input_key TEXT NOT NULL,
                    protected_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(work_id, input_key),
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(work_items)"
                ).fetchall()
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

            delivery_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(work_deliveries)"
                ).fetchall()
            }
            if "failed_attempts" not in delivery_columns:
                connection.execute(
                    "ALTER TABLE work_deliveries "
                    "ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "next_attempt_at" not in delivery_columns:
                connection.execute(
                    "ALTER TABLE work_deliveries ADD COLUMN next_attempt_at TEXT"
                )
            if "last_failure_reason" not in delivery_columns:
                connection.execute(
                    "ALTER TABLE work_deliveries ADD COLUMN last_failure_reason TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_deliveries_due "
                "ON work_deliveries(state, next_attempt_at, created_at)"
            )

    def _item_from_row(self, row: sqlite3.Row) -> WorkItem:
        created_at = _parse_dt(row["created_at"])
        updated_at = _parse_dt(row["updated_at"])
        if created_at is None or updated_at is None:
            raise WorkStoreError("stored work item is missing timestamps")
        return WorkItem(
            work_id=row["work_id"],
            request=self._decode_text(row["request"]),
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
            result=self._decode_json(row["result_json"]),
            status_detail=self._decode_optional_text(row["status_detail"]),
            created_at=created_at,
            updated_at=updated_at,
            version=row["version"],
        )

    def _delivery_from_row(self, row: sqlite3.Row) -> WorkDelivery:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise WorkStoreError("stored work delivery is missing created_at")
        return WorkDelivery(
            delivery_id=row["delivery_id"],
            work_id=row["work_id"],
            kind=WorkDeliveryKind(row["kind"]),
            message=self._decode_text(row["message"]),
            policy=DeliveryPolicy(row["policy"]),
            event_key=row["event_key"],
            state=WorkDeliveryState(row["state"]),
            created_at=created_at,
            delivered_at=_parse_dt(row["delivered_at"]),
            failed_attempts=int(row["failed_attempts"]),
            next_attempt_at=_parse_dt(row["next_attempt_at"]),
            last_failure_reason=row["last_failure_reason"],
        )

    def _step_from_row(self, row: sqlite3.Row) -> WorkStep:
        created_at = _parse_dt(row["created_at"])
        if created_at is None:
            raise WorkStoreError("stored work step is missing created_at")
        return WorkStep(
            step_id=row["step_id"],
            work_id=row["work_id"],
            kind=row["kind"],
            summary=self._decode_text(row["summary"]),
            state=WorkStepState(row["state"]),
            input_data=self._decode_json(row["input_json"]),
            observation=self._decode_json(row["observation_json"]),
            error=self._decode_optional_text(row["error"]),
            created_at=created_at,
            started_at=_parse_dt(row["started_at"]),
            completed_at=_parse_dt(row["completed_at"]),
        )

    @staticmethod
    def _validate_dependency_graph(
        connection: sqlite3.Connection,
        item: WorkItem,
    ) -> None:
        """Reject dependency chains that would deadlock by reaching the new item."""

        stack: list[tuple[str, tuple[str, ...]]] = [
            (dependency_id, (item.work_id, dependency_id))
            for dependency_id in item.dependencies
        ]
        visited: set[str] = set()
        while stack:
            dependency_id, path = stack.pop()
            if dependency_id == item.work_id:
                raise WorkStoreError(
                    "work dependency cycle detected: " + " -> ".join(path)
                )
            if dependency_id in visited:
                continue
            visited.add(dependency_id)
            row = connection.execute(
                "SELECT dependencies_json FROM work_items WHERE work_id = ?",
                (dependency_id,),
            ).fetchone()
            if row is None:
                continue
            try:
                dependencies = tuple(json.loads(row["dependencies_json"]))
            except (TypeError, ValueError) as exc:
                raise WorkStoreError(
                    f"stored dependency graph is invalid for {dependency_id}"
                ) from exc
            for child in dependencies:
                normalized = str(child).strip()
                if not normalized:
                    continue
                if normalized == item.work_id:
                    raise WorkStoreError(
                        "work dependency cycle detected: "
                        + " -> ".join((*path, normalized))
                    )
                if normalized not in visited:
                    stack.append((normalized, (*path, normalized)))

    def protect_existing_payloads(self) -> int:
        """Encrypt legacy plaintext payload fields when protection is enabled."""

        if not self._payload_codec.protects_at_rest:
            return 0

        tables = (
            (
                "work_items",
                "work_id",
                ("request", "result_json", "status_detail"),
            ),
            ("work_deliveries", "delivery_id", ("message",)),
            (
                "work_steps",
                "step_id",
                ("summary", "input_json", "observation_json", "error"),
            ),
        )
        migrated = 0
        with self._lock, self._connect() as connection:
            for table, primary_key, columns in tables:
                selected = ", ".join((primary_key, *columns))
                rows = connection.execute(f"SELECT {selected} FROM {table}").fetchall()
                for row in rows:
                    updates: dict[str, str] = {}
                    for column in columns:
                        raw = row[column]
                        if raw is None or self._payload_codec.is_protected(raw):
                            continue
                        updates[column] = self._encode_text(raw)
                    if not updates:
                        continue
                    assignments = ", ".join(f"{column} = ?" for column in updates)
                    connection.execute(
                        f"UPDATE {table} SET {assignments} WHERE {primary_key} = ?",
                        (*updates.values(), row[primary_key]),
                    )
                    migrated += 1

        if migrated:
            with self._lock, self._connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
        return migrated

    def create(self, item: WorkItem) -> WorkItem:
        with self._lock, self._connect() as connection:
            self._validate_dependency_graph(connection, item)
            try:
                self._insert_item(connection, item)
            except sqlite3.IntegrityError as exc:
                raise WorkStoreError(f"work already exists: {item.work_id}") from exc
        return item

    def _insert_item(self, connection: sqlite3.Connection, item: WorkItem) -> None:
        """Insert within the caller's transaction, including a change-stage link."""
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
                self._encode_text(item.request),
                item.work_type.value,
                item.source_session_id,
                item.source_turn_id,
                item.state.value,
                int(item.priority),
                item.delivery_policy.value,
                json.dumps(item.dependencies),
                item.paused_from_state.value if item.paused_from_state else None,
                item.current_step_id,
                self._encode_json(item.result),
                self._encode_optional_text(item.status_detail),
                _dt(item.created_at),
                _dt(item.updated_at),
                item.version,
            ),
        )

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
                    self._encode_json(item.result),
                    self._encode_optional_text(item.status_detail),
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
                    state, created_at, delivered_at, failed_attempts,
                    next_attempt_at, last_failure_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.delivery_id,
                    delivery.work_id,
                    delivery.kind.value,
                    self._encode_text(delivery.message),
                    delivery.policy.value,
                    delivery.event_key,
                    delivery.state.value,
                    _dt(delivery.created_at),
                    _dt(delivery.delivered_at),
                    delivery.failed_attempts,
                    _dt(delivery.next_attempt_at),
                    delivery.last_failure_reason,
                ),
            )
        return delivery

    def owner_goal_work_ids(self, goal_id: str) -> tuple[str, ...]:
        """Return only canonical work directly sourced by this owner goal."""
        key = str(goal_id).strip()
        if not key:
            raise ValueError("goal_id must not be empty")
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT work_id FROM work_items WHERE source_session_id IN (?, ?, ?) "
                "ORDER BY work_id",
                (f"gicc:{key}", f"goal:{key}", f"gicc-monitor:{key}"),
            ).fetchall()
        return tuple(row["work_id"] for row in rows)

    def suppress_pending_deliveries_for_work_ids(
        self, work_ids: tuple[str, ...]
    ) -> int:
        """Retire stale owner notifications from cancelled work; keep audit rows.

        No 'delivered' timestamp is written: the owner did not receive these.
        """
        keys = tuple(sorted({str(key).strip() for key in work_ids if str(key).strip()}))
        if not keys:
            return 0
        suppressed = 0
        with self._lock, self._connect() as db:
            for key in keys:
                result = db.execute(
                    "UPDATE work_deliveries SET state=? WHERE work_id=? AND state=?",
                    (
                        WorkDeliveryState.CANCELLED.value,
                        key,
                        WorkDeliveryState.PENDING.value,
                    ),
                )
                suppressed += result.rowcount
        return suppressed

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

    def list_due_deliveries(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> tuple[WorkDelivery, ...]:
        if limit <= 0:
            raise ValueError("delivery limit must be positive")
        due_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM work_deliveries
                WHERE state = ?
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY
                    CASE policy
                        WHEN 'interrupt' THEN 0
                        WHEN 'when_idle' THEN 1
                        ELSE 2
                    END,
                    created_at ASC
                LIMIT ?
                """,
                (
                    WorkDeliveryState.PENDING.value,
                    _dt(due_at),
                    limit,
                ),
            ).fetchall()
        return tuple(self._delivery_from_row(row) for row in rows)

    def schedule_delivery_retry(
        self,
        delivery_id: str,
        *,
        delay_seconds: float,
        reason: str,
    ) -> WorkDelivery:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is None:
                raise WorkStoreError(f"unknown work delivery: {delivery_id}")
            delivery = self._delivery_from_row(row)
            updated = delivery.retry_after(delay_seconds, reason=reason)
            if updated is delivery:
                return delivery
            connection.execute(
                """
                UPDATE work_deliveries
                SET failed_attempts = ?, next_attempt_at = ?,
                    last_failure_reason = ?
                WHERE delivery_id = ? AND state = ?
                """,
                (
                    updated.failed_attempts,
                    _dt(updated.next_attempt_at),
                    updated.last_failure_reason,
                    updated.delivery_id,
                    WorkDeliveryState.PENDING.value,
                ),
            )
        return updated

    def requeue_delivered_owner_input(self, delivery_id: str) -> WorkDelivery:
        """Repair a delivered OWNER_INPUT whose WorkItem is still waiting.

        OWNER_INPUT delivery is complete only when the owner's response has been
        durably submitted. Older runtime versions could mark the spoken question
        delivered before collecting a reply. Reopening that exact durable record
        preserves event identity while restoring the canonical waiting invariant.
        """

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is None:
                raise WorkStoreError(f"unknown work delivery: {delivery_id}")
            delivery = self._delivery_from_row(row)
            if delivery.kind is not WorkDeliveryKind.OWNER_INPUT:
                raise ValueError("only owner-input deliveries may be reopened")
            if delivery.state is WorkDeliveryState.PENDING:
                return delivery
            connection.execute(
                """
                UPDATE work_deliveries
                SET state = ?, delivered_at = NULL, next_attempt_at = NULL,
                    last_failure_reason = ?
                WHERE delivery_id = ?
                """,
                (
                    WorkDeliveryState.PENDING.value,
                    "reconciled_waiting_owner_without_durable_response",
                    delivery.delivery_id,
                ),
            )
            reopened_row = connection.execute(
                "SELECT * FROM work_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            assert reopened_row is not None
            return self._delivery_from_row(reopened_row)

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
                SET state = ?, delivered_at = ?, next_attempt_at = NULL,
                    last_failure_reason = NULL
                WHERE delivery_id = ?
                """,
                (
                    updated.state.value,
                    _dt(updated.delivered_at),
                    updated.delivery_id,
                ),
            )
        return updated

    def set_execution_id(self, work_id: str, execution_id: str) -> None:
        normalized = str(execution_id).strip()
        if not normalized:
            raise ValueError("execution_id must not be empty")
        self.require(work_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO work_execution_refs (work_id, execution_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(work_id) DO UPDATE SET
                    execution_id = excluded.execution_id,
                    updated_at = excluded.updated_at
                """,
                (work_id, normalized, _dt(datetime.now(UTC))),
            )

    def get_execution_id(self, work_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT execution_id FROM work_execution_refs WHERE work_id = ?",
                (work_id,),
            ).fetchone()
        return None if row is None else str(row["execution_id"])

    def set_status_update_interval(
        self,
        work_id: str,
        *,
        interval_seconds: int,
    ) -> None:
        if isinstance(interval_seconds, bool) or interval_seconds <= 0:
            raise ValueError("status update interval must be positive")
        self.require(work_id)
        now = datetime.now(UTC)
        next_due = now + timedelta(seconds=int(interval_seconds))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO work_status_updates (
                    work_id, interval_seconds, next_due_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(work_id) DO UPDATE SET
                    interval_seconds = excluded.interval_seconds,
                    next_due_at = excluded.next_due_at,
                    updated_at = excluded.updated_at
                """,
                (
                    work_id,
                    int(interval_seconds),
                    _dt(next_due),
                    _dt(now),
                    _dt(now),
                ),
            )

    def clear_status_update_interval(self, work_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM work_status_updates WHERE work_id = ?",
                (work_id,),
            )

    def list_due_status_updates(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> tuple[tuple[str, int, datetime], ...]:
        if limit <= 0:
            raise ValueError("status update limit must be positive")
        due_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT work_id, interval_seconds, next_due_at
                FROM work_status_updates
                WHERE next_due_at <= ?
                ORDER BY next_due_at ASC
                LIMIT ?
                """,
                (_dt(due_at), limit),
            ).fetchall()
        result: list[tuple[str, int, datetime]] = []
        for row in rows:
            parsed = _parse_dt(row["next_due_at"])
            if parsed is None:
                continue
            result.append((str(row["work_id"]), int(row["interval_seconds"]), parsed))
        return tuple(result)

    def advance_status_update_interval(
        self,
        work_id: str,
        *,
        interval_seconds: int,
        now: datetime | None = None,
    ) -> None:
        base = (now or datetime.now(UTC)).astimezone(UTC)
        next_due = base + timedelta(seconds=int(interval_seconds))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE work_status_updates
                SET next_due_at = ?, updated_at = ?
                WHERE work_id = ?
                """,
                (_dt(next_due), _dt(base), work_id),
            )

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
                        self._encode_text(step.summary),
                        step.state.value,
                        self._encode_json(step.input_data),
                        self._encode_json(step.observation),
                        self._encode_optional_text(step.error),
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
                    self._encode_json(step.observation),
                    self._encode_optional_text(step.error),
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

    def put_sensitive_input(
        self,
        work_id: str,
        input_key: str,
        value: str,
    ) -> None:
        """Store one model-hidden owner value using the canonical payload codec."""

        normalized_work = str(work_id).strip()
        normalized_key = str(input_key).strip().casefold()
        normalized_value = str(value).strip()
        if not normalized_work or not normalized_key or not normalized_value:
            raise ValueError("sensitive work input requires work_id, key and value")
        with self._lock, self._connect() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM work_items WHERE work_id=?",
                    (normalized_work,),
                ).fetchone()
                is None
            ):
                raise WorkStoreError(f"unknown work item: {normalized_work}")
            encoded = self._encode_text(normalized_value)
            with connection:
                connection.execute(
                    """INSERT INTO work_sensitive_inputs
                    (work_id, input_key, protected_value, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(work_id, input_key) DO UPDATE SET
                    protected_value=excluded.protected_value,
                    created_at=excluded.created_at""",
                    (
                        normalized_work,
                        normalized_key,
                        encoded,
                        _dt(datetime.now(UTC)),
                    ),
                )

    def pop_sensitive_input(
        self,
        work_id: str,
        input_key: str,
    ) -> str | None:
        """Atomically consume one model-hidden owner value."""

        normalized_work = str(work_id).strip()
        normalized_key = str(input_key).strip().casefold()
        if not normalized_work or not normalized_key:
            raise ValueError("sensitive input lookup requires work_id and key")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT protected_value FROM work_sensitive_inputs
                WHERE work_id=? AND input_key=?""",
                (normalized_work, normalized_key),
            ).fetchone()
            if row is None:
                return None
            value = self._decode_text(row["protected_value"])
            with connection:
                connection.execute(
                    """DELETE FROM work_sensitive_inputs
                    WHERE work_id=? AND input_key=?""",
                    (normalized_work, normalized_key),
                )
        return value

    def clear_sensitive_inputs(self, work_id: str) -> None:
        normalized = str(work_id).strip()
        if not normalized:
            return
        with self._lock, self._connect() as connection, connection:
            connection.execute(
                "DELETE FROM work_sensitive_inputs WHERE work_id=?",
                (normalized,),
            )

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

    def list_recent(
        self,
        *,
        states: Iterable[WorkState] | None = None,
        limit: int = 100,
    ) -> tuple[WorkItem, ...]:
        """List WorkItems by most recent canonical update, newest first."""

        if limit <= 0:
            raise ValueError("work list limit must be positive")
        state_values = tuple(state.value for state in states or ())
        query = "SELECT * FROM work_items"
        parameters: list[object] = []
        if state_values:
            marks = ",".join("?" for _ in state_values)
            query += f" WHERE state IN ({marks})"
            parameters.extend(state_values)
        query += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        parameters.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._item_from_row(row) for row in rows)
