"""Durable DevelopmentEngine thread/result lineage in the canonical WorkStore."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from jarvis.work.store import SQLiteWorkStore

from .contracts import (
    DevelopmentDisposition,
    DevelopmentResultV1,
    DevelopmentTicketV1,
)


class DevelopmentSessionState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DevelopmentSessionRecord:
    ticket_digest: str
    ticket_id: str
    work_id: str
    engine_id: str
    engine_version: str
    reasoning_fingerprint: str
    thread_id: str | None
    last_result_digest: str | None
    state: DevelopmentSessionState
    created_at_epoch: float
    updated_at_epoch: float


class DevelopmentSessionStore:
    """Persist provider working-memory identity without making it canonical truth."""

    def __init__(self, work_store: SQLiteWorkStore) -> None:
        if not isinstance(work_store, SQLiteWorkStore):
            raise TypeError("work_store must be SQLiteWorkStore")
        self._work_store = work_store
        self._initialize()

    def _initialize(self) -> None:
        with self._work_store.extension_transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS development_engine_sessions (
                    ticket_digest TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    engine_id TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    reasoning_fingerprint TEXT NOT NULL,
                    thread_id TEXT,
                    last_result_digest TEXT,
                    state TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    updated_at_epoch REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_development_sessions_work
                ON development_engine_sessions(work_id, updated_at_epoch);

                CREATE TABLE IF NOT EXISTS development_engine_results (
                    result_digest TEXT PRIMARY KEY,
                    ticket_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_development_results_ticket
                ON development_engine_results(ticket_digest, created_at_epoch);
                """
            )

    @staticmethod
    def _record(row) -> DevelopmentSessionRecord:
        return DevelopmentSessionRecord(
            ticket_digest=str(row["ticket_digest"]),
            ticket_id=str(row["ticket_id"]),
            work_id=str(row["work_id"]),
            engine_id=str(row["engine_id"]),
            engine_version=str(row["engine_version"]),
            reasoning_fingerprint=str(row["reasoning_fingerprint"]),
            thread_id=None if row["thread_id"] is None else str(row["thread_id"]),
            last_result_digest=(
                None
                if row["last_result_digest"] is None
                else str(row["last_result_digest"])
            ),
            state=DevelopmentSessionState(str(row["state"])),
            created_at_epoch=float(row["created_at_epoch"]),
            updated_at_epoch=float(row["updated_at_epoch"]),
        )

    def get(self, ticket_digest: str) -> DevelopmentSessionRecord | None:
        normalized = str(ticket_digest).strip().casefold()
        if not normalized:
            raise ValueError("ticket_digest must not be empty")
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM development_engine_sessions
                WHERE ticket_digest = ?
                """,
                (normalized,),
            ).fetchone()
        return None if row is None else self._record(row)

    def begin(
        self,
        *,
        ticket: DevelopmentTicketV1,
        engine_id: str,
        engine_version: str,
        reasoning_fingerprint: str,
    ) -> DevelopmentSessionRecord:
        if not isinstance(ticket, DevelopmentTicketV1):
            raise TypeError("ticket must be DevelopmentTicketV1")
        engine = str(engine_id).strip().casefold()
        version = str(engine_version).strip()
        fingerprint = str(reasoning_fingerprint).strip().casefold()
        if not engine or not version or not fingerprint:
            raise ValueError("engine identity and reasoning fingerprint are required")
        now = time.time()
        with self._work_store.extension_transaction() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM development_engine_sessions
                WHERE ticket_digest = ?
                """,
                (ticket.digest,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO development_engine_sessions (
                        ticket_digest,
                        ticket_id,
                        work_id,
                        engine_id,
                        engine_version,
                        reasoning_fingerprint,
                        thread_id,
                        last_result_digest,
                        state,
                        created_at_epoch,
                        updated_at_epoch
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        ticket.digest,
                        ticket.ticket_id,
                        ticket.work_id,
                        engine,
                        version,
                        fingerprint,
                        DevelopmentSessionState.ACTIVE.value,
                        now,
                        now,
                    ),
                )
            else:
                if (
                    str(existing["ticket_id"]) != ticket.ticket_id
                    or str(existing["work_id"]) != ticket.work_id
                ):
                    raise ValueError(
                        "development session identity conflicts with durable ticket"
                    )
                prior_fingerprint = str(existing["reasoning_fingerprint"])
                last_result = existing["last_result_digest"]
                if prior_fingerprint != fingerprint:
                    last_result = None
                connection.execute(
                    """
                    UPDATE development_engine_sessions
                    SET engine_id = ?,
                        engine_version = ?,
                        reasoning_fingerprint = ?,
                        last_result_digest = ?,
                        state = ?,
                        updated_at_epoch = ?
                    WHERE ticket_digest = ?
                    """,
                    (
                        engine,
                        version,
                        fingerprint,
                        last_result,
                        DevelopmentSessionState.ACTIVE.value,
                        now,
                        ticket.digest,
                    ),
                )
            row = connection.execute(
                """
                SELECT *
                FROM development_engine_sessions
                WHERE ticket_digest = ?
                """,
                (ticket.digest,),
            ).fetchone()
        if row is None:
            raise RuntimeError("development session was not persisted")
        return self._record(row)

    def bind_thread(
        self,
        *,
        ticket_digest: str,
        thread_id: str,
    ) -> DevelopmentSessionRecord:
        digest = str(ticket_digest).strip().casefold()
        thread = str(thread_id).strip()
        if not digest or not thread:
            raise ValueError("ticket_digest and thread_id are required")
        now = time.time()
        with self._work_store.extension_transaction() as connection:
            updated = connection.execute(
                """
                UPDATE development_engine_sessions
                SET thread_id = ?, updated_at_epoch = ?
                WHERE ticket_digest = ?
                """,
                (thread, now, digest),
            )
            if updated.rowcount != 1:
                raise KeyError(f"development session not found: {digest}")
            row = connection.execute(
                """
                SELECT *
                FROM development_engine_sessions
                WHERE ticket_digest = ?
                """,
                (digest,),
            ).fetchone()
        if row is None:
            raise RuntimeError("development thread binding disappeared")
        return self._record(row)

    def record_result(
        self,
        *,
        ticket: DevelopmentTicketV1,
        result: DevelopmentResultV1,
        reasoning_fingerprint: str,
    ) -> DevelopmentSessionRecord:
        if result.ticket_id != ticket.ticket_id or result.ticket_digest != ticket.digest:
            raise ValueError("development result is not bound to this ticket")
        fingerprint = str(reasoning_fingerprint).strip().casefold()
        if not fingerprint:
            raise ValueError("reasoning_fingerprint must not be empty")
        current = self.get(ticket.digest)
        if current is None:
            raise KeyError("development session must exist before recording a result")
        if current.reasoning_fingerprint != fingerprint:
            raise ValueError("development result fingerprint is stale")

        if result.disposition is DevelopmentDisposition.COMPLETED:
            state = DevelopmentSessionState.COMPLETED
        elif result.disposition is DevelopmentDisposition.FAILED:
            state = DevelopmentSessionState.FAILED
        else:
            state = DevelopmentSessionState.BLOCKED

        now = time.time()
        payload = self._work_store.encode_extension_json(result.canonical_payload())
        with self._work_store.extension_transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO development_engine_results (
                    result_digest,
                    ticket_digest,
                    result_json,
                    created_at_epoch
                )
                VALUES (?, ?, ?, ?)
                """,
                (result.digest, ticket.digest, payload, now),
            )
            connection.execute(
                """
                UPDATE development_engine_sessions
                SET last_result_digest = ?,
                    state = ?,
                    updated_at_epoch = ?
                WHERE ticket_digest = ?
                  AND reasoning_fingerprint = ?
                """,
                (
                    result.digest,
                    state.value,
                    now,
                    ticket.digest,
                    fingerprint,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM development_engine_sessions
                WHERE ticket_digest = ?
                """,
                (ticket.digest,),
            ).fetchone()
        if row is None:
            raise RuntimeError("development session disappeared")
        record = self._record(row)
        if record.last_result_digest != result.digest:
            raise ValueError("development session changed before result persistence")
        return record

    def load_result(
        self,
        *,
        ticket: DevelopmentTicketV1,
        result_digest: str,
    ) -> DevelopmentResultV1 | None:
        digest = str(result_digest).strip().casefold()
        if not digest:
            raise ValueError("result_digest must not be empty")
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT result_json
                FROM development_engine_results
                WHERE result_digest = ? AND ticket_digest = ?
                """,
                (digest, ticket.digest),
            ).fetchone()
        if row is None:
            return None
        payload = self._work_store.decode_extension_json(str(row["result_json"]))
        if not isinstance(payload, dict):
            raise TypeError("durable development result payload is invalid")
        return DevelopmentResultV1.from_payload(
            ticket=ticket,
            payload=payload,
            expected_digest=digest,
        )

    def reusable_result(
        self,
        *,
        ticket: DevelopmentTicketV1,
        reasoning_fingerprint: str,
    ) -> DevelopmentResultV1 | None:
        """Return an exact durable reasoning result when no relevant fact changed."""

        fingerprint = str(reasoning_fingerprint).strip().casefold()
        record = self.get(ticket.digest)
        if (
            record is None
            or record.reasoning_fingerprint != fingerprint
            or record.last_result_digest is None
        ):
            return None
        result = self.load_result(
            ticket=ticket,
            result_digest=record.last_result_digest,
        )
        if result is None:
            return None
        if result.disposition is DevelopmentDisposition.BLOCKED_RESOURCE:
            return None
        return result
