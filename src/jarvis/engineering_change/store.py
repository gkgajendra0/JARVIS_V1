"""Canonical change records alongside WorkItems in the protected work database."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime

import rfc8785

from jarvis.work.models import WorkItem, WorkState
from jarvis.work.store import SQLiteWorkStore

from .models import (
    TRANSITIONS,
    ChangeArtifact,
    ChangeConflict,
    ChangeStage,
    ChangeState,
    EngineeringChange,
    ProcessContract,
    ProcessStageRole,
    UnsupportedProcess,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


class ChangeStore:
    """Transactional change/work ownership; DBOS is still the execution backend."""

    DEFAULT_PROCESS = ProcessContract("engineering.change", 1)

    def __init__(
        self, work: SQLiteWorkStore, *, processes: tuple[ProcessContract, ...] = ()
    ) -> None:
        self.work = work
        self._processes = {
            (
                self.DEFAULT_PROCESS.key,
                self.DEFAULT_PROCESS.version,
            ): self.DEFAULT_PROCESS
        }
        for process in processes:
            identity = (process.key, process.version)
            if identity in self._processes:
                raise ChangeConflict("duplicate process contract")
            self._processes[identity] = process
        with work._lock, work._connect() as connection:
            schema = """
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
                    plan_artifact_id TEXT REFERENCES engineering_change_artifacts(artifact_id),
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
            connection.executescript(schema)
            with connection:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(engineering_change_stages)"
                    )
                }
                if "plan_artifact_id" not in columns:
                    connection.execute(
                        """ALTER TABLE engineering_change_stages ADD COLUMN
                        plan_artifact_id TEXT REFERENCES engineering_change_artifacts(artifact_id)"""
                    )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS engineering_change_schema (
                    version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"""
                )
                checksum = hashlib.sha256(
                    (schema + "|stage-plan-v2").encode("utf-8")
                ).hexdigest()
                rows = connection.execute(
                    "SELECT version, checksum FROM engineering_change_schema"
                ).fetchall()
                ledger = {row["version"]: row["checksum"] for row in rows}
                if rows and (
                    2 not in ledger or set(ledger) - {2, 3} or ledger[2] != checksum
                ):
                    raise ChangeConflict("engineering change schema checksum mismatch")
                if not rows:
                    connection.execute(
                        "INSERT INTO engineering_change_schema VALUES (2, ?)",
                        (checksum,),
                    )
                proof_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(engineering_change_decisions)"
                    )
                }
                for column in (
                    "verification_id",
                    "verifier_id",
                    "proposal_fingerprint",
                ):
                    if column not in proof_columns:
                        connection.execute(
                            f"ALTER TABLE engineering_change_decisions ADD COLUMN {column} TEXT"
                        )
                proof_checksum = hashlib.sha256(
                    (checksum + "|strong-owner-proof-v3").encode("utf-8")
                ).hexdigest()
                proof_row = connection.execute(
                    "SELECT checksum FROM engineering_change_schema WHERE version=3"
                ).fetchone()
                if proof_row is not None and proof_row["checksum"] != proof_checksum:
                    raise ChangeConflict(
                        "engineering change proof schema checksum mismatch"
                    )
                if proof_row is None:
                    connection.execute(
                        "INSERT INTO engineering_change_schema VALUES (3, ?)",
                        (proof_checksum,),
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

    def _event(
        self,
        db: sqlite3.Connection,
        change_id: str,
        event_key: str,
        kind: str,
        detail: dict[str, object],
    ) -> None:
        db.execute(
            "INSERT INTO engineering_change_events VALUES (?, ?, ?, ?, ?, ?)",
            (
                "event_" + uuid.uuid4().hex[:16],
                change_id,
                event_key,
                kind,
                self.work._encode_json(detail),
                _now(),
            ),
        )

    def list_events(self, change_id: str) -> tuple[dict[str, object], ...]:
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT * FROM engineering_change_events WHERE change_id=?
                ORDER BY rowid""",
                (change_id,),
            ).fetchall()
        return tuple(
            {
                "event_key": row["event_key"],
                "kind": row["kind"],
                "detail": self.work._decode_json(row["detail"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def process_contract(self, key: str, version: int) -> ProcessContract:
        if type(version) is not int:
            raise UnsupportedProcess(f"unsupported change process: {key}/{version}")
        try:
            return self._processes[(key, version)]
        except KeyError as exc:
            raise UnsupportedProcess(
                f"unsupported change process: {key}/{version}"
            ) from exc

    def _assert_supported(self, key: str, version: int) -> None:
        self.process_contract(key, version)

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
            self._event(
                connection,
                change_id,
                "created:1",
                "created",
                {
                    "process_key": process_key,
                    "process_version": process_version,
                },
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

    def list_by_states(
        self,
        states: tuple[ChangeState, ...],
        *,
        process_key: str | None = None,
        process_version: int | None = None,
        limit: int = 20,
    ) -> tuple[EngineeringChange, ...]:
        if not states or any(not isinstance(state, ChangeState) for state in states):
            raise ValueError("change state filter must be non-empty and typed")
        if type(limit) is not int or limit <= 0:
            raise ValueError("change list limit must be positive")
        normalized_process = None if process_key is None else str(process_key).strip()
        if process_key is not None and not normalized_process:
            raise ValueError("process_key must not be empty")
        if process_version is not None and (
            type(process_version) is not int or process_version <= 0
        ):
            raise ValueError("process_version must be positive")
        if normalized_process is None and process_version is not None:
            raise ValueError("process_version requires process_key")

        placeholders = ",".join("?" for _ in states)
        query = f"SELECT * FROM engineering_changes WHERE state IN ({placeholders})"
        parameters: list[object] = [state.value for state in states]
        if normalized_process is not None:
            query += " AND process_key=?"
            parameters.append(normalized_process)
        if process_version is not None:
            query += " AND process_version=?"
            parameters.append(process_version)
        query += " ORDER BY created_at, change_id LIMIT ?"
        parameters.append(limit)

        with self.work._lock, self.work._connect() as db:
            rows = db.execute(query, tuple(parameters)).fetchall()
        return tuple(self._from_row(row) for row in rows)

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

    def list_artifacts(
        self,
        change_id: str,
        *,
        kind: str | None = None,
    ) -> tuple[ChangeArtifact, ...]:
        """Return integrity-checked artifacts in revision order for durable replay."""
        self.require(change_id)
        with self.work._lock, self.work._connect() as db:
            if kind is None:
                rows = db.execute(
                    """SELECT artifact_id FROM engineering_change_artifacts
                    WHERE change_id=? ORDER BY kind, revision""",
                    (change_id,),
                ).fetchall()
            else:
                if not kind.strip():
                    raise ChangeConflict("artifact kind must not be empty")
                rows = db.execute(
                    """SELECT artifact_id FROM engineering_change_artifacts
                    WHERE change_id=? AND kind=? ORDER BY revision""",
                    (change_id, kind),
                ).fetchall()
        artifacts = tuple(self.get_artifact(row["artifact_id"]) for row in rows)
        if any(item is None for item in artifacts):
            raise ChangeConflict("artifact disappeared during durable replay")
        return tuple(item for item in artifacts if item is not None)

    def list_stages(self, change_id: str) -> tuple[ChangeStage, ...]:
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT * FROM engineering_change_stages WHERE change_id=?
                ORDER BY rowid""",
                (change_id,),
            ).fetchall()
        return tuple(
            ChangeStage(
                row["change_id"],
                row["stage_key"],
                row["attempt"],
                row["work_id"],
                row["plan_artifact_id"],
            )
            for row in rows
        )

    def reopen_recoverable_development_engine_failures(
        self,
        *,
        recovery_generation: str,
    ) -> tuple[str, ...]:
        """Reopen only known DevelopmentEngine states fixed by this runtime generation.

        This is compatibility recovery for prior JARVIS bugs, not a generic retry of
        failed engineering. Recovery requires the still-current strongly approved
        architecture and one of two exact historical shapes:
        - old completed-child + unclassified DevelopmentEngine failure; or
        - failed development caused solely by response_contract_invalid.

        The generation key makes each compatibility recovery one-shot across restarts.
        """

        generation = str(recovery_generation).strip().casefold()
        if not generation:
            raise ValueError("recovery_generation must not be empty")

        recovered: list[str] = []
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT * FROM engineering_changes
                WHERE state=? ORDER BY created_at, change_id""",
                (ChangeState.FAILED.value,),
            ).fetchall()
            for row in rows:
                change = self._from_row(row)
                process = self.process_contract(
                    change.process_key,
                    change.process_version,
                )
                development = process.development_stage
                architecture = db.execute(
                    """SELECT artifact_id, digest
                    FROM engineering_change_artifacts
                    WHERE change_id=? AND kind='architecture'
                    ORDER BY revision DESC LIMIT 1""",
                    (change.change_id,),
                ).fetchone()
                if architecture is None:
                    continue

                stage = db.execute(
                    """SELECT * FROM engineering_change_stages
                    WHERE change_id=? AND stage_key=? AND plan_artifact_id=?
                    ORDER BY attempt DESC LIMIT 1""",
                    (
                        change.change_id,
                        development.stage_key,
                        architecture["artifact_id"],
                    ),
                ).fetchone()
                if stage is None:
                    continue

                work_row = db.execute(
                    "SELECT * FROM work_items WHERE work_id=?",
                    (stage["work_id"],),
                ).fetchone()
                if work_row is None:
                    continue
                work = self.work._item_from_row(work_row)

                recovery_kind: str | None = None
                if work.state is WorkState.COMPLETED:
                    engine_result = work.result.get("development_engine")
                    if isinstance(engine_result, dict):
                        disposition = (
                            str(engine_result.get("disposition") or "")
                            .strip()
                            .casefold()
                        )
                        reason = " ".join(
                            str(engine_result.get("reason") or "").split()
                        ).casefold()
                        if (
                            disposition == "failed"
                            and "non-retryable failure (unknown)" in reason
                        ):
                            recovery_kind = "legacy_unclassified_completed_child"

                elif work.state is WorkState.FAILED:
                    step_rows = db.execute(
                        """SELECT * FROM work_steps
                        WHERE work_id=? AND state=?
                        ORDER BY created_at DESC, step_id DESC""",
                        (work.work_id, "completed"),
                    ).fetchall()
                    engine_result = None
                    for step_row in step_rows:
                        step = self.work._step_from_row(step_row)
                        candidate = step.observation.get("development_result")
                        if isinstance(candidate, dict):
                            engine_result = candidate
                            break
                    if isinstance(engine_result, dict):
                        disposition = (
                            str(engine_result.get("disposition") or "")
                            .strip()
                            .casefold()
                        )
                        reason = " ".join(
                            str(engine_result.get("reason") or "").split()
                        ).casefold()
                        if (
                            disposition == "failed"
                            and "response_contract_invalid" in reason
                        ):
                            recovery_kind = "response_contract_invalid"

                if recovery_kind is None:
                    continue

                approval = db.execute(
                    """SELECT d.gate_id
                    FROM engineering_change_gates AS g
                    JOIN engineering_change_decisions AS d ON d.gate_id=g.gate_id
                    WHERE g.change_id=? AND g.kind='architecture'
                    AND g.artifact_id=? AND g.artifact_digest=?
                    AND d.approved=1 AND d.verification_id IS NOT NULL
                    ORDER BY d.decided_at DESC LIMIT 1""",
                    (
                        change.change_id,
                        architecture["artifact_id"],
                        architecture["digest"],
                    ),
                ).fetchone()
                if approval is None:
                    continue

                event_key = (
                    f"development-engine-compat-recovery:{generation}:{work.work_id}"
                )
                if (
                    db.execute(
                        """SELECT 1 FROM engineering_change_events
                        WHERE change_id=? AND event_key=?""",
                        (change.change_id, event_key),
                    ).fetchone()
                    is not None
                ):
                    continue

                timestamp = _now()
                cursor = db.execute(
                    """UPDATE engineering_changes
                    SET state=?, version=version+1, updated_at=?
                    WHERE change_id=? AND version=? AND state=?""",
                    (
                        ChangeState.APPROVED_FOR_BUILD.value,
                        timestamp,
                        change.change_id,
                        change.version,
                        ChangeState.FAILED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ChangeConflict(
                        "stale DevelopmentEngine compatibility recovery transition"
                    )
                self._event(
                    db,
                    change.change_id,
                    event_key,
                    "development_engine_compatibility_reopened",
                    {
                        "generation": generation,
                        "recovery_kind": recovery_kind,
                        "work_id": work.work_id,
                        "stage_key": development.stage_key,
                        "attempt": int(stage["attempt"]),
                        "architecture_artifact_id": architecture["artifact_id"],
                        "approval_gate_id": approval["gate_id"],
                        "from": ChangeState.FAILED.value,
                        "to": ChangeState.APPROVED_FOR_BUILD.value,
                    },
                )
                recovered.append(change.change_id)
        return tuple(recovered)

    def reopen_recoverable_architecture_revision_failures(
        self,
        *,
        recovery_generation: str,
    ) -> tuple[str, ...]:
        """Supersede only revision-research failures fixed by this runtime generation.

        A failed architecture-source attempt is never retried in place here. Instead,
        the exact revision request is copied to a fresh source attempt so stale model
        evidence from the failed WorkItem cannot become current evidence.
        """

        generation = str(recovery_generation).strip().casefold()
        if not generation:
            raise ValueError("recovery_generation must not be empty")

        recovered: list[str] = []
        with self.work._lock, self.work._connect() as db:
            rows = db.execute(
                """SELECT * FROM engineering_changes
                WHERE state=? ORDER BY created_at, change_id""",
                (ChangeState.FAILED.value,),
            ).fetchall()
            for row in rows:
                change = self._from_row(row)
                process = self.process_contract(
                    change.process_key,
                    change.process_version,
                )
                source_stage = process.architecture_source_stage
                revision_row = db.execute(
                    """SELECT * FROM engineering_change_artifacts
                    WHERE change_id=? AND kind='architecture_revision_request'
                    ORDER BY revision DESC LIMIT 1""",
                    (change.change_id,),
                ).fetchone()
                if revision_row is None:
                    continue
                revision_payload = self.work._decode_json(revision_row["payload"])
                if not isinstance(revision_payload, dict):
                    continue
                source_attempt = revision_payload.get("source_attempt")
                if not isinstance(source_attempt, int) or source_attempt <= 1:
                    continue

                stage_row = db.execute(
                    """SELECT * FROM engineering_change_stages
                    WHERE change_id=? AND stage_key=? AND attempt=?""",
                    (change.change_id, source_stage.stage_key, source_attempt),
                ).fetchone()
                if stage_row is None:
                    continue
                work_row = db.execute(
                    "SELECT * FROM work_items WHERE work_id=?",
                    (stage_row["work_id"],),
                ).fetchone()
                if work_row is None:
                    continue
                work = self.work._item_from_row(work_row)
                if work.state is not WorkState.FAILED:
                    continue

                failure_kinds: set[str] = set()
                step_rows = db.execute(
                    """SELECT * FROM work_steps
                    WHERE work_id=? AND state='failed'
                    ORDER BY created_at, step_id""",
                    (work.work_id,),
                ).fetchall()
                for step_row in step_rows:
                    step = self.work._step_from_row(step_row)
                    error = " ".join(str(step.error or "").split()).casefold()
                    if step.kind == "brain_reasoning" and (
                        "servers are currently overloaded" in error
                        or "servers overloaded" in error
                    ):
                        failure_kinds.add("provider_overload")
                    if step.kind == "acq_verify_pypi_sdk" and (
                        "package name must be a python distribution name" in error
                    ):
                        failure_kinds.add("legacy_pypi_url_identity")

                if not failure_kinds:
                    continue

                previous_architecture_id = str(
                    revision_payload.get("previous_architecture_artifact_id") or ""
                ).strip()
                current_architecture = db.execute(
                    """SELECT artifact_id FROM engineering_change_artifacts
                    WHERE change_id=? AND kind='architecture'
                    ORDER BY revision DESC LIMIT 1""",
                    (change.change_id,),
                ).fetchone()
                if (
                    not previous_architecture_id
                    or current_architecture is None
                    or current_architecture["artifact_id"]
                    != previous_architecture_id
                ):
                    continue

                event_key = (
                    f"architecture-revision-compat-recovery:{generation}:{work.work_id}"
                )
                if (
                    db.execute(
                        """SELECT 1 FROM engineering_change_events
                        WHERE change_id=? AND event_key=?""",
                        (change.change_id, event_key),
                    ).fetchone()
                    is not None
                ):
                    continue

                max_attempt = int(
                    db.execute(
                        """SELECT COALESCE(MAX(attempt), 0)
                        FROM engineering_change_stages
                        WHERE change_id=? AND stage_key=?""",
                        (change.change_id, source_stage.stage_key),
                    ).fetchone()[0]
                )
                replacement_attempt = max_attempt + 1
                replacement_payload = dict(revision_payload)
                replacement_payload["source_attempt"] = replacement_attempt
                replacement_payload["compatibility_recovery"] = {
                    "generation": generation,
                    "failed_work_id": work.work_id,
                    "failure_kinds": sorted(failure_kinds),
                }
                artifact_revision = int(
                    db.execute(
                        """SELECT COALESCE(MAX(revision), 0) + 1
                        FROM engineering_change_artifacts
                        WHERE change_id=? AND kind='architecture_revision_request'""",
                        (change.change_id,),
                    ).fetchone()[0]
                )
                artifact = ChangeArtifact(
                    artifact_id="artifact_" + uuid.uuid4().hex[:16],
                    change_id=change.change_id,
                    kind="architecture_revision_request",
                    revision=artifact_revision,
                    digest=_digest(replacement_payload),
                    payload=replacement_payload,
                    created_at=_now(),
                )
                db.execute(
                    "INSERT INTO engineering_change_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact.artifact_id,
                        artifact.change_id,
                        artifact.kind,
                        artifact.revision,
                        artifact.digest,
                        self.work._encode_json(replacement_payload),
                        artifact.created_at,
                    ),
                )

                timestamp = _now()
                cursor = db.execute(
                    """UPDATE engineering_changes
                    SET state=?, version=version+1, updated_at=?
                    WHERE change_id=? AND version=? AND state=?""",
                    (
                        ChangeState.RESEARCHING.value,
                        timestamp,
                        change.change_id,
                        change.version,
                        ChangeState.FAILED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ChangeConflict(
                        "stale architecture revision compatibility recovery"
                    )
                self._event(
                    db,
                    change.change_id,
                    f"artifact:{artifact.artifact_id}",
                    "artifact",
                    {
                        "kind": artifact.kind,
                        "revision": artifact.revision,
                        "digest": artifact.digest,
                    },
                )
                self._event(
                    db,
                    change.change_id,
                    event_key,
                    "architecture_revision_compatibility_reopened",
                    {
                        "generation": generation,
                        "failed_work_id": work.work_id,
                        "failed_source_attempt": source_attempt,
                        "replacement_source_attempt": replacement_attempt,
                        "failure_kinds": sorted(failure_kinds),
                        "from": ChangeState.FAILED.value,
                        "to": ChangeState.RESEARCHING.value,
                    },
                )
                recovered.append(change.change_id)
        return tuple(recovered)

    def reopen_failed_stage_for_retry(
        self,
        work_id: str,
    ) -> EngineeringChange | None:
        """Reopen only the exact failed change stage being explicitly retried.

        FAILED remains terminal for ordinary lifecycle transitions. This narrow
        recovery path is available only when the linked canonical WorkItem is also
        FAILED and the same stage can still be admitted under its preserved evidence.
        """

        normalized_work_id = str(work_id).strip()
        if not normalized_work_id:
            raise ValueError("work_id must not be empty")

        with self.work._lock, self.work._connect() as db:
            stage_row = db.execute(
                "SELECT * FROM engineering_change_stages WHERE work_id=?",
                (normalized_work_id,),
            ).fetchone()
            if stage_row is None:
                return None

            change_row = db.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (stage_row["change_id"],),
            ).fetchone()
            if change_row is None:
                raise ChangeConflict("retry stage has no EngineeringChange")
            change = self._from_row(change_row)

            work_row = db.execute(
                "SELECT * FROM work_items WHERE work_id=?",
                (normalized_work_id,),
            ).fetchone()
            if work_row is None:
                raise ChangeConflict("retry stage has no canonical WorkItem")
            work = self.work._item_from_row(work_row)
            if work.state is not WorkState.FAILED:
                raise ChangeConflict("change retry requires a failed stage WorkItem")

            process = self.process_contract(
                change.process_key,
                change.process_version,
            )
            stage_contract = process.stage_for_key(stage_row["stage_key"])

            if stage_contract.role is ProcessStageRole.ARCHITECTURE_SOURCE:
                target_state = ChangeState.RESEARCHING
            elif stage_contract.role is ProcessStageRole.DEVELOPMENT:
                latest_architecture = db.execute(
                    """SELECT artifact_id
                    FROM engineering_change_artifacts
                    WHERE change_id=? AND kind='architecture'
                    ORDER BY revision DESC LIMIT 1""",
                    (change.change_id,),
                ).fetchone()
                if (
                    latest_architecture is None
                    or stage_row["plan_artifact_id"]
                    != latest_architecture["artifact_id"]
                ):
                    raise ChangeConflict(
                        "failed development retry belongs to an older architecture"
                    )
                target_state = ChangeState.DEVELOPING
            else:  # pragma: no cover - process validation owns known roles
                raise ChangeConflict("unregistered change stage role")

            if change.state is target_state:
                return None
            if change.state is not ChangeState.FAILED:
                raise ChangeConflict(
                    "only the failed governing EngineeringChange may be reopened"
                )

            timestamp = _now()
            cursor = db.execute(
                """UPDATE engineering_changes
                SET state=?, version=version+1, updated_at=?
                WHERE change_id=? AND version=? AND state=?""",
                (
                    target_state.value,
                    timestamp,
                    change.change_id,
                    change.version,
                    ChangeState.FAILED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ChangeConflict("stale failed-change retry recovery")

            self._event(
                db,
                change.change_id,
                f"stage-retry:{normalized_work_id}:v{work.version}",
                "failed_stage_reopened",
                {
                    "work_id": normalized_work_id,
                    "stage_key": stage_row["stage_key"],
                    "attempt": stage_row["attempt"],
                    "from": ChangeState.FAILED.value,
                    "to": target_state.value,
                    "work_version": work.version,
                },
            )
            reopened_row = db.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (change.change_id,),
            ).fetchone()
            assert reopened_row is not None
            return self._from_row(reopened_row)

    def stage_for_work(self, work_id: str) -> ChangeStage | None:
        with self.work._lock, self.work._connect() as db:
            row = db.execute(
                "SELECT * FROM engineering_change_stages WHERE work_id=?", (work_id,)
            ).fetchone()
        return (
            None
            if row is None
            else ChangeStage(
                row["change_id"],
                row["stage_key"],
                row["attempt"],
                row["work_id"],
                row["plan_artifact_id"],
            )
        )

    def work_admitted(self, work_id: str) -> bool:
        """Existing direct WorkItems are unaffected; change WorkItems need current gates."""
        with self.work._lock, self.work._connect() as db:
            stage = db.execute(
                "SELECT change_id, stage_key, plan_artifact_id FROM engineering_change_stages WHERE work_id=?",
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
                change = self._from_row(row)
                self._admit_stage(db, change, stage["stage_key"])
                process = self.process_contract(
                    change.process_key,
                    change.process_version,
                )
                stage_contract = process.stage_for_key(stage["stage_key"])
                if stage_contract.role is ProcessStageRole.DEVELOPMENT:
                    latest = db.execute(
                        """SELECT artifact_id FROM engineering_change_artifacts
                        WHERE change_id=? AND kind='architecture'
                        ORDER BY revision DESC LIMIT 1""",
                        (stage["change_id"],),
                    ).fetchone()
                    if (
                        latest is None
                        or latest["artifact_id"] != stage["plan_artifact_id"]
                    ):
                        return False
            except (ChangeConflict, UnsupportedProcess):
                return False
            return True

    def _admit_stage(
        self,
        db: sqlite3.Connection,
        change: EngineeringChange,
        stage_key: str,
    ) -> None:
        process = self.process_contract(change.process_key, change.process_version)
        stage = process.stage_for_key(stage_key)
        if stage.role is ProcessStageRole.ARCHITECTURE_SOURCE:
            if change.state is not ChangeState.RESEARCHING:
                raise ChangeConflict("architecture-source stage is not admitted")
            return
        if stage.role is not ProcessStageRole.DEVELOPMENT or change.state not in {
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

    def mark_promoted(
        self,
        change_id: str,
        *,
        artifact_id: str,
        artifact_digest: str,
        expected_version: int,
    ) -> EngineeringChange:
        """Enter PROMOTED only from the exact current approved promotion artifact."""
        with self.work._lock, self.work._connect() as connection:
            row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (change_id,),
            ).fetchone()
            if row is None:
                raise ChangeConflict("unknown change")
            current = self._from_row(row)
            if (
                current.version != expected_version
                or current.state is not ChangeState.WAITING_PROMOTION_APPROVAL
            ):
                raise ChangeConflict("change is not awaiting exact promotion")

            latest = connection.execute(
                """SELECT artifact_id, digest FROM engineering_change_artifacts
                WHERE change_id=? AND kind='promotion'
                ORDER BY revision DESC LIMIT 1""",
                (change_id,),
            ).fetchone()
            if latest is None or (
                latest["artifact_id"],
                latest["digest"],
            ) != (artifact_id, artifact_digest):
                raise ChangeConflict(
                    "promotion artifact is missing, stale, or mismatched"
                )

            approved = connection.execute(
                """SELECT 1 FROM engineering_change_gates AS gate
                JOIN engineering_change_decisions AS decision USING (gate_id)
                WHERE gate.change_id=? AND gate.kind='promotion'
                  AND gate.artifact_id=? AND gate.artifact_digest=?
                  AND decision.approved=1""",
                (change_id, artifact_id, artifact_digest),
            ).fetchone()
            if approved is None:
                raise ChangeConflict("current promotion artifact has no owner approval")

            timestamp = _now()
            cursor = connection.execute(
                """UPDATE engineering_changes
                SET state=?, version=version+1, updated_at=?
                WHERE change_id=? AND version=?""",
                (
                    ChangeState.PROMOTED.value,
                    timestamp,
                    change_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ChangeConflict("stale promotion transition")
            self._event(
                connection,
                change_id,
                f"transition:{expected_version + 1}",
                "transition",
                {
                    "from": current.state.value,
                    "to": ChangeState.PROMOTED.value,
                    "promotion_artifact_id": artifact_id,
                    "promotion_artifact_digest": artifact_digest,
                },
            )
            updated = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (change_id,),
            ).fetchone()
            assert updated is not None
            return self._from_row(updated)

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
            self._event(
                connection,
                change_id,
                f"transition:{current.version + 1}",
                "transition",
                {"from": current.state.value, "to": state.value},
            )
            return self._from_row(
                connection.execute(
                    "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
                ).fetchone()
            )

    def request_architecture_revision_for_work(
        self,
        work_id: str,
        *,
        reason: str,
    ) -> EngineeringChange:
        """Return governed development to research without asking for ad-hoc approval."""

        normalized_work_id = str(work_id).strip()
        normalized_reason = " ".join(str(reason).split()).strip()
        if not normalized_work_id or not normalized_reason:
            raise ChangeConflict(
                "work identity and architecture revision reason are required"
            )

        with self.work._lock, self.work._connect() as connection:
            stage_row = connection.execute(
                """SELECT change_id, stage_key, attempt
                FROM engineering_change_stages WHERE work_id=?""",
                (normalized_work_id,),
            ).fetchone()
            if stage_row is None:
                raise ChangeConflict("architecture revision work is not change-owned")

            change_row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (stage_row["change_id"],),
            ).fetchone()
            if change_row is None:
                raise ChangeConflict("architecture revision change is missing")
            change = self._from_row(change_row)
            process = self.process_contract(change.process_key, change.process_version)
            stage_contract = process.stage_for_key(stage_row["stage_key"])
            if stage_contract.role is not ProcessStageRole.DEVELOPMENT:
                raise ChangeConflict(
                    "architecture revision may only originate from development"
                )

            existing_revision_row = connection.execute(
                """SELECT payload
                FROM engineering_change_artifacts
                WHERE change_id=? AND kind='architecture_revision_request'
                ORDER BY revision DESC LIMIT 1""",
                (change.change_id,),
            ).fetchone()
            if existing_revision_row is not None:
                existing_payload = self.work._decode_json(
                    existing_revision_row["payload"]
                )
                if (
                    isinstance(existing_payload, dict)
                    and existing_payload.get("development_work_id")
                    == normalized_work_id
                    and change.state is not ChangeState.DEVELOPING
                ):
                    # DBOS may replay after the revision artifact + state transition
                    # committed but before the superseded development WorkItem was
                    # durably cancelled. Reuse that exact revision request.
                    return change

            if change.state is not ChangeState.DEVELOPING:
                raise ChangeConflict(
                    "architecture revision requires an actively developing change"
                )

            architecture_row = connection.execute(
                """SELECT artifact_id, revision, digest
                FROM engineering_change_artifacts
                WHERE change_id=? AND kind='architecture'
                ORDER BY revision DESC LIMIT 1""",
                (change.change_id,),
            ).fetchone()
            if architecture_row is None:
                raise ChangeConflict(
                    "architecture revision requires approved architecture"
                )

            source_stage = process.architecture_source_stage
            max_attempt = connection.execute(
                """SELECT COALESCE(MAX(attempt), 0)
                FROM engineering_change_stages
                WHERE change_id=? AND stage_key=?""",
                (change.change_id, source_stage.stage_key),
            ).fetchone()[0]
            source_attempt = int(max_attempt) + 1
            payload: dict[str, object] = {
                "schema": "architecture_revision_request.v1",
                "development_work_id": normalized_work_id,
                "development_attempt": int(stage_row["attempt"]),
                "previous_architecture_artifact_id": architecture_row["artifact_id"],
                "previous_architecture_revision": int(architecture_row["revision"]),
                "previous_architecture_digest": architecture_row["digest"],
                "source_stage_key": source_stage.stage_key,
                "source_attempt": source_attempt,
                "reason": normalized_reason[:1000],
            }
            digest = _digest(payload)
            revision = connection.execute(
                """SELECT COALESCE(MAX(revision), 0) + 1
                FROM engineering_change_artifacts
                WHERE change_id=? AND kind='architecture_revision_request'""",
                (change.change_id,),
            ).fetchone()[0]
            artifact = ChangeArtifact(
                artifact_id="artifact_" + uuid.uuid4().hex[:16],
                change_id=change.change_id,
                kind="architecture_revision_request",
                revision=int(revision),
                digest=digest,
                payload=payload,
                created_at=_now(),
            )
            connection.execute(
                "INSERT INTO engineering_change_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact.artifact_id,
                    artifact.change_id,
                    artifact.kind,
                    artifact.revision,
                    artifact.digest,
                    self.work._encode_json(payload),
                    artifact.created_at,
                ),
            )
            timestamp = _now()
            cursor = connection.execute(
                """UPDATE engineering_changes
                SET state=?, version=version+1, updated_at=?
                WHERE change_id=? AND version=?""",
                (
                    ChangeState.RESEARCHING.value,
                    timestamp,
                    change.change_id,
                    change.version,
                ),
            )
            if cursor.rowcount != 1:
                raise ChangeConflict("stale architecture revision request")
            self._event(
                connection,
                change.change_id,
                f"artifact:{artifact.artifact_id}",
                "artifact",
                {
                    "kind": artifact.kind,
                    "revision": artifact.revision,
                    "digest": artifact.digest,
                },
            )
            self._event(
                connection,
                change.change_id,
                f"architecture-revision:{artifact.artifact_id}",
                "architecture_revision_requested",
                {
                    "development_work_id": normalized_work_id,
                    "source_attempt": source_attempt,
                    "reason": normalized_reason[:1000],
                },
            )
            updated = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?",
                (change.change_id,),
            ).fetchone()
            assert updated is not None
            return self._from_row(updated)

    def add_artifact(
        self, change_id: str, *, kind: str, payload: dict[str, object]
    ) -> ChangeArtifact:
        if not kind.strip() or not isinstance(payload, dict):
            raise ChangeConflict("artifact kind and object payload are required")
        digest = _digest(payload)
        with self.work._lock, self.work._connect() as connection:
            change_row = connection.execute(
                "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
            ).fetchone()
            if change_row is None:
                raise ChangeConflict("unknown change")
            change = self._from_row(change_row)
            if kind == "architecture" and change.state in {
                ChangeState.PROMOTED,
                ChangeState.OBSERVING,
                ChangeState.CLOSED,
                ChangeState.REJECTED,
                ChangeState.FAILED,
                ChangeState.SUPERSEDED,
                ChangeState.ROLLED_BACK,
            }:
                raise ChangeConflict(
                    "terminal or promoted change cannot revise architecture"
                )
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
            self._event(
                connection,
                change_id,
                f"artifact:{artifact.artifact_id}",
                "artifact",
                {"kind": kind, "revision": revision, "digest": digest},
            )
            if kind == "architecture" and change.state in {
                ChangeState.WAITING_OWNER_APPROVAL,
                ChangeState.APPROVED_FOR_BUILD,
                ChangeState.DEVELOPING,
                ChangeState.VERIFYING,
                ChangeState.WAITING_OWNER_ACCEPTANCE,
                ChangeState.READY_FOR_PROMOTION,
                ChangeState.WAITING_PROMOTION_APPROVAL,
            }:
                connection.execute(
                    """UPDATE engineering_changes SET state=?, version=version+1,
                    updated_at=? WHERE change_id=?""",
                    (ChangeState.ARCHITECTURE_READY.value, _now(), change_id),
                )
                self._event(
                    connection,
                    change_id,
                    f"revised:{artifact.artifact_id}",
                    "architecture_revised",
                    {"previous_state": change.state.value},
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
                return ChangeStage(
                    change_id,
                    stage_key,
                    attempt,
                    item.work_id,
                    connection.execute(
                        """SELECT plan_artifact_id FROM engineering_change_stages
                        WHERE change_id=? AND stage_key=? AND attempt=?""",
                        (change_id, stage_key, attempt),
                    ).fetchone()[0],
                )
            plan_artifact_id = None
            change = self._from_row(change_row)
            process = self.process_contract(change.process_key, change.process_version)
            stage_contract = process.stage_for_key(stage_key)
            if stage_contract.role is ProcessStageRole.DEVELOPMENT:
                latest = connection.execute(
                    """SELECT artifact_id FROM engineering_change_artifacts
                    WHERE change_id=? AND kind='architecture'
                    ORDER BY revision DESC LIMIT 1""",
                    (change_id,),
                ).fetchone()
                if latest is None:
                    raise ChangeConflict("approved architecture is missing")
                plan_artifact_id = latest[0]
            self.work._validate_dependency_graph(connection, item)
            try:
                self.work._insert_item(connection, item)
                connection.execute(
                    "INSERT INTO engineering_change_stages VALUES (?, ?, ?, ?, ?)",
                    (change_id, stage_key, attempt, item.work_id, plan_artifact_id),
                )
                self._event(
                    connection,
                    change_id,
                    f"stage:{stage_key}:{attempt}",
                    "stage",
                    {"work_id": item.work_id, "plan_artifact_id": plan_artifact_id},
                )
            except sqlite3.IntegrityError as exc:
                raise ChangeConflict("stage WorkItem link violates identity") from exc
            return ChangeStage(
                change_id, stage_key, attempt, item.work_id, plan_artifact_id
            )
