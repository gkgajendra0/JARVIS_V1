"""Durable Phase-4 routing provenance sharing the canonical WorkStore SQLite file."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.health import TargetHealthRecord
from jarvis.model_routing.models import (
    EligibilitySnapshot,
    LocalityRequirement,
    PrivacyClass,
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
    RoutingDecision,
    RoutingRequest,
    TargetExclusion,
)
from jarvis.work.store import SQLiteWorkStore


class RoutingStoreError(RuntimeError):
    pass


def _sha256(value: str, *, field: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def _snapshot_payload(snapshot: EligibilitySnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "routing_request_id": snapshot.routing_request_id,
        "considered_target_ids": list(snapshot.considered_target_ids),
        "eligible_target_ids": list(snapshot.eligible_target_ids),
        "exclusions": [
            {
                "target_id": exclusion.target_id,
                "reason_codes": list(exclusion.reason_codes),
            }
            for exclusion in snapshot.exclusions
        ],
        "target_health_versions": dict(snapshot.target_health_versions),
        "credential_availability": dict(snapshot.credential_availability),
        "required_capabilities": list(snapshot.required_capabilities),
        "privacy_class": snapshot.privacy_class.value,
        "locality_requirement": snapshot.locality_requirement.value,
        "policy_version": snapshot.policy_version,
        "policy_digest": snapshot.policy_digest,
    }


def _snapshot_from_payload(payload: dict[str, object]) -> EligibilitySnapshot:
    exclusions_raw = payload["exclusions"]
    if not isinstance(exclusions_raw, list):
        raise RoutingStoreError("stored eligibility exclusions are invalid")
    exclusions = tuple(
        TargetExclusion(
            target_id=str(item["target_id"]),
            reason_codes=tuple(str(value) for value in item["reason_codes"]),
        )
        for item in exclusions_raw
        if isinstance(item, dict)
    )
    return EligibilitySnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        routing_request_id=str(payload["routing_request_id"]),
        considered_target_ids=tuple(
            str(value) for value in payload["considered_target_ids"]
        ),
        eligible_target_ids=tuple(
            str(value) for value in payload["eligible_target_ids"]
        ),
        exclusions=exclusions,
        target_health_versions={
            str(key): int(value)
            for key, value in dict(payload["target_health_versions"]).items()
        },
        credential_availability={
            str(key): bool(value)
            for key, value in dict(payload["credential_availability"]).items()
        },
        required_capabilities=tuple(
            str(value) for value in payload["required_capabilities"]
        ),
        privacy_class=PrivacyClass(str(payload["privacy_class"])),
        locality_requirement=LocalityRequirement(
            str(payload["locality_requirement"])
        ),
        policy_version=int(payload["policy_version"]),
        policy_digest=str(payload["policy_digest"]),
    )


def _decision_payload(decision: RoutingDecision) -> dict[str, object]:
    return {
        "decision_id": decision.decision_id,
        "routing_request_id": decision.routing_request_id,
        "strategy_key": decision.strategy_key,
        "strategy_version": decision.strategy_version,
        "strategy_digest": decision.strategy_digest,
        "ordered_target_ids": list(decision.ordered_target_ids),
        "selected_target_id": decision.selected_target_id,
        "reason_codes": list(decision.reason_codes),
        "selected_role": decision.selected_role,
        "fallback_budget": decision.fallback_budget,
        "created_at_epoch": decision.created_at_epoch,
    }


def _decision_from_payload(payload: dict[str, object]) -> RoutingDecision:
    return RoutingDecision(
        decision_id=str(payload["decision_id"]),
        routing_request_id=str(payload["routing_request_id"]),
        strategy_key=str(payload["strategy_key"]),
        strategy_version=int(payload["strategy_version"]),
        strategy_digest=str(payload["strategy_digest"]),
        ordered_target_ids=tuple(
            str(value) for value in payload["ordered_target_ids"]
        ),
        selected_target_id=str(payload["selected_target_id"]),
        reason_codes=tuple(str(value) for value in payload["reason_codes"]),
        selected_role=str(payload["selected_role"]),
        fallback_budget=int(payload["fallback_budget"]),
        created_at_epoch=float(payload["created_at_epoch"]),
    )


def _attempt_payload(attempt: RoutingAttempt) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "decision_id": attempt.decision_id,
        "work_id": attempt.work_id,
        "target_id": attempt.target_id,
        "attempt_ordinal": attempt.attempt_ordinal,
        "started_at_epoch": attempt.started_at_epoch,
        "kind": attempt.kind.value,
        "ended_at_epoch": attempt.ended_at_epoch,
        "latency_ms": attempt.latency_ms,
        "failure_class": attempt.failure_class,
        "usage": dict(attempt.usage),
        "estimated_cost_usd": attempt.estimated_cost_usd,
        "response_contract_result": attempt.response_contract_result.value,
        "correlation_key": attempt.correlation_key,
    }


def _attempt_from_payload(payload: dict[str, object]) -> RoutingAttempt:
    return RoutingAttempt(
        attempt_id=str(payload["attempt_id"]),
        decision_id=str(payload["decision_id"]),
        work_id=str(payload["work_id"]),
        target_id=str(payload["target_id"]),
        attempt_ordinal=int(payload["attempt_ordinal"]),
        started_at_epoch=float(payload["started_at_epoch"]),
        kind=RoutingAttemptKind(str(payload["kind"])),
        ended_at_epoch=(
            None
            if payload["ended_at_epoch"] is None
            else float(payload["ended_at_epoch"])
        ),
        latency_ms=(
            None if payload["latency_ms"] is None else float(payload["latency_ms"])
        ),
        failure_class=(
            None
            if payload["failure_class"] is None
            else str(payload["failure_class"])
        ),
        usage={
            str(key): float(value)
            for key, value in dict(payload["usage"]).items()
        },
        estimated_cost_usd=(
            None
            if payload["estimated_cost_usd"] is None
            else float(payload["estimated_cost_usd"])
        ),
        response_contract_result=ResponseContractResult(
            str(payload["response_contract_result"])
        ),
        correlation_key=(
            None
            if payload["correlation_key"] is None
            else str(payload["correlation_key"])
        ),
    )


@dataclass(frozen=True, slots=True)
class PersistedRoutingDecision:
    work_id: str
    registry_digest: str
    eligibility: EligibilitySnapshot
    decision: RoutingDecision


class ModelRoutingStore:
    """Append-only routing lineage plus CAS target health in WorkStore SQLite."""

    def __init__(self, work_store: SQLiteWorkStore) -> None:
        if not isinstance(work_store, SQLiteWorkStore):
            raise TypeError("work_store must be a SQLiteWorkStore")
        self._work_store = work_store
        self._initialize()

    @property
    def path(self):
        return self._work_store.path

    def _initialize(self) -> None:
        with self._work_store.extension_transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_routing_decisions (
                    decision_id TEXT PRIMARY KEY,
                    routing_request_id TEXT NOT NULL UNIQUE,
                    work_id TEXT NOT NULL,
                    strategy_key TEXT NOT NULL,
                    strategy_version INTEGER NOT NULL,
                    strategy_digest TEXT NOT NULL,
                    registry_digest TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    policy_digest TEXT NOT NULL,
                    selected_target_id TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    eligibility_json TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE TABLE IF NOT EXISTS model_routing_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    attempt_ordinal INTEGER NOT NULL,
                    attempt_json TEXT NOT NULL,
                    started_at_epoch REAL NOT NULL,
                    FOREIGN KEY(decision_id)
                        REFERENCES model_routing_decisions(decision_id),
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id),
                    UNIQUE(decision_id, attempt_ordinal)
                );

                CREATE TABLE IF NOT EXISTS model_target_health (
                    target_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL,
                    cooldown_until_epoch REAL,
                    last_failure_kind TEXT,
                    updated_at_epoch REAL NOT NULL,
                    version INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_model_routing_decisions_work
                    ON model_routing_decisions(work_id, created_at_epoch);
                CREATE INDEX IF NOT EXISTS idx_model_routing_attempts_decision
                    ON model_routing_attempts(
                        decision_id, attempt_ordinal
                    );
                """
            )

    def _validate_decision_inputs(
        self,
        request: RoutingRequest,
        eligibility: EligibilitySnapshot,
        decision: RoutingDecision,
        registry_digest: str,
    ) -> str:
        if not isinstance(request, RoutingRequest):
            raise TypeError("request must be a RoutingRequest")
        if not isinstance(eligibility, EligibilitySnapshot):
            raise TypeError("eligibility must be an EligibilitySnapshot")
        if not isinstance(decision, RoutingDecision):
            raise TypeError("decision must be a RoutingDecision")
        if eligibility.routing_request_id != request.routing_request_id:
            raise ValueError("eligibility routing_request_id does not match request")
        if decision.routing_request_id != request.routing_request_id:
            raise ValueError("decision routing_request_id does not match request")
        if decision.selected_target_id not in eligibility.eligible_target_ids:
            raise ValueError("selected target is not eligible")
        if not set(decision.ordered_target_ids).issubset(
            eligibility.eligible_target_ids
        ):
            raise ValueError("decision contains an ineligible target")
        return _sha256(registry_digest, field="registry_digest")

    def _insert_decision(
        self,
        connection: sqlite3.Connection,
        *,
        request: RoutingRequest,
        eligibility: EligibilitySnapshot,
        decision: RoutingDecision,
        registry_digest: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO model_routing_decisions (
                decision_id, routing_request_id, work_id,
                strategy_key, strategy_version, strategy_digest,
                registry_digest, policy_version, policy_digest,
                selected_target_id, decision_json, eligibility_json,
                created_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                request.routing_request_id,
                request.work_id,
                decision.strategy_key,
                decision.strategy_version,
                decision.strategy_digest,
                registry_digest,
                eligibility.policy_version,
                eligibility.policy_digest,
                decision.selected_target_id,
                self._work_store.encode_extension_json(
                    _decision_payload(decision)
                ),
                self._work_store.encode_extension_json(
                    _snapshot_payload(eligibility)
                ),
                decision.created_at_epoch,
            ),
        )

    def record_decision(
        self,
        *,
        request: RoutingRequest,
        eligibility: EligibilitySnapshot,
        decision: RoutingDecision,
        registry_digest: str,
    ) -> PersistedRoutingDecision:
        digest = self._validate_decision_inputs(
            request,
            eligibility,
            decision,
            registry_digest,
        )
        try:
            with self._work_store.extension_transaction() as connection:
                self._insert_decision(
                    connection,
                    request=request,
                    eligibility=eligibility,
                    decision=decision,
                    registry_digest=digest,
                )
        except sqlite3.IntegrityError as exc:
            raise RoutingStoreError(
                f"routing decision cannot be created: {decision.decision_id}"
            ) from exc
        return PersistedRoutingDecision(
            work_id=request.work_id,
            registry_digest=digest,
            eligibility=eligibility,
            decision=decision,
        )

    def _insert_attempt(
        self,
        connection: sqlite3.Connection,
        attempt: RoutingAttempt,
    ) -> None:
        row = connection.execute(
            """
            SELECT work_id, decision_json
            FROM model_routing_decisions
            WHERE decision_id = ?
            """,
            (attempt.decision_id,),
        ).fetchone()
        if row is None:
            raise RoutingStoreError(
                f"unknown routing decision: {attempt.decision_id}"
            )
        if row["work_id"] != attempt.work_id:
            raise RoutingStoreError("routing attempt work_id does not match decision")
        decision = _decision_from_payload(
            self._work_store.decode_extension_json(row["decision_json"])
        )
        if attempt.target_id not in decision.ordered_target_ids:
            raise RoutingStoreError("routing attempt target is outside decision order")
        connection.execute(
            """
            INSERT INTO model_routing_attempts (
                attempt_id, decision_id, work_id, target_id,
                attempt_ordinal, attempt_json, started_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.attempt_id,
                attempt.decision_id,
                attempt.work_id,
                attempt.target_id,
                attempt.attempt_ordinal,
                self._work_store.encode_extension_json(
                    _attempt_payload(attempt)
                ),
                attempt.started_at_epoch,
            ),
        )

    def record_attempt(self, attempt: RoutingAttempt) -> RoutingAttempt:
        if not isinstance(attempt, RoutingAttempt):
            raise TypeError("attempt must be a RoutingAttempt")
        try:
            with self._work_store.extension_transaction() as connection:
                self._insert_attempt(connection, attempt)
        except sqlite3.IntegrityError as exc:
            raise RoutingStoreError(
                f"routing attempt cannot be created: {attempt.attempt_id}"
            ) from exc
        return attempt

    def record_decision_and_attempt(
        self,
        *,
        request: RoutingRequest,
        eligibility: EligibilitySnapshot,
        decision: RoutingDecision,
        registry_digest: str,
        attempt: RoutingAttempt,
    ) -> PersistedRoutingDecision:
        digest = self._validate_decision_inputs(
            request,
            eligibility,
            decision,
            registry_digest,
        )
        if attempt.decision_id != decision.decision_id:
            raise ValueError("attempt decision_id does not match decision")
        if attempt.work_id != request.work_id:
            raise ValueError("attempt work_id does not match request")
        try:
            with self._work_store.extension_transaction() as connection:
                self._insert_decision(
                    connection,
                    request=request,
                    eligibility=eligibility,
                    decision=decision,
                    registry_digest=digest,
                )
                self._insert_attempt(connection, attempt)
        except sqlite3.IntegrityError as exc:
            raise RoutingStoreError(
                "routing decision/attempt transaction could not be committed"
            ) from exc
        return PersistedRoutingDecision(
            work_id=request.work_id,
            registry_digest=digest,
            eligibility=eligibility,
            decision=decision,
        )

    def get_decision(self, decision_id: str) -> PersistedRoutingDecision | None:
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM model_routing_decisions
                WHERE decision_id = ?
                """,
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        return PersistedRoutingDecision(
            work_id=row["work_id"],
            registry_digest=row["registry_digest"],
            eligibility=_snapshot_from_payload(
                self._work_store.decode_extension_json(
                    row["eligibility_json"]
                )
            ),
            decision=_decision_from_payload(
                self._work_store.decode_extension_json(row["decision_json"])
            ),
        )

    def find_decision_by_request(
        self,
        routing_request_id: str,
    ) -> PersistedRoutingDecision | None:
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT decision_id FROM model_routing_decisions
                WHERE routing_request_id = ?
                """,
                (routing_request_id,),
            ).fetchone()
        if row is None:
            return None
        return self.get_decision(row["decision_id"])

    def list_attempts(self, decision_id: str) -> tuple[RoutingAttempt, ...]:
        with self._work_store.extension_transaction() as connection:
            rows = connection.execute(
                """
                SELECT attempt_json FROM model_routing_attempts
                WHERE decision_id = ?
                ORDER BY attempt_ordinal
                """,
                (decision_id,),
            ).fetchall()
        return tuple(
            _attempt_from_payload(
                self._work_store.decode_extension_json(row["attempt_json"])
            )
            for row in rows
        )

    def create_health(self, record: TargetHealthRecord) -> TargetHealthRecord:
        if not isinstance(record, TargetHealthRecord):
            raise TypeError("record must be a TargetHealthRecord")
        try:
            with self._work_store.extension_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO model_target_health (
                        target_id, state, consecutive_failures,
                        cooldown_until_epoch, last_failure_kind,
                        updated_at_epoch, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.target_id,
                        record.state.value,
                        record.consecutive_failures,
                        record.cooldown_until_epoch,
                        record.last_failure_kind,
                        record.updated_at_epoch,
                        record.version,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RoutingStoreError(
                f"target health already exists: {record.target_id}"
            ) from exc
        return record

    def get_health(self, target_id: str) -> TargetHealthRecord | None:
        normalized = target_id.strip().casefold()
        if not normalized:
            raise ValueError("target_id must not be empty")
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM model_target_health
                WHERE target_id = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return TargetHealthRecord(
            target_id=row["target_id"],
            state=TargetHealthEligibility(row["state"]),
            consecutive_failures=int(row["consecutive_failures"]),
            cooldown_until_epoch=(
                None
                if row["cooldown_until_epoch"] is None
                else float(row["cooldown_until_epoch"])
            ),
            last_failure_kind=row["last_failure_kind"],
            updated_at_epoch=float(row["updated_at_epoch"]),
            version=int(row["version"]),
        )

    def save_health(
        self,
        record: TargetHealthRecord,
        *,
        expected_version: int,
    ) -> TargetHealthRecord:
        if not isinstance(record, TargetHealthRecord):
            raise TypeError("record must be a TargetHealthRecord")
        if expected_version <= 0:
            raise ValueError("expected_version must be positive")
        with self._work_store.extension_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE model_target_health SET
                    state = ?, consecutive_failures = ?,
                    cooldown_until_epoch = ?, last_failure_kind = ?,
                    updated_at_epoch = ?, version = ?
                WHERE target_id = ? AND version = ?
                """,
                (
                    record.state.value,
                    record.consecutive_failures,
                    record.cooldown_until_epoch,
                    record.last_failure_kind,
                    record.updated_at_epoch,
                    record.version,
                    record.target_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RoutingStoreError(
                    "stale target health update rejected: "
                    f"{record.target_id} expected v{expected_version}"
                )
        return record
