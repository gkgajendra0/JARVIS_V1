"""Separate SQLite persistence for operational engineering incidents."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from jarvis.incidents.models import (
    EvidenceReference,
    IncidentRecord,
    IncidentSeverity,
    IncidentStatus,
)
from jarvis.self_repair.domain import (
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairRiskClass,
    RepairVerdict,
)


class SqliteIncidentStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = RLock()
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS engineering_incident (
                    incident_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    updated_at_epoch REAL NOT NULL,
                    affected_components_json TEXT NOT NULL,
                    root_cause TEXT,
                    accepted_fix TEXT,
                    regression_tests_json TEXT NOT NULL,
                    commit_sha TEXT,
                    pr_number INTEGER,
                    deployment_result TEXT,
                    rollback_status TEXT,
                    lessons_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS engineering_incident_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    occurred_at_epoch REAL NOT NULL,
                    component_id TEXT,
                    FOREIGN KEY(incident_id)
                    REFERENCES engineering_incident(incident_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_incident_status_updated
                ON engineering_incident(status, updated_at_epoch)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS engineering_repair_attempt (
                    attempt_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    trigger_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    action_id TEXT NOT NULL,
                    action_kind TEXT NOT NULL,
                    risk_class INTEGER NOT NULL,
                    component_id TEXT NOT NULL,
                    action_created_at_epoch REAL NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    started_at_epoch REAL NOT NULL,
                    pre_repair_evidence_json TEXT NOT NULL,
                    finished_at_epoch REAL,
                    execution_result TEXT,
                    post_repair_evidence_json TEXT NOT NULL,
                    verifier_result TEXT,
                    next_retry_eligible_epoch REAL,
                    verdict TEXT,
                    FOREIGN KEY(incident_id)
                    REFERENCES engineering_incident(incident_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_repair_attempt_incident
                ON engineering_repair_attempt(
                    incident_id, attempt_number, started_at_epoch
                )
                """
            )

    def upsert(self, incident: IncidentRecord) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO engineering_incident (
                    incident_id, title, symptom, severity, status,
                    created_at_epoch, updated_at_epoch, affected_components_json,
                    root_cause, accepted_fix, regression_tests_json, commit_sha,
                    pr_number, deployment_result, rollback_status, lessons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    title=excluded.title,
                    symptom=excluded.symptom,
                    severity=excluded.severity,
                    status=excluded.status,
                    updated_at_epoch=excluded.updated_at_epoch,
                    affected_components_json=excluded.affected_components_json,
                    root_cause=excluded.root_cause,
                    accepted_fix=excluded.accepted_fix,
                    regression_tests_json=excluded.regression_tests_json,
                    commit_sha=excluded.commit_sha,
                    pr_number=excluded.pr_number,
                    deployment_result=excluded.deployment_result,
                    rollback_status=excluded.rollback_status,
                    lessons_json=excluded.lessons_json
                """,
                (
                    incident.incident_id,
                    incident.title,
                    incident.symptom,
                    incident.severity.value,
                    incident.status.value,
                    incident.created_at_epoch,
                    incident.updated_at_epoch,
                    json.dumps(incident.affected_components),
                    incident.root_cause,
                    incident.accepted_fix,
                    json.dumps(incident.regression_tests),
                    incident.commit_sha,
                    incident.pr_number,
                    incident.deployment_result,
                    incident.rollback_status,
                    json.dumps(incident.lessons),
                ),
            )
            self._connection.execute(
                "DELETE FROM engineering_incident_evidence WHERE incident_id = ?",
                (incident.incident_id,),
            )
            self._connection.executemany(
                """
                INSERT INTO engineering_incident_evidence (
                    evidence_id, incident_id, kind, reference, summary,
                    occurred_at_epoch, component_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.evidence_id,
                        incident.incident_id,
                        item.kind,
                        item.reference,
                        item.summary,
                        item.occurred_at_epoch,
                        item.component_id,
                    )
                    for item in incident.evidence
                ],
            )

    def get(self, incident_id: str) -> IncidentRecord | None:
        with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM engineering_incident WHERE incident_id = ?",
                (incident_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description or ()]
            payload = dict(zip(columns, row, strict=True))
            evidence_rows = self._connection.execute(
                """
                SELECT evidence_id, kind, reference, summary,
                       occurred_at_epoch, component_id
                FROM engineering_incident_evidence
                WHERE incident_id = ?
                ORDER BY occurred_at_epoch, evidence_id
                """,
                (incident_id,),
            ).fetchall()
        evidence = tuple(EvidenceReference(*item) for item in evidence_rows)
        return IncidentRecord(
            incident_id=payload["incident_id"],
            title=payload["title"],
            symptom=payload["symptom"],
            severity=IncidentSeverity(payload["severity"]),
            status=IncidentStatus(payload["status"]),
            created_at_epoch=payload["created_at_epoch"],
            updated_at_epoch=payload["updated_at_epoch"],
            affected_components=tuple(json.loads(payload["affected_components_json"])),
            evidence=evidence,
            root_cause=payload["root_cause"],
            accepted_fix=payload["accepted_fix"],
            regression_tests=tuple(json.loads(payload["regression_tests_json"])),
            commit_sha=payload["commit_sha"],
            pr_number=payload["pr_number"],
            deployment_result=payload["deployment_result"],
            rollback_status=payload["rollback_status"],
            lessons=tuple(json.loads(payload["lessons_json"])),
        )

    def list_recent(
        self,
        *,
        limit: int = 50,
        status: IncidentStatus | None = None,
    ) -> tuple[IncidentRecord, ...]:
        if limit <= 0:
            return ()
        query = "SELECT incident_id FROM engineering_incident"
        parameters: tuple[object, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            parameters = (status.value,)
        query += " ORDER BY updated_at_epoch DESC LIMIT ?"
        parameters = (*parameters, limit)
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return tuple(
            incident
            for (incident_id,) in rows
            if (incident := self.get(incident_id)) is not None
        )

    def upsert_repair_attempt(self, attempt: RepairAttempt) -> None:
        with self._lock, self._connection:
            existing = self._get_repair_attempt_unlocked(attempt.attempt_id)
            if existing is not None:
                existing_identity = (
                    existing.incident_id,
                    existing.trigger_id,
                    existing.policy_id,
                    existing.policy_version,
                    existing.action,
                    existing.attempt_number,
                    existing.started_at_epoch,
                    existing.pre_repair_evidence,
                )
                incoming_identity = (
                    attempt.incident_id,
                    attempt.trigger_id,
                    attempt.policy_id,
                    attempt.policy_version,
                    attempt.action,
                    attempt.attempt_number,
                    attempt.started_at_epoch,
                    attempt.pre_repair_evidence,
                )
                if existing_identity != incoming_identity:
                    raise ValueError(
                        "repair attempt identity cannot change after persistence"
                    )
                if existing.finished_at_epoch is not None:
                    if existing != attempt:
                        raise ValueError(
                            "completed repair attempt cannot be overwritten"
                        )
                    return

            self._connection.execute(
                """
                INSERT INTO engineering_repair_attempt (
                    attempt_id, incident_id, trigger_id, policy_id, policy_version,
                    action_id, action_kind, risk_class, component_id,
                    action_created_at_epoch, attempt_number, started_at_epoch,
                    pre_repair_evidence_json, finished_at_epoch, execution_result,
                    post_repair_evidence_json, verifier_result,
                    next_retry_eligible_epoch, verdict
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    trigger_id=excluded.trigger_id,
                    policy_id=excluded.policy_id,
                    policy_version=excluded.policy_version,
                    action_id=excluded.action_id,
                    action_kind=excluded.action_kind,
                    risk_class=excluded.risk_class,
                    component_id=excluded.component_id,
                    action_created_at_epoch=excluded.action_created_at_epoch,
                    attempt_number=excluded.attempt_number,
                    started_at_epoch=excluded.started_at_epoch,
                    pre_repair_evidence_json=excluded.pre_repair_evidence_json,
                    finished_at_epoch=excluded.finished_at_epoch,
                    execution_result=excluded.execution_result,
                    post_repair_evidence_json=excluded.post_repair_evidence_json,
                    verifier_result=excluded.verifier_result,
                    next_retry_eligible_epoch=excluded.next_retry_eligible_epoch,
                    verdict=excluded.verdict
                """,
                (
                    attempt.attempt_id,
                    attempt.incident_id,
                    attempt.trigger_id,
                    attempt.policy_id,
                    attempt.policy_version,
                    attempt.action.action_id,
                    attempt.action.kind.value,
                    int(attempt.action.risk_class),
                    attempt.action.component_id,
                    attempt.action.created_at_epoch,
                    attempt.attempt_number,
                    attempt.started_at_epoch,
                    json.dumps(attempt.pre_repair_evidence),
                    attempt.finished_at_epoch,
                    attempt.execution_result,
                    json.dumps(attempt.post_repair_evidence),
                    attempt.verifier_result,
                    attempt.next_retry_eligible_epoch,
                    attempt.verdict.value if attempt.verdict is not None else None,
                ),
            )

    def get_repair_attempt(self, attempt_id: str) -> RepairAttempt | None:
        with self._lock:
            return self._get_repair_attempt_unlocked(attempt_id)

    def _get_repair_attempt_unlocked(self, attempt_id: str) -> RepairAttempt | None:
        cursor = self._connection.execute(
            "SELECT * FROM engineering_repair_attempt WHERE attempt_id = ?",
            (attempt_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in cursor.description or ()]
        return self._repair_attempt_from_payload(dict(zip(columns, row, strict=True)))

    def list_repair_attempts(
        self,
        incident_id: str,
        *,
        limit: int = 100,
    ) -> tuple[RepairAttempt, ...]:
        if limit <= 0:
            return ()
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM engineering_repair_attempt
                WHERE incident_id = ?
                ORDER BY attempt_number, started_at_epoch, attempt_id
                LIMIT ?
                """,
                (incident_id, limit),
            )
            columns = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchall()
        return tuple(
            self._repair_attempt_from_payload(dict(zip(columns, row, strict=True)))
            for row in rows
        )

    @staticmethod
    def _repair_attempt_from_payload(payload: dict[str, object]) -> RepairAttempt:
        action = RepairAction(
            action_id=str(payload["action_id"]),
            policy_id=str(payload["policy_id"]),
            policy_version=int(payload["policy_version"]),
            trigger_id=str(payload["trigger_id"]),
            component_id=str(payload["component_id"]),
            kind=RepairActionKind(str(payload["action_kind"])),
            risk_class=RepairRiskClass(int(payload["risk_class"])),
            created_at_epoch=float(payload["action_created_at_epoch"]),
        )
        verdict_value = payload["verdict"]
        return RepairAttempt(
            attempt_id=str(payload["attempt_id"]),
            incident_id=str(payload["incident_id"]),
            trigger_id=str(payload["trigger_id"]),
            policy_id=str(payload["policy_id"]),
            policy_version=int(payload["policy_version"]),
            action=action,
            attempt_number=int(payload["attempt_number"]),
            started_at_epoch=float(payload["started_at_epoch"]),
            pre_repair_evidence=tuple(
                json.loads(str(payload["pre_repair_evidence_json"]))
            ),
            finished_at_epoch=(
                float(payload["finished_at_epoch"])
                if payload["finished_at_epoch"] is not None
                else None
            ),
            execution_result=(
                str(payload["execution_result"])
                if payload["execution_result"] is not None
                else None
            ),
            post_repair_evidence=tuple(
                json.loads(str(payload["post_repair_evidence_json"]))
            ),
            verifier_result=(
                str(payload["verifier_result"])
                if payload["verifier_result"] is not None
                else None
            ),
            next_retry_eligible_epoch=(
                float(payload["next_retry_eligible_epoch"])
                if payload["next_retry_eligible_epoch"] is not None
                else None
            ),
            verdict=(
                RepairVerdict(str(verdict_value)) if verdict_value is not None else None
            ),
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
