"""Shared SQLite persistence for engineering incidents and knowledge facets."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRevision,
    KnowledgeEvidenceLink,
    KnowledgeFreshnessState,
    KnowledgeLifecycleEvent,
    KnowledgeLifecycleState,
    KnowledgeSensitivity,
)
from jarvis.engineering_knowledge.persistence import (
    EngineeringKnowledgeCandidateBundle,
    EngineeringKnowledgeCandidateWriteResult,
    EngineeringKnowledgePersistenceConflictError,
)
from jarvis.engineering_knowledge.security import EngineeringEvidenceAdmissionGate
from jarvis.incidents.migration_runner import EngineeringMigrationRunner
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
    RepairPolicySnapshot,
    RepairRiskClass,
    RepairTriggerSnapshot,
    RepairVerdict,
    RepairVerificationResult,
)


class SqliteIncidentStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = RLock()
        self._connection.execute("PRAGMA journal_mode=WAL")
        EngineeringMigrationRunner().apply(self._connection)

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
                    existing.trigger_snapshot,
                    existing.policy_snapshot,
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
                    attempt.trigger_snapshot,
                    attempt.policy_snapshot,
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

            trigger_snapshot_json = (
                json.dumps(
                    attempt.trigger_snapshot.to_payload(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if attempt.trigger_snapshot is not None
                else None
            )
            policy_snapshot_json = (
                json.dumps(
                    attempt.policy_snapshot.to_payload(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if attempt.policy_snapshot is not None
                else None
            )
            policy_digest = (
                attempt.policy_snapshot.digest
                if attempt.policy_snapshot is not None
                else None
            )
            verification_json = (
                json.dumps(
                    attempt.verification.to_payload(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if attempt.verification is not None
                else None
            )

            self._connection.execute(
                """
                INSERT INTO engineering_repair_attempt (
                    attempt_id, incident_id, trigger_id, policy_id, policy_version,
                    action_id, action_kind, risk_class, component_id,
                    action_created_at_epoch, attempt_number, started_at_epoch,
                    pre_repair_evidence_json, trigger_snapshot_json,
                    policy_snapshot_json, policy_digest,
                    finished_at_epoch, execution_result,
                    post_repair_evidence_json, verifier_result, verification_json,
                    next_retry_eligible_epoch, verdict
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
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
                    trigger_snapshot_json=excluded.trigger_snapshot_json,
                    policy_snapshot_json=excluded.policy_snapshot_json,
                    policy_digest=excluded.policy_digest,
                    finished_at_epoch=excluded.finished_at_epoch,
                    execution_result=excluded.execution_result,
                    post_repair_evidence_json=excluded.post_repair_evidence_json,
                    verifier_result=excluded.verifier_result,
                    verification_json=excluded.verification_json,
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
                    trigger_snapshot_json,
                    policy_snapshot_json,
                    policy_digest,
                    attempt.finished_at_epoch,
                    attempt.execution_result,
                    json.dumps(attempt.post_repair_evidence),
                    attempt.verifier_result,
                    verification_json,
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
                ORDER BY attempt_number DESC, started_at_epoch DESC, attempt_id DESC
                LIMIT ?
                """,
                (incident_id, limit),
            )
            columns = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchall()
        attempts = tuple(
            self._repair_attempt_from_payload(dict(zip(columns, row, strict=True)))
            for row in rows
        )
        return tuple(reversed(attempts))

    def list_repair_attempts_for_component(
        self,
        component_id: str,
        *,
        action_kind: RepairActionKind | None = None,
        limit: int = 500,
    ) -> tuple[RepairAttempt, ...]:
        """Return bounded repair history across incidents for one repair target."""

        normalized_component = str(component_id).strip().lower()
        if not normalized_component or limit <= 0:
            return ()
        if action_kind is not None and not isinstance(action_kind, RepairActionKind):
            raise TypeError("action_kind must be a RepairActionKind or None")

        query = """
            SELECT * FROM engineering_repair_attempt
            WHERE component_id = ?
        """
        parameters: list[object] = [normalized_component]
        if action_kind is not None:
            query += " AND action_kind = ?"
            parameters.append(action_kind.value)
        query += """
            ORDER BY started_at_epoch DESC, attempt_id DESC
            LIMIT ?
        """
        parameters.append(limit)

        with self._lock:
            cursor = self._connection.execute(query, tuple(parameters))
            columns = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchall()

        attempts = tuple(
            self._repair_attempt_from_payload(dict(zip(columns, row, strict=True)))
            for row in rows
        )
        return tuple(reversed(attempts))

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

        trigger_snapshot = None
        trigger_snapshot_value = payload.get("trigger_snapshot_json")
        if trigger_snapshot_value is not None:
            trigger_snapshot = RepairTriggerSnapshot.from_payload(
                json.loads(str(trigger_snapshot_value))
            )

        policy_snapshot = None
        policy_snapshot_value = payload.get("policy_snapshot_json")
        if policy_snapshot_value is not None:
            policy_snapshot = RepairPolicySnapshot.from_payload(
                json.loads(str(policy_snapshot_value))
            )
            persisted_digest = payload.get("policy_digest")
            if (
                persisted_digest is not None
                and str(persisted_digest) != policy_snapshot.digest
            ):
                raise ValueError(
                    "persisted repair policy digest does not match snapshot"
                )

        verification = None
        verification_value = payload.get("verification_json")
        if verification_value is not None:
            verification = RepairVerificationResult.from_payload(
                json.loads(str(verification_value))
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
            trigger_snapshot=trigger_snapshot,
            policy_snapshot=policy_snapshot,
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
            verification=verification,
            next_retry_eligible_epoch=(
                float(payload["next_retry_eligible_epoch"])
                if payload["next_retry_eligible_epoch"] is not None
                else None
            ),
            verdict=(
                RepairVerdict(str(verdict_value)) if verdict_value is not None else None
            ),
        )

    def persist_engineering_knowledge_candidate(
        self,
        candidate: EngineeringKnowledgeCandidateBundle,
    ) -> EngineeringKnowledgeCandidateWriteResult:
        """Atomically persist one deterministic immutable candidate or verify replay."""

        if not isinstance(candidate, EngineeringKnowledgeCandidateBundle):
            raise TypeError("candidate must be an EngineeringKnowledgeCandidateBundle")

        identity = candidate.identity
        revision = candidate.revision
        inserted_after_existing_revision = False

        admission_gate = EngineeringEvidenceAdmissionGate()
        for evidence in candidate.evidence:
            admission_gate.require_admissible_evidence(evidence)

        with self._lock, self._connection:
            self._insert_immutable_row(
                table="engineering_knowledge_identity",
                columns=(
                    "knowledge_id",
                    "stable_label",
                    "created_at_epoch",
                    "created_by",
                ),
                values=(
                    identity.knowledge_id,
                    identity.stable_label,
                    identity.created_at_epoch,
                    identity.created_by,
                ),
                identity_columns=("knowledge_id",),
                identity_values=(identity.knowledge_id,),
            )
            revision_created = self._insert_immutable_row(
                table="engineering_knowledge_revision",
                columns=(
                    "revision_id",
                    "knowledge_id",
                    "revision_number",
                    "parent_revision_id",
                    "supersedes_revision_id",
                    "kind_namespace",
                    "normalized_summary",
                    "valid_from_epoch",
                    "valid_to_epoch",
                    "system_from_epoch",
                    "system_to_epoch",
                    "sensitivity",
                    "freshness_state",
                    "canonicalization",
                    "digest_algorithm",
                    "canonical_digest",
                    "created_at_epoch",
                    "created_by",
                ),
                values=(
                    revision.revision_id,
                    revision.knowledge_id,
                    revision.revision_number,
                    revision.parent_revision_id,
                    revision.supersedes_revision_id,
                    revision.kind_namespace,
                    revision.normalized_summary,
                    revision.valid_from_epoch,
                    revision.valid_to_epoch,
                    revision.system_from_epoch,
                    revision.system_to_epoch,
                    revision.sensitivity.value,
                    revision.freshness_state.value,
                    revision.canonicalization,
                    revision.digest_algorithm,
                    revision.canonical_digest,
                    revision.created_at_epoch,
                    revision.created_by,
                ),
                identity_columns=("revision_id",),
                identity_values=(revision.revision_id,),
            )

            for facet in candidate.facets:
                inserted = self._insert_immutable_row(
                    table="engineering_knowledge_facet",
                    columns=(
                        "facet_id",
                        "revision_id",
                        "facet_type",
                        "schema_id",
                        "schema_version",
                        "schema_digest",
                        "producer",
                        "payload_json",
                        "protected_payload_ref",
                        "payload_digest",
                        "created_at_epoch",
                    ),
                    values=(
                        facet.facet_id,
                        facet.revision_id,
                        facet.facet_type,
                        facet.schema_id,
                        facet.schema_version,
                        facet.schema_digest,
                        facet.producer,
                        facet.payload_json,
                        facet.protected_payload_ref,
                        facet.payload_digest,
                        facet.created_at_epoch,
                    ),
                    identity_columns=("facet_id",),
                    identity_values=(facet.facet_id,),
                )
                inserted_after_existing_revision |= inserted and not revision_created

            for item in candidate.applicability:
                inserted = self._insert_immutable_row(
                    table="engineering_knowledge_applicability",
                    columns=(
                        "applicability_id",
                        "revision_id",
                        "target_namespace",
                        "target_identity",
                        "matcher_type",
                        "constraint_json",
                        "required",
                        "created_at_epoch",
                    ),
                    values=(
                        item.applicability_id,
                        item.revision_id,
                        item.target_namespace,
                        item.target_identity,
                        item.matcher_type,
                        item.constraint_json,
                        int(item.required),
                        item.created_at_epoch,
                    ),
                    identity_columns=("applicability_id",),
                    identity_values=(item.applicability_id,),
                )
                inserted_after_existing_revision |= inserted and not revision_created

            for evidence in candidate.evidence:
                inserted = self._insert_immutable_row(
                    table="engineering_evidence",
                    columns=(
                        "evidence_id",
                        "evidence_type",
                        "source_class",
                        "canonical_reference",
                        "summary",
                        "occurred_at_epoch",
                        "observed_at_epoch",
                        "sensitivity",
                        "producer",
                        "integrity_algorithm",
                        "integrity_digest",
                        "created_at_epoch",
                    ),
                    values=(
                        evidence.evidence_id,
                        evidence.evidence_type,
                        evidence.source_class,
                        evidence.canonical_reference,
                        evidence.summary,
                        evidence.occurred_at_epoch,
                        evidence.observed_at_epoch,
                        evidence.sensitivity.value,
                        evidence.producer,
                        evidence.integrity_algorithm,
                        evidence.integrity_digest,
                        evidence.created_at_epoch,
                    ),
                    identity_columns=("evidence_id",),
                    identity_values=(evidence.evidence_id,),
                )
                inserted_after_existing_revision |= inserted and not revision_created

            for link in candidate.evidence_links:
                inserted = self._insert_immutable_row(
                    table="engineering_knowledge_evidence_link",
                    columns=(
                        "revision_id",
                        "evidence_id",
                        "relation_type",
                        "created_at_epoch",
                    ),
                    values=(
                        link.revision_id,
                        link.evidence_id,
                        link.relation_type,
                        link.created_at_epoch,
                    ),
                    identity_columns=("revision_id", "evidence_id", "relation_type"),
                    identity_values=(
                        link.revision_id,
                        link.evidence_id,
                        link.relation_type,
                    ),
                )
                inserted_after_existing_revision |= inserted and not revision_created

            event = candidate.lifecycle_event
            inserted = self._insert_immutable_row(
                table="engineering_knowledge_lifecycle_event",
                columns=(
                    "event_id",
                    "revision_id",
                    "from_state",
                    "to_state",
                    "reason_code",
                    "actor",
                    "policy_id",
                    "evidence_ids_json",
                    "occurred_at_epoch",
                ),
                values=(
                    event.event_id,
                    event.revision_id,
                    event.from_state.value if event.from_state is not None else None,
                    event.to_state.value,
                    event.reason_code,
                    event.actor,
                    event.policy_id,
                    json.dumps(
                        event.evidence_ids,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    event.occurred_at_epoch,
                ),
                identity_columns=("event_id",),
                identity_values=(event.event_id,),
            )
            inserted_after_existing_revision |= inserted and not revision_created

            for attestation in candidate.attestations:
                inserted = self._insert_immutable_row(
                    table="engineering_attestation",
                    columns=(
                        "attestation_id",
                        "subject_type",
                        "subject_id",
                        "subject_digest",
                        "predicate_type",
                        "producer",
                        "expected_contract_json",
                        "observed_result_json",
                        "verdict",
                        "evidence_ids_json",
                        "observed_at_epoch",
                        "created_at_epoch",
                    ),
                    values=(
                        attestation.attestation_id,
                        attestation.subject_type,
                        attestation.subject_id,
                        attestation.subject_digest,
                        attestation.predicate_type,
                        attestation.producer,
                        attestation.expected_contract_json,
                        attestation.observed_result_json,
                        attestation.verdict.value,
                        json.dumps(
                            attestation.evidence_ids,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        attestation.observed_at_epoch,
                        attestation.created_at_epoch,
                    ),
                    identity_columns=("attestation_id",),
                    identity_values=(attestation.attestation_id,),
                )
                inserted_after_existing_revision |= inserted and not revision_created

            if inserted_after_existing_revision:
                raise EngineeringKnowledgePersistenceConflictError(
                    "existing candidate revision was incomplete; replay refused"
                )

        return EngineeringKnowledgeCandidateWriteResult(
            knowledge_id=identity.knowledge_id,
            revision_id=revision.revision_id,
            created=revision_created,
        )

    def _insert_immutable_row(
        self,
        *,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        identity_columns: tuple[str, ...],
        identity_values: tuple[object, ...],
    ) -> bool:
        where_clause = " AND ".join(f"{column} = ?" for column in identity_columns)
        existing = self._connection.execute(
            f"""
            SELECT {", ".join(columns)}
            FROM {table}
            WHERE {where_clause}
            """,
            identity_values,
        ).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise EngineeringKnowledgePersistenceConflictError(
                    f"{table} immutable identity exists with different content"
                )
            return False

        placeholders = ", ".join("?" for _ in columns)
        try:
            self._connection.execute(
                f"""
                INSERT INTO {table} ({", ".join(columns)})
                VALUES ({placeholders})
                """,
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise EngineeringKnowledgePersistenceConflictError(
                f"{table} immutable unique-key or freeze conflict"
            ) from exc
        return True

    def get_engineering_knowledge_revision(
        self,
        revision_id: str,
    ) -> EngineeringKnowledgeRevision | None:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_revision
                WHERE revision_id = ?
                """,
                (str(revision_id).strip(),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description or ()]
        payload = dict(zip(columns, row, strict=True))
        return EngineeringKnowledgeRevision(
            revision_id=str(payload["revision_id"]),
            knowledge_id=str(payload["knowledge_id"]),
            revision_number=int(payload["revision_number"]),
            parent_revision_id=(
                str(payload["parent_revision_id"])
                if payload["parent_revision_id"] is not None
                else None
            ),
            supersedes_revision_id=(
                str(payload["supersedes_revision_id"])
                if payload["supersedes_revision_id"] is not None
                else None
            ),
            kind_namespace=str(payload["kind_namespace"]),
            normalized_summary=str(payload["normalized_summary"]),
            valid_from_epoch=(
                float(payload["valid_from_epoch"])
                if payload["valid_from_epoch"] is not None
                else None
            ),
            valid_to_epoch=(
                float(payload["valid_to_epoch"])
                if payload["valid_to_epoch"] is not None
                else None
            ),
            system_from_epoch=float(payload["system_from_epoch"]),
            system_to_epoch=(
                float(payload["system_to_epoch"])
                if payload["system_to_epoch"] is not None
                else None
            ),
            sensitivity=KnowledgeSensitivity(str(payload["sensitivity"])),
            freshness_state=KnowledgeFreshnessState(str(payload["freshness_state"])),
            canonicalization=str(payload["canonicalization"]),
            digest_algorithm=str(payload["digest_algorithm"]),
            canonical_digest=str(payload["canonical_digest"]),
            created_at_epoch=float(payload["created_at_epoch"]),
            created_by=str(payload["created_by"]),
        )

    def get_engineering_knowledge_lifecycle_state(
        self,
        revision_id: str,
    ) -> KnowledgeLifecycleState | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT lifecycle_state
                FROM engineering_knowledge_revision_state
                WHERE revision_id = ?
                """,
                (str(revision_id).strip(),),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeLifecycleState(str(row[0]))

    def list_engineering_knowledge_evidence_links(
        self,
        revision_id: str,
    ) -> tuple[KnowledgeEvidenceLink, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT revision_id, evidence_id, relation_type, created_at_epoch
                FROM engineering_knowledge_evidence_link
                WHERE revision_id = ?
                ORDER BY relation_type, evidence_id
                """,
                (str(revision_id).strip(),),
            ).fetchall()
        return tuple(
            KnowledgeEvidenceLink(
                revision_id=str(row[0]),
                evidence_id=str(row[1]),
                relation_type=str(row[2]),
                created_at_epoch=float(row[3]),
            )
            for row in rows
        )

    def list_engineering_knowledge_evidence(
        self,
        revision_id: str,
    ) -> tuple[EngineeringEvidence, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT DISTINCT evidence.evidence_id, evidence.evidence_type,
                       evidence.source_class, evidence.canonical_reference,
                       evidence.summary, evidence.occurred_at_epoch,
                       evidence.observed_at_epoch, evidence.sensitivity,
                       evidence.producer, evidence.integrity_algorithm,
                       evidence.integrity_digest, evidence.created_at_epoch
                FROM engineering_knowledge_evidence_link AS link
                JOIN engineering_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE link.revision_id = ?
                ORDER BY evidence.canonical_reference, evidence.evidence_id
                """,
                (str(revision_id).strip(),),
            ).fetchall()
        return tuple(
            EngineeringEvidence(
                evidence_id=str(row[0]),
                evidence_type=str(row[1]),
                source_class=str(row[2]),
                canonical_reference=str(row[3]),
                summary=str(row[4]),
                occurred_at_epoch=(
                    float(row[5]) if row[5] is not None else None
                ),
                observed_at_epoch=float(row[6]),
                sensitivity=KnowledgeSensitivity(str(row[7])),
                producer=str(row[8]),
                integrity_algorithm=(
                    str(row[9]) if row[9] is not None else None
                ),
                integrity_digest=(
                    str(row[10]) if row[10] is not None else None
                ),
                created_at_epoch=float(row[11]),
            )
            for row in rows
        )

    def list_engineering_knowledge_applicability(
        self,
        revision_id: str,
    ) -> tuple[EngineeringApplicability, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT applicability_id, revision_id, target_namespace,
                       target_identity, matcher_type, constraint_json,
                       required, created_at_epoch
                FROM engineering_knowledge_applicability
                WHERE revision_id = ?
                ORDER BY target_namespace, target_identity, matcher_type,
                         applicability_id
                """,
                (str(revision_id).strip(),),
            ).fetchall()
        return tuple(
            EngineeringApplicability(
                applicability_id=str(row[0]),
                revision_id=str(row[1]),
                target_namespace=str(row[2]),
                target_identity=str(row[3]),
                matcher_type=str(row[4]),
                constraint_json=str(row[5]),
                required=bool(row[6]),
                created_at_epoch=float(row[7]),
            )
            for row in rows
        )

    def list_engineering_attestations(
        self,
        *,
        subject_type: str,
        subject_id: str,
    ) -> tuple[EngineeringAttestation, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT attestation_id, subject_type, subject_id, subject_digest,
                       predicate_type, producer, expected_contract_json,
                       observed_result_json, verdict, evidence_ids_json,
                       observed_at_epoch, created_at_epoch
                FROM engineering_attestation
                WHERE subject_type = ? AND subject_id = ?
                ORDER BY predicate_type, observed_at_epoch, attestation_id
                """,
                (str(subject_type).strip().lower(), str(subject_id).strip()),
            ).fetchall()
        return tuple(
            EngineeringAttestation(
                attestation_id=str(row[0]),
                subject_type=str(row[1]),
                subject_id=str(row[2]),
                subject_digest=str(row[3]),
                predicate_type=str(row[4]),
                producer=str(row[5]),
                expected_contract_json=str(row[6]),
                observed_result_json=str(row[7]),
                verdict=AttestationVerdict(str(row[8])),
                evidence_ids=tuple(json.loads(str(row[9]))),
                observed_at_epoch=float(row[10]),
                created_at_epoch=float(row[11]),
            )
            for row in rows
        )

    def append_engineering_knowledge_lifecycle_event(
        self,
        event: KnowledgeLifecycleEvent,
        *,
        expected_from_state: KnowledgeLifecycleState,
    ) -> bool:
        """Append one lifecycle event under a same-transaction state precondition."""

        if not isinstance(event, KnowledgeLifecycleEvent):
            raise TypeError("event must be a KnowledgeLifecycleEvent")
        if not isinstance(expected_from_state, KnowledgeLifecycleState):
            raise TypeError("expected_from_state must be a KnowledgeLifecycleState")
        if event.from_state is not expected_from_state:
            raise ValueError("event.from_state must equal expected_from_state")

        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT lifecycle_state
                FROM engineering_knowledge_revision_state
                WHERE revision_id = ?
                """,
                (event.revision_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown knowledge revision: {event.revision_id}")
            current = KnowledgeLifecycleState(str(row[0]))
            if current is event.to_state:
                existing = self._connection.execute(
                    """
                    SELECT revision_id, from_state, to_state, reason_code, actor,
                           policy_id, evidence_ids_json, occurred_at_epoch
                    FROM engineering_knowledge_lifecycle_event
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                ).fetchone()
                expected = (
                    event.revision_id,
                    event.from_state.value,
                    event.to_state.value,
                    event.reason_code,
                    event.actor,
                    event.policy_id,
                    json.dumps(
                        event.evidence_ids,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    event.occurred_at_epoch,
                )
                if existing == expected:
                    return False
                raise ValueError(
                    "lifecycle target already reached by a different transition"
                )
            if current is not expected_from_state:
                raise ValueError(
                    "knowledge lifecycle state changed before transition: "
                    f"expected {expected_from_state.value}, found {current.value}"
                )
            self._connection.execute(
                """
                INSERT INTO engineering_knowledge_lifecycle_event (
                    event_id, revision_id, from_state, to_state, reason_code,
                    actor, policy_id, evidence_ids_json, occurred_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.revision_id,
                    event.from_state.value,
                    event.to_state.value,
                    event.reason_code,
                    event.actor,
                    event.policy_id,
                    json.dumps(
                        event.evidence_ids,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    event.occurred_at_epoch,
                ),
            )
        return True

    def insert_engineering_knowledge_facet(
        self,
        facet: EngineeringKnowledgeFacet,
    ) -> None:
        """Persist one immutable facet without requiring registered semantics."""

        if not isinstance(facet, EngineeringKnowledgeFacet):
            raise TypeError("facet must be an EngineeringKnowledgeFacet")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO engineering_knowledge_facet (
                    facet_id, revision_id, facet_type, schema_id, schema_version,
                    schema_digest, producer, payload_json, protected_payload_ref,
                    payload_digest, created_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    facet.facet_id,
                    facet.revision_id,
                    facet.facet_type,
                    facet.schema_id,
                    facet.schema_version,
                    facet.schema_digest,
                    facet.producer,
                    facet.payload_json,
                    facet.protected_payload_ref,
                    facet.payload_digest,
                    facet.created_at_epoch,
                ),
            )

    def get_engineering_knowledge_facet(
        self,
        facet_id: str,
    ) -> EngineeringKnowledgeFacet | None:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_facet
                WHERE facet_id = ?
                """,
                (str(facet_id).strip(),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description or ()]
        return self._engineering_knowledge_facet_from_payload(
            dict(zip(columns, row, strict=True))
        )

    def list_engineering_knowledge_facets(
        self,
        revision_id: str,
    ) -> tuple[EngineeringKnowledgeFacet, ...]:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_facet
                WHERE revision_id = ?
                ORDER BY facet_type, schema_id, schema_version, facet_id
                """,
                (str(revision_id).strip(),),
            )
            columns = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchall()
        return tuple(
            self._engineering_knowledge_facet_from_payload(
                dict(zip(columns, row, strict=True))
            )
            for row in rows
        )

    @staticmethod
    def _engineering_knowledge_facet_from_payload(
        payload: dict[str, object],
    ) -> EngineeringKnowledgeFacet:
        return EngineeringKnowledgeFacet(
            facet_id=str(payload["facet_id"]),
            revision_id=str(payload["revision_id"]),
            facet_type=str(payload["facet_type"]),
            schema_id=str(payload["schema_id"]),
            schema_version=str(payload["schema_version"]),
            schema_digest=str(payload["schema_digest"]),
            producer=str(payload["producer"]),
            payload_json=(
                str(payload["payload_json"])
                if payload["payload_json"] is not None
                else None
            ),
            protected_payload_ref=(
                str(payload["protected_payload_ref"])
                if payload["protected_payload_ref"] is not None
                else None
            ),
            payload_digest=str(payload["payload_digest"]),
            created_at_epoch=float(payload["created_at_epoch"]),
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
