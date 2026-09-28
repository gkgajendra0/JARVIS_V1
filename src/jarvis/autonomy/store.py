"""WorkStore-backed durable autonomy state for Phase 10A."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from typing import Any, TypeVar

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.store import SQLiteWorkStore

from .models import (
    ActionCandidateV1,
    CandidateDispositionRecordV1,
    DispatchIntentV1,
    AutonomyFindingEventV1,
    AutonomyFindingV1,
    AutonomyOutcomeRecordV1,
    DesiredStateV1,
    ObjectiveV1,
    OwnerAttentionEventV1,
    OwnerAttentionItemV1,
    ReconcileRunV1,
)
from .system_state import SystemStateSnapshotV1

AUTONOMY_SCHEMA_VERSION = 2
_AUTONOMY_SCHEMA_V1_CHECKSUM = (
    "f4a0bd325651c34576debdbe58f2aee82486540b7b517553cf07acf514ca4c5e"
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS autonomy_schema (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_objectives (
    objective_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK(generation > 0),
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    updated_at_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_desired_states (
    desired_state_id TEXT PRIMARY KEY,
    objective_id TEXT NOT NULL
        REFERENCES autonomy_objectives(objective_id),
    generation INTEGER NOT NULL CHECK(generation > 0),
    status TEXT NOT NULL,
    rule_key TEXT NOT NULL,
    rule_version INTEGER NOT NULL CHECK(rule_version > 0),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    updated_at_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_findings (
    finding_id TEXT PRIMARY KEY,
    desired_state_id TEXT NOT NULL
        REFERENCES autonomy_desired_states(desired_state_id),
    desired_generation INTEGER NOT NULL CHECK(desired_generation > 0),
    status TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    first_seen_epoch REAL NOT NULL,
    last_seen_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_finding_events (
    event_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL
        REFERENCES autonomy_findings(finding_id),
    event_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    UNIQUE(finding_id, event_key)
);

CREATE TABLE IF NOT EXISTS autonomy_action_candidates (
    candidate_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL
        REFERENCES autonomy_findings(finding_id),
    desired_state_id TEXT NOT NULL
        REFERENCES autonomy_desired_states(desired_state_id),
    desired_generation INTEGER NOT NULL CHECK(desired_generation > 0),
    action_kind TEXT NOT NULL,
    mode TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_candidate_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL
        REFERENCES autonomy_action_candidates(candidate_id),
    disposition TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_dispatch_intents (
    intent_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL
        REFERENCES autonomy_action_candidates(candidate_id),
    action_kind TEXT NOT NULL,
    dispatch_role TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    UNIQUE(candidate_id, dispatch_role)
);

CREATE TABLE IF NOT EXISTS autonomy_dispatch_links (
    dispatch_link_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL
        REFERENCES autonomy_action_candidates(candidate_id),
    dispatch_role TEXT NOT NULL,
    downstream_kind TEXT NOT NULL,
    downstream_id TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    UNIQUE(candidate_id, dispatch_role)
);

CREATE TABLE IF NOT EXISTS autonomy_owner_attention (
    attention_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    group_key TEXT NOT NULL,
    objective_id TEXT NOT NULL
        REFERENCES autonomy_objectives(objective_id),
    finding_id TEXT NOT NULL
        REFERENCES autonomy_findings(finding_id),
    candidate_id TEXT
        REFERENCES autonomy_action_candidates(candidate_id),
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    first_occurrence_epoch REAL NOT NULL,
    last_occurrence_epoch REAL NOT NULL,
    next_renotify_epoch REAL,
    UNIQUE(fingerprint, status)
);

CREATE TABLE IF NOT EXISTS autonomy_attention_events (
    event_id TEXT PRIMARY KEY,
    attention_id TEXT NOT NULL
        REFERENCES autonomy_owner_attention(attention_id),
    event_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    UNIQUE(attention_id, event_key)
);

CREATE TABLE IF NOT EXISTS autonomy_system_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    snapshot_digest TEXT NOT NULL UNIQUE CHECK(length(snapshot_digest) = 64),
    payload TEXT NOT NULL,
    created_at_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_outcome_links (
    outcome_record_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL
        REFERENCES autonomy_action_candidates(candidate_id),
    dispatch_link_id TEXT NOT NULL,
    downstream_source_kind TEXT NOT NULL,
    downstream_source_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    recorded_at_epoch REAL NOT NULL,
    UNIQUE(candidate_id, dispatch_link_id)
);

CREATE TABLE IF NOT EXISTS autonomy_reconcile_runs (
    reconcile_run_id TEXT PRIMARY KEY,
    request_token TEXT NOT NULL UNIQUE,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    desired_generation_digest TEXT NOT NULL
        CHECK(length(desired_generation_digest) = 64),
    snapshot_digest TEXT,
    handled_token TEXT UNIQUE,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    started_at_epoch REAL NOT NULL,
    ended_at_epoch REAL
);

CREATE TABLE IF NOT EXISTS autonomy_budget_windows (
    policy_id TEXT NOT NULL,
    dimension_key TEXT NOT NULL,
    window_started_epoch REAL NOT NULL,
    window_seconds REAL NOT NULL CHECK(window_seconds > 0),
    used_value REAL NOT NULL CHECK(used_value >= 0),
    version INTEGER NOT NULL CHECK(version > 0),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    payload TEXT NOT NULL,
    PRIMARY KEY(policy_id, dimension_key, window_started_epoch)
);

CREATE INDEX IF NOT EXISTS idx_autonomy_objectives_status_priority
    ON autonomy_objectives(status, priority DESC, updated_at_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_desired_objective_status
    ON autonomy_desired_states(objective_id, status, updated_at_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_findings_status_last_seen
    ON autonomy_findings(status, last_seen_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_candidates_finding_created
    ON autonomy_action_candidates(finding_id, created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_candidate_decisions_candidate_created
    ON autonomy_candidate_decisions(candidate_id, created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_dispatch_intents_candidate_created
    ON autonomy_dispatch_intents(candidate_id, created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_attention_status_priority
    ON autonomy_owner_attention(status, priority DESC, last_occurrence_epoch);
CREATE INDEX IF NOT EXISTS idx_autonomy_reconcile_status_started
    ON autonomy_reconcile_runs(status, started_at_epoch);
"""

