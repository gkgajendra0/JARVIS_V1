"""Durable provenance for C3 global brain routing decisions."""

from __future__ import annotations

import sqlite3

from jarvis.brain_routing.models import (
    BrainRouteKind,
    BrainRouteRecord,
    BrainRoutingMode,
)
from jarvis.work.store import SQLiteWorkStore


class BrainRouteStoreError(RuntimeError):
    pass


def _payload(record: BrainRouteRecord) -> dict[str, object]:
    return {
        "route_request_id": record.route_request_id,
        "work_id": record.work_id,
        "subsystem_key": record.subsystem_key,
        "task_kind": record.task_kind,
        "route_kind": record.route_kind.value,
        "mode": record.mode.value,
        "policy_version": record.policy_version,
        "policy_digest": record.policy_digest,
        "reason_codes": list(record.reason_codes),
        "created_at_epoch": record.created_at_epoch,
        "selected_action": record.selected_action,
        "resolver_id": record.resolver_id,
        "resolver_version": record.resolver_version,
        "shadow_proposed_action": record.shadow_proposed_action,
        "shadow_match": record.shadow_match,
        "model_decision_id": record.model_decision_id,
        "model_target_id": record.model_target_id,
        "goal_complete": record.goal_complete,
        "needs_owner": record.needs_owner,
        "owner_question": record.owner_question,
        "parameters_digest": record.parameters_digest,
        "outcome_code": record.outcome_code,
    }


def _record(payload: dict[str, object]) -> BrainRouteRecord:
    return BrainRouteRecord(
        route_request_id=str(payload["route_request_id"]),
        work_id=str(payload["work_id"]),
        subsystem_key=str(payload["subsystem_key"]),
        task_kind=str(payload["task_kind"]),
        route_kind=BrainRouteKind(str(payload["route_kind"])),
        mode=BrainRoutingMode(str(payload["mode"])),
        policy_version=int(payload["policy_version"]),
        policy_digest=str(payload["policy_digest"]),
        reason_codes=tuple(str(item) for item in payload["reason_codes"]),
        created_at_epoch=float(payload["created_at_epoch"]),
        selected_action=(
            None
            if payload.get("selected_action") is None
            else str(payload["selected_action"])
        ),
        resolver_id=(
            None if payload.get("resolver_id") is None else str(payload["resolver_id"])
        ),
        resolver_version=(
            None
            if payload.get("resolver_version") is None
            else int(payload["resolver_version"])
        ),
        shadow_proposed_action=(
            None
            if payload.get("shadow_proposed_action") is None
            else str(payload["shadow_proposed_action"])
        ),
        shadow_match=(
            None
            if payload.get("shadow_match") is None
            else bool(payload["shadow_match"])
        ),
        model_decision_id=(
            None
            if payload.get("model_decision_id") is None
            else str(payload["model_decision_id"])
        ),
        model_target_id=(
            None
            if payload.get("model_target_id") is None
            else str(payload["model_target_id"])
        ),
        goal_complete=payload.get("goal_complete"),
        needs_owner=payload.get("needs_owner"),
        owner_question=(
            None
            if payload.get("owner_question") is None
            else str(payload["owner_question"])
        ),
        parameters_digest=(
            None
            if payload.get("parameters_digest") is None
            else str(payload["parameters_digest"])
        ),
        outcome_code=str(payload.get("outcome_code") or "selected"),
    )