AUTONOMY_SCHEMA_CHECKSUM = hashlib.sha256(
    (_SCHEMA_SQL.strip() + "|phase10a.4-workstore-extension-v2").encode()
).hexdigest()

_EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "autonomy_schema": frozenset({"version", "checksum"}),
    "autonomy_objectives": frozenset(
        {
            "objective_id",
            "generation",
            "status",
            "priority",
            "payload_digest",
            "payload",
            "created_at_epoch",
            "updated_at_epoch",
        }
    ),
    "autonomy_desired_states": frozenset(
        {
            "desired_state_id",
            "objective_id",
            "generation",
            "status",
            "rule_key",
            "rule_version",
            "payload_digest",
            "payload",
            "created_at_epoch",
            "updated_at_epoch",
        }
    ),
    "autonomy_findings": frozenset(
        {
            "finding_id",
            "desired_state_id",
            "desired_generation",
            "status",
            "version",
            "payload_digest",
            "payload",
            "first_seen_epoch",
            "last_seen_epoch",
        }
    ),
    "autonomy_finding_events": frozenset(
        {
            "event_id",
            "finding_id",
            "event_key",
            "kind",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_action_candidates": frozenset(
        {
            "candidate_id",
            "finding_id",
            "desired_state_id",
            "desired_generation",
            "action_kind",
            "mode",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_candidate_decisions": frozenset(
        {
            "decision_id",
            "candidate_id",
            "disposition",
            "source_identity",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_dispatch_intents": frozenset(
        {
            "intent_id",
            "candidate_id",
            "action_kind",
            "dispatch_role",
            "source_identity",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_dispatch_links": frozenset(
        {
            "dispatch_link_id",
            "candidate_id",
            "dispatch_role",
            "downstream_kind",
            "downstream_id",
            "source_identity",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_owner_attention": frozenset(
        {
            "attention_id",
            "fingerprint",
            "group_key",
            "objective_id",
            "finding_id",
            "candidate_id",
            "status",
            "priority",
            "version",
            "payload_digest",
            "payload",
            "first_occurrence_epoch",
            "last_occurrence_epoch",
            "next_renotify_epoch",
        }
    ),
    "autonomy_attention_events": frozenset(
        {
            "event_id",
            "attention_id",
            "event_key",
            "kind",
            "payload_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_system_snapshots": frozenset(
        {
            "snapshot_id",
            "snapshot_digest",
            "payload",
            "created_at_epoch",
        }
    ),
    "autonomy_outcome_links": frozenset(
        {
            "outcome_record_id",
            "candidate_id",
            "dispatch_link_id",
            "downstream_source_kind",
            "downstream_source_id",
            "payload_digest",
            "payload",
            "recorded_at_epoch",
        }
    ),
    "autonomy_reconcile_runs": frozenset(
        {
            "reconcile_run_id",
            "request_token",
            "trigger",
            "status",
            "desired_generation_digest",
            "snapshot_digest",
            "handled_token",
            "payload_digest",
            "payload",
            "started_at_epoch",
            "ended_at_epoch",
        }
    ),
    "autonomy_budget_windows": frozenset(
        {
            "policy_id",
            "dimension_key",
            "window_started_epoch",
            "window_seconds",
            "used_value",
            "version",
            "payload_digest",
            "payload",
        }
    ),
}


class AutonomyStoreError(RuntimeError):
    """Base error for Phase-10A persistence."""


class AutonomyConflictError(AutonomyStoreError):
    """An identity or compare-and-swap conflict."""


class AutonomyIntegrityError(AutonomyStoreError):
    """Stored autonomy state violates the accepted integrity contract."""


T = TypeVar("T")


class AutonomyStore:
    """Additive autonomy-domain state inside the canonical WorkStore database."""

    def __init__(self, work: SQLiteWorkStore) -> None:
        if not isinstance(work, SQLiteWorkStore):
            raise TypeError("work must be a SQLiteWorkStore")
        self.work = work
        self._initialize()

    @property
    def path(self):
        """Expose the canonical WorkStore path; there is no second autonomy database."""

        return self.work.path

    def _initialize(self) -> None:
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name LIKE 'autonomy_%'
                """
            ).fetchall()
            existing_tables = {str(row["name"]) for row in rows}
            ledger_exists = "autonomy_schema" in existing_tables

            if existing_tables and not ledger_exists:
                raise AutonomyIntegrityError(
                    "autonomy tables exist without an autonomy schema ledger"
                )

            if ledger_exists:
                ledger_rows = db.execute(
                    "SELECT version, checksum FROM autonomy_schema ORDER BY version"
                ).fetchall()
                if len(ledger_rows) != 1:
                    raise AutonomyIntegrityError(
                        "autonomy schema ledger must contain exactly one version"
                    )
                row = ledger_rows[0]
                version = int(row["version"])
                checksum = str(row["checksum"])
                if version == 1:
                    if checksum != _AUTONOMY_SCHEMA_V1_CHECKSUM:
                        raise AutonomyIntegrityError("autonomy schema checksum mismatch")
                    db.executescript(_SCHEMA_SQL)
                    db.execute(
                        "UPDATE autonomy_schema SET version=?, checksum=? WHERE version=1",
                        (AUTONOMY_SCHEMA_VERSION, AUTONOMY_SCHEMA_CHECKSUM),
                    )
                    existing_tables = set(_EXPECTED_COLUMNS)
                elif version == AUTONOMY_SCHEMA_VERSION:
                    if checksum != AUTONOMY_SCHEMA_CHECKSUM:
                        raise AutonomyIntegrityError("autonomy schema checksum mismatch")
                    expected_tables = set(_EXPECTED_COLUMNS)
                    if existing_tables != expected_tables:
                        missing = sorted(expected_tables - existing_tables)
                        extra = sorted(existing_tables - expected_tables)
                        raise AutonomyIntegrityError(
                            "autonomy schema table mismatch "
                            f"missing={missing} extra={extra}"
                        )
                else:
                    raise AutonomyIntegrityError("unsupported autonomy schema version")

            db.executescript(_SCHEMA_SQL)

            for table, expected_columns in _EXPECTED_COLUMNS.items():
                actual_columns = frozenset(
                    str(row["name"])
                    for row in db.execute(f"PRAGMA table_info({table})").fetchall()
                )
                if actual_columns != expected_columns:
                    raise AutonomyIntegrityError(f"{table} column contract mismatch")

            if not ledger_exists:
                db.execute(
                    "INSERT INTO autonomy_schema(version, checksum) VALUES (?, ?)",
                    (AUTONOMY_SCHEMA_VERSION, AUTONOMY_SCHEMA_CHECKSUM),
                )

    def _encoded_payload(self, value: Any) -> tuple[str, str]:
        payload = value.to_payload()
        digest = canonical_digest(payload)
        return digest, self.work.encode_extension_json(payload)

    def _decoded_payload(
        self,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        payload = self.work.decode_extension_json(str(row["payload"]))
        if not isinstance(payload, dict):
            raise AutonomyIntegrityError("stored autonomy payload is not an object")
        expected = str(row["payload_digest"])
        actual = canonical_digest(payload)
        if actual != expected:
            raise AutonomyIntegrityError("stored autonomy payload digest mismatch")
        return payload

    def _immutable_create(
        self,
        *,
        table: str,
        identity_column: str,
        identity: str,
        value: Any,
        insert_sql: str,
        params: tuple[Any, ...],
        decoder: Callable[[dict[str, Any]], T],
    ) -> T:
        digest, encoded = self._encoded_payload(value)
        with self.work.extension_transaction() as db:
            existing = db.execute(
                f"SELECT * FROM {table} WHERE {identity_column}=?",
                (identity,),
            ).fetchone()
            if existing is not None:
                payload = self._decoded_payload(existing)
                if str(existing["payload_digest"]) != digest:
                    raise AutonomyConflictError(
                        f"{table} identity already exists with different payload"
                    )
                return decoder(payload)
            try:
                db.execute(insert_sql, (*params, digest, encoded))
            except sqlite3.IntegrityError as exc:
                raise AutonomyConflictError(
                    f"{table} insert violated an autonomy identity constraint"
                ) from exc
        return value

    def create_objective(self, objective: ObjectiveV1) -> ObjectiveV1:
        return self._immutable_create(
            table="autonomy_objectives",
            identity_column="objective_id",
            identity=objective.objective_id,
            value=objective,
            insert_sql="""
                INSERT INTO autonomy_objectives(
                    objective_id, generation, status, priority,
                    created_at_epoch, updated_at_epoch,
                    payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                objective.objective_id,
                objective.generation,
                objective.status.value,
                int(objective.priority),
                objective.created_at_epoch,
                objective.updated_at_epoch,
            ),
            decoder=ObjectiveV1.from_payload,
        )

    def require_objective(self, objective_id: str) -> ObjectiveV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT * FROM autonomy_objectives WHERE objective_id=?",
                (objective_id,),
            ).fetchone()
        if row is None:
            raise KeyError(objective_id)
        return ObjectiveV1.from_payload(self._decoded_payload(row))

    def update_objective(
        self,
        objective: ObjectiveV1,
        *,
        expected_generation: int,
    ) -> ObjectiveV1:
        if objective.generation != expected_generation + 1:
            raise AutonomyConflictError(
                "objective update generation must increment exactly once"
            )
        digest, encoded = self._encoded_payload(objective)
        with self.work.extension_transaction() as db:
            current = db.execute(
                "SELECT * FROM autonomy_objectives WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
            if current is None:
                raise KeyError(objective.objective_id)
            if str(current["payload_digest"]) == digest:
                return ObjectiveV1.from_payload(self._decoded_payload(current))
            if int(current["generation"]) != expected_generation:
                raise AutonomyConflictError("stale objective generation")
            cursor = db.execute(
                """
                UPDATE autonomy_objectives
                SET generation=?, status=?, priority=?, updated_at_epoch=?,
                    payload_digest=?, payload=?
                WHERE objective_id=? AND generation=?
                """,
                (
                    objective.generation,
                    objective.status.value,
                    int(objective.priority),
                    objective.updated_at_epoch,
                    digest,
                    encoded,
                    objective.objective_id,
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise AutonomyConflictError("objective compare-and-swap failed")
        return objective

    def create_desired_state(self, desired: DesiredStateV1) -> DesiredStateV1:
        return self._immutable_create(
            table="autonomy_desired_states",
            identity_column="desired_state_id",
            identity=desired.desired_state_id,
            value=desired,
            insert_sql="""
                INSERT INTO autonomy_desired_states(
                    desired_state_id, objective_id, generation, status,
                    rule_key, rule_version, created_at_epoch, updated_at_epoch,
                    payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                desired.desired_state_id,
                desired.objective_id,
                desired.generation,
                desired.status.value,
                desired.rule_key,
                desired.rule_version,
                desired.created_at_epoch,
                desired.updated_at_epoch,
            ),
            decoder=DesiredStateV1.from_payload,
        )

    def require_desired_state(self, desired_state_id: str) -> DesiredStateV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_desired_states
                WHERE desired_state_id=?
                """,
                (desired_state_id,),
            ).fetchone()
        if row is None:
            raise KeyError(desired_state_id)
        return DesiredStateV1.from_payload(self._decoded_payload(row))

    def update_desired_state(
        self,
        desired: DesiredStateV1,
        *,
        expected_generation: int,
    ) -> DesiredStateV1:
        if desired.generation != expected_generation + 1:
            raise AutonomyConflictError(
                "desired-state generation must increment exactly once"
            )
        digest, encoded = self._encoded_payload(desired)
        with self.work.extension_transaction() as db:
            current = db.execute(
                """
                SELECT * FROM autonomy_desired_states
                WHERE desired_state_id=?
                """,
                (desired.desired_state_id,),
            ).fetchone()
            if current is None:
                raise KeyError(desired.desired_state_id)
            if str(current["payload_digest"]) == digest:
                return DesiredStateV1.from_payload(self._decoded_payload(current))
            if int(current["generation"]) != expected_generation:
                raise AutonomyConflictError("stale desired-state generation")
            cursor = db.execute(
                """
                UPDATE autonomy_desired_states
                SET generation=?, status=?, rule_key=?, rule_version=?,
                    updated_at_epoch=?, payload_digest=?, payload=?
                WHERE desired_state_id=? AND generation=?
                """,
                (
                    desired.generation,
                    desired.status.value,
                    desired.rule_key,
                    desired.rule_version,
                    desired.updated_at_epoch,
                    digest,
                    encoded,
                    desired.desired_state_id,
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise AutonomyConflictError("desired-state compare-and-swap failed")
        return desired

    def create_finding(self, finding: AutonomyFindingV1) -> AutonomyFindingV1:
        return self._immutable_create(
            table="autonomy_findings",
            identity_column="finding_id",
            identity=finding.finding_id,
            value=finding,
            insert_sql="""
                INSERT INTO autonomy_findings(
                    finding_id, desired_state_id, desired_generation,
                    status, version, first_seen_epoch, last_seen_epoch,
                    payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                finding.finding_id,
                finding.desired_state_id,
                finding.desired_generation,
                finding.status.value,
                finding.version,
                finding.first_seen_epoch,
                finding.last_seen_epoch,
            ),
            decoder=AutonomyFindingV1.from_payload,
        )

    def require_finding(self, finding_id: str) -> AutonomyFindingV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT * FROM autonomy_findings WHERE finding_id=?",
                (finding_id,),
            ).fetchone()
        if row is None:
            raise KeyError(finding_id)
        return AutonomyFindingV1.from_payload(self._decoded_payload(row))

    def update_finding(
        self,
        finding: AutonomyFindingV1,
        *,
        expected_version: int,
    ) -> AutonomyFindingV1:
        if finding.version != expected_version + 1:
            raise AutonomyConflictError("finding version must increment exactly once")
        digest, encoded = self._encoded_payload(finding)
        with self.work.extension_transaction() as db:
            current = db.execute(
                "SELECT * FROM autonomy_findings WHERE finding_id=?",
                (finding.finding_id,),
            ).fetchone()
            if current is None:
                raise KeyError(finding.finding_id)
            if str(current["payload_digest"]) == digest:
                return AutonomyFindingV1.from_payload(self._decoded_payload(current))
            if int(current["version"]) != expected_version:
                raise AutonomyConflictError("stale finding version")
            cursor = db.execute(
                """
                UPDATE autonomy_findings
                SET desired_generation=?, status=?, version=?,
                    last_seen_epoch=?, payload_digest=?, payload=?
                WHERE finding_id=? AND version=?
                """,
                (
                    finding.desired_generation,
                    finding.status.value,
                    finding.version,
                    finding.last_seen_epoch,
                    digest,
                    encoded,
                    finding.finding_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AutonomyConflictError("finding compare-and-swap failed")
        return finding

    def append_finding_event(
        self,
        event: AutonomyFindingEventV1,
    ) -> AutonomyFindingEventV1:
        digest, encoded = self._encoded_payload(event)
        with self.work.extension_transaction() as db:
            existing = db.execute(
                """
                SELECT * FROM autonomy_finding_events
                WHERE finding_id=? AND event_key=?
                """,
                (event.finding_id, event.event_key),
            ).fetchone()
            if existing is not None:
                payload = self._decoded_payload(existing)
                if str(existing["payload_digest"]) != digest:
                    raise AutonomyConflictError(
                        "finding event key reused with different payload"
                    )
                return AutonomyFindingEventV1.from_payload(payload)
            try:
                db.execute(
                    """
                    INSERT INTO autonomy_finding_events(
                        event_id, finding_id, event_key, kind,
                        created_at_epoch, payload_digest, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.finding_id,
                        event.event_key,
                        event.kind,
                        event.created_at_epoch,
                        digest,
                        encoded,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutonomyConflictError("finding event identity conflict") from exc
        return event

    def list_finding_events(
        self,
        finding_id: str,
    ) -> tuple[AutonomyFindingEventV1, ...]:
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM autonomy_finding_events
                WHERE finding_id=? ORDER BY rowid
                """,
                (finding_id,),
            ).fetchall()
        return tuple(
            AutonomyFindingEventV1.from_payload(self._decoded_payload(row))
            for row in rows
        )

    def create_action_candidate(
        self,
        candidate: ActionCandidateV1,
    ) -> ActionCandidateV1:
        return self._immutable_create(
            table="autonomy_action_candidates",
            identity_column="candidate_id",
            identity=candidate.candidate_id,
            value=candidate,
            insert_sql="""
                INSERT INTO autonomy_action_candidates(
                    candidate_id, finding_id, desired_state_id,
                    desired_generation, action_kind, mode, created_at_epoch,
                    payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                candidate.candidate_id,
                candidate.finding_id,
                candidate.desired_state_id,
                candidate.desired_generation,
                candidate.action_kind.value,
                candidate.mode.value,
                candidate.created_at_epoch,
            ),
            decoder=ActionCandidateV1.from_payload,
        )

    def require_action_candidate(self, candidate_id: str) -> ActionCandidateV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_action_candidates
                WHERE candidate_id=?
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return ActionCandidateV1.from_payload(self._decoded_payload(row))

    def list_action_candidates(
        self,
        finding_id: str,
    ) -> tuple[ActionCandidateV1, ...]:
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM autonomy_action_candidates
                WHERE finding_id=? ORDER BY rowid
                """,
                (finding_id,),
            ).fetchall()
        return tuple(
            ActionCandidateV1.from_payload(self._decoded_payload(row))
            for row in rows
        )

    def record_candidate_decision(
        self,
        decision: CandidateDispositionRecordV1,
    ) -> CandidateDispositionRecordV1:
        return self._immutable_create(
            table="autonomy_candidate_decisions",
            identity_column="decision_id",
            identity=decision.decision_id,
            value=decision,
            insert_sql="""
                INSERT INTO autonomy_candidate_decisions(
                    decision_id, candidate_id, disposition, source_identity,
                    created_at_epoch, payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                decision.decision_id,
                decision.candidate_id,
                decision.disposition.value,
                decision.source_identity,
                decision.created_at_epoch,
            ),
            decoder=CandidateDispositionRecordV1.from_payload,
        )

    def list_candidate_decisions(
        self,
        candidate_id: str,
    ) -> tuple[CandidateDispositionRecordV1, ...]:
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM autonomy_candidate_decisions
                WHERE candidate_id=? ORDER BY rowid
                """,
                (candidate_id,),
            ).fetchall()
        return tuple(
            CandidateDispositionRecordV1.from_payload(self._decoded_payload(row))
            for row in rows
        )

    def latest_candidate_decision(
        self,
        candidate_id: str,
    ) -> CandidateDispositionRecordV1 | None:
        decisions = self.list_candidate_decisions(candidate_id)
        return decisions[-1] if decisions else None

    def record_dispatch_intent(
        self,
        intent: DispatchIntentV1,
    ) -> DispatchIntentV1:
        return self._immutable_create(
            table="autonomy_dispatch_intents",
            identity_column="intent_id",
            identity=intent.intent_id,
            value=intent,
            insert_sql="""
                INSERT INTO autonomy_dispatch_intents(
                    intent_id, candidate_id, action_kind, dispatch_role,
                    source_identity, created_at_epoch, payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                intent.intent_id,
                intent.candidate_id,
                intent.action_kind.value,
                intent.dispatch_role,
                intent.source_identity,
                intent.created_at_epoch,
            ),
            decoder=DispatchIntentV1.from_payload,
        )

    def require_dispatch_intent(
        self,
        intent_id: str,
    ) -> DispatchIntentV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_dispatch_intents
                WHERE intent_id=?
                """,
                (intent_id,),
            ).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return DispatchIntentV1.from_payload(self._decoded_payload(row))

    def create_owner_attention(
        self,
        item: OwnerAttentionItemV1,
    ) -> OwnerAttentionItemV1:
        return self._immutable_create(
            table="autonomy_owner_attention",
            identity_column="attention_id",
            identity=item.attention_id,
            value=item,
            insert_sql="""
                INSERT INTO autonomy_owner_attention(
                    attention_id, fingerprint, group_key, objective_id,
                    finding_id, candidate_id, status, priority, version,
                    first_occurrence_epoch, last_occurrence_epoch,
                    next_renotify_epoch, payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                item.attention_id,
                item.fingerprint,
                item.group_key,
                item.objective_id,
                item.finding_id,
                item.candidate_id,
                item.status.value,
                int(item.priority),
                item.version,
                item.first_occurrence_epoch,
                item.last_occurrence_epoch,
                item.next_renotify_epoch,
            ),
            decoder=OwnerAttentionItemV1.from_payload,
        )

    def require_owner_attention(
        self,
        attention_id: str,
    ) -> OwnerAttentionItemV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_owner_attention
                WHERE attention_id=?
                """,
                (attention_id,),
            ).fetchone()
        if row is None:
            raise KeyError(attention_id)
        return OwnerAttentionItemV1.from_payload(self._decoded_payload(row))

    def update_owner_attention(
        self,
        item: OwnerAttentionItemV1,
        *,
        expected_version: int,
    ) -> OwnerAttentionItemV1:
        if item.version != expected_version + 1:
            raise AutonomyConflictError(
                "owner-attention version must increment exactly once"
            )
        digest, encoded = self._encoded_payload(item)
        with self.work.extension_transaction() as db:
            current = db.execute(
                """
                SELECT * FROM autonomy_owner_attention
                WHERE attention_id=?
                """,
                (item.attention_id,),
            ).fetchone()
            if current is None:
                raise KeyError(item.attention_id)
            if str(current["payload_digest"]) == digest:
                return OwnerAttentionItemV1.from_payload(self._decoded_payload(current))
            if int(current["version"]) != expected_version:
                raise AutonomyConflictError("stale owner-attention version")
            cursor = db.execute(
                """
                UPDATE autonomy_owner_attention
                SET status=?, priority=?, version=?, last_occurrence_epoch=?,
                    next_renotify_epoch=?, payload_digest=?, payload=?
                WHERE attention_id=? AND version=?
                """,
                (
                    item.status.value,
                    int(item.priority),
                    item.version,
                    item.last_occurrence_epoch,
                    item.next_renotify_epoch,
                    digest,
                    encoded,
                    item.attention_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AutonomyConflictError("owner-attention compare-and-swap failed")
        return item

    def append_attention_event(
        self,
        event: OwnerAttentionEventV1,
    ) -> OwnerAttentionEventV1:
        digest, encoded = self._encoded_payload(event)
        with self.work.extension_transaction() as db:
            existing = db.execute(
                """
                SELECT * FROM autonomy_attention_events
                WHERE attention_id=? AND event_key=?
                """,
                (event.attention_id, event.event_key),
            ).fetchone()
            if existing is not None:
                payload = self._decoded_payload(existing)
                if str(existing["payload_digest"]) != digest:
                    raise AutonomyConflictError(
                        "attention event key reused with different payload"
                    )
                return OwnerAttentionEventV1.from_payload(payload)
            try:
                db.execute(
                    """
                    INSERT INTO autonomy_attention_events(
                        event_id, attention_id, event_key, kind,
                        created_at_epoch, payload_digest, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.attention_id,
                        event.event_key,
                        event.kind,
                        event.created_at_epoch,
                        digest,
                        encoded,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutonomyConflictError(
                    "attention event identity conflict"
                ) from exc
        return event

    def list_attention_events(
        self,
        attention_id: str,
    ) -> tuple[OwnerAttentionEventV1, ...]:
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM autonomy_attention_events
                WHERE attention_id=? ORDER BY rowid
                """,
                (attention_id,),
            ).fetchall()
        return tuple(
            OwnerAttentionEventV1.from_payload(self._decoded_payload(row))
            for row in rows
        )

    def record_outcome(
        self,
        outcome: AutonomyOutcomeRecordV1,
    ) -> AutonomyOutcomeRecordV1:
        return self._immutable_create(
            table="autonomy_outcome_links",
            identity_column="outcome_record_id",
            identity=outcome.outcome_record_id,
            value=outcome,
            insert_sql="""
                INSERT INTO autonomy_outcome_links(
                    outcome_record_id, candidate_id, dispatch_link_id,
                    downstream_source_kind, downstream_source_id,
                    recorded_at_epoch, payload_digest, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=(
                outcome.outcome_record_id,
                outcome.candidate_id,
                outcome.dispatch_link_id,
                outcome.downstream_source_kind,
                outcome.downstream_source_id,
                outcome.recorded_at_epoch,
            ),
            decoder=AutonomyOutcomeRecordV1.from_payload,
        )

    def require_outcome(
        self,
        outcome_record_id: str,
    ) -> AutonomyOutcomeRecordV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_outcome_links
                WHERE outcome_record_id=?
                """,
                (outcome_record_id,),
            ).fetchone()
        if row is None:
            raise KeyError(outcome_record_id)
        return AutonomyOutcomeRecordV1.from_payload(self._decoded_payload(row))

    def create_reconcile_run(self, run: ReconcileRunV1) -> ReconcileRunV1:
        digest, encoded = self._encoded_payload(run)
        with self.work.extension_transaction() as db:
            existing = db.execute(
                """
                SELECT * FROM autonomy_reconcile_runs
                WHERE request_token=?
                """,
                (run.request_token,),
            ).fetchone()
            if existing is not None:
                payload = self._decoded_payload(existing)
                if str(existing["payload_digest"]) != digest:
                    raise AutonomyConflictError(
                        "reconcile request token reused with different payload"
                    )
                return ReconcileRunV1.from_payload(payload)
            try:
                db.execute(
                    """
                    INSERT INTO autonomy_reconcile_runs(
                        reconcile_run_id, request_token, trigger, status,
                        desired_generation_digest, snapshot_digest,
                        handled_token, started_at_epoch, ended_at_epoch,
                        payload_digest, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.reconcile_run_id,
                        run.request_token,
                        run.trigger.value,
                        run.status.value,
                        run.desired_generation_digest,
                        run.snapshot_digest,
                        run.handled_token,
                        run.started_at_epoch,
                        run.ended_at_epoch,
                        digest,
                        encoded,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutonomyConflictError("reconcile-run identity conflict") from exc
        return run

    def require_reconcile_run_by_token(
        self,
        request_token: str,
    ) -> ReconcileRunV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_reconcile_runs
                WHERE request_token=?
                """,
                (request_token,),
            ).fetchone()
        if row is None:
            raise KeyError(request_token)
        return ReconcileRunV1.from_payload(self._decoded_payload(row))

    def record_system_snapshot(
        self,
        snapshot: SystemStateSnapshotV1,
    ) -> SystemStateSnapshotV1:
        if not isinstance(snapshot, SystemStateSnapshotV1):
            raise TypeError("snapshot must be a SystemStateSnapshotV1")
        encoded = self.work.encode_extension_json(snapshot.to_payload())
        with self.work.extension_transaction() as db:
            existing = db.execute(
                """
                SELECT * FROM autonomy_system_snapshots
                WHERE snapshot_id=?
                """,
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing is not None:
                payload = self.work.decode_extension_json(str(existing["payload"]))
                if not isinstance(payload, dict):
                    raise AutonomyIntegrityError(
                        "stored SystemState snapshot payload is not an object"
                    )
                persisted = SystemStateSnapshotV1.from_payload(payload)
                if persisted != snapshot:
                    raise AutonomyConflictError(
                        "SystemState snapshot identity already exists with different payload"
                    )
                if str(existing["snapshot_digest"]) != snapshot.snapshot_digest:
                    raise AutonomyIntegrityError(
                        "stored SystemState snapshot digest column mismatch"
                    )
                return persisted
            try:
                db.execute(
                    """
                    INSERT INTO autonomy_system_snapshots(
                        snapshot_id, snapshot_digest, payload, created_at_epoch
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.snapshot_digest,
                        encoded,
                        snapshot.ended_at_epoch,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutonomyConflictError(
                    "SystemState snapshot identity conflict"
                ) from exc
        return snapshot

    def require_system_snapshot(
        self,
        snapshot_id: str,
    ) -> SystemStateSnapshotV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_system_snapshots
                WHERE snapshot_id=?
                """,
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        payload = self.work.decode_extension_json(str(row["payload"]))
        if not isinstance(payload, dict):
            raise AutonomyIntegrityError(
                "stored SystemState snapshot payload is not an object"
            )
        snapshot = SystemStateSnapshotV1.from_payload(payload)
        if str(row["snapshot_digest"]) != snapshot.snapshot_digest:
            raise AutonomyIntegrityError(
                "stored SystemState snapshot digest column mismatch"
            )
        return snapshot