class BrainRouteStore:
    """Store one immutable global route choice per canonical reasoning cycle."""

    def __init__(self, work_store: SQLiteWorkStore) -> None:
        if not isinstance(work_store, SQLiteWorkStore):
            raise TypeError("work_store must be a SQLiteWorkStore")
        self._work_store = work_store
        self._initialize()

    def _initialize(self) -> None:
        with self._work_store.extension_transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS brain_route_decisions (
                    route_request_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    route_kind TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_brain_route_decisions_work
                    ON brain_route_decisions(work_id, created_at_epoch);

                CREATE TABLE IF NOT EXISTS brain_route_context_snapshots (
                    route_request_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_brain_route_context_snapshots_work
                    ON brain_route_context_snapshots(work_id, created_at_epoch);
                """
            )

    def get(self, route_request_id: str) -> BrainRouteRecord | None:
        normalized = str(route_request_id).strip()
        if not normalized:
            raise ValueError("route_request_id must not be empty")
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT route_json
                FROM brain_route_decisions
                WHERE route_request_id = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return _record(self._work_store.decode_extension_json(row["route_json"]))

    def record(self, record: BrainRouteRecord) -> BrainRouteRecord:
        if not isinstance(record, BrainRouteRecord):
            raise TypeError("record must be a BrainRouteRecord")
        encoded = self._work_store.encode_extension_json(_payload(record))
        try:
            with self._work_store.extension_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO brain_route_decisions (
                        route_request_id,
                        work_id,
                        route_kind,
                        route_json,
                        created_at_epoch
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.route_request_id,
                        record.work_id,
                        record.route_kind.value,
                        encoded,
                        record.created_at_epoch,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get(record.route_request_id)
            if existing is None:
                raise BrainRouteStoreError(
                    "brain route decision conflicted without recoverable record"
                )
            if existing.work_id != record.work_id:
                raise BrainRouteStoreError(
                    "brain route request id is already bound to another work item"
                )
            return existing
        return record

    def list_for_work(self, work_id: str) -> tuple[BrainRouteRecord, ...]:
        normalized = str(work_id).strip()
        if not normalized:
            raise ValueError("work_id must not be empty")
        with self._work_store.extension_transaction() as connection:
            rows = connection.execute(
                """
                SELECT route_json
                FROM brain_route_decisions
                WHERE work_id = ?
                ORDER BY created_at_epoch, route_request_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(
            _record(self._work_store.decode_extension_json(row["route_json"]))
            for row in rows
        )

    def record_context_snapshot(
        self,
        *,
        route_request_id: str,
        work_id: str,
        snapshot: dict[str, object],
        created_at_epoch: float,
    ) -> dict[str, object]:
        """Persist one bounded C6 replay snapshot without duplicating Work history."""

        route_id = str(route_request_id).strip()
        normalized_work_id = str(work_id).strip()
        if not route_id or not normalized_work_id:
            raise ValueError("route_request_id and work_id are required")
        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be an object")
        if snapshot.get("schema") != "c6_work_reasoning_snapshot.v1":
            raise ValueError("unsupported C6 work reasoning snapshot schema")
        encoded = self._work_store.encode_extension_json(snapshot)
        with self._work_store.extension_transaction() as connection:
            existing = connection.execute(
                """
                SELECT work_id, snapshot_json
                FROM brain_route_context_snapshots
                WHERE route_request_id = ?
                """,
                (route_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["work_id"]) != normalized_work_id:
                    raise BrainRouteStoreError(
                        "C6 context snapshot route is bound to another WorkItem"
                    )
                current = self._work_store.decode_extension_json(
                    str(existing["snapshot_json"])
                )
                if current != snapshot:
                    raise BrainRouteStoreError(
                        "C6 context snapshot conflicts with durable provenance"
                    )
                return dict(current)
            connection.execute(
                """
                INSERT INTO brain_route_context_snapshots (
                    route_request_id, work_id, snapshot_json, created_at_epoch
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    route_id,
                    normalized_work_id,
                    encoded,
                    float(created_at_epoch),
                ),
            )
        return dict(snapshot)

    def get_context_snapshot(
        self,
        route_request_id: str,
    ) -> dict[str, object] | None:
        route_id = str(route_request_id).strip()
        if not route_id:
            raise ValueError("route_request_id must not be empty")
        with self._work_store.extension_transaction() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json
                FROM brain_route_context_snapshots
                WHERE route_request_id = ?
                """,
                (route_id,),
            ).fetchone()
        if row is None:
            return None
        payload = self._work_store.decode_extension_json(str(row["snapshot_json"]))
        if not isinstance(payload, dict):
            raise BrainRouteStoreError("C6 context snapshot payload is invalid")
        if payload.get("schema") != "c6_work_reasoning_snapshot.v1":
            raise BrainRouteStoreError("C6 context snapshot schema is invalid")
        return dict(payload)

    def summary_for_work(self, work_id: str) -> dict[str, int]:
        records = self.list_for_work(work_id)
        deterministic = sum(
            item.route_kind is BrainRouteKind.DETERMINISTIC for item in records
        )
        model = sum(item.route_kind is BrainRouteKind.MODEL for item in records)
        shadow_matches = sum(item.shadow_match is True for item in records)
        shadow_mismatches = sum(item.shadow_match is False for item in records)
        return {
            "route_count": len(records),
            "deterministic_routes": deterministic,
            "model_routes": model,
            "model_calls_avoided": deterministic,
            "shadow_matches": shadow_matches,
            "shadow_mismatches": shadow_mismatches,
        }
