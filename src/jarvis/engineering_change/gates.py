"""Exact artifact-bound owner decisions; never executable Authority permits."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .models import ChangeConflict, ChangeState
from .store import ChangeStore, _now


class GateKind(str, Enum):
    ARCHITECTURE = "architecture"
    ACCEPTANCE = "acceptance"
    PROMOTION = "promotion"


_STATES = {
    GateKind.ARCHITECTURE: (
        ChangeState.ARCHITECTURE_READY,
        ChangeState.WAITING_OWNER_APPROVAL,
        ChangeState.APPROVED_FOR_BUILD,
    ),
    GateKind.ACCEPTANCE: (
        ChangeState.VERIFYING,
        ChangeState.WAITING_OWNER_ACCEPTANCE,
        ChangeState.READY_FOR_PROMOTION,
    ),
    GateKind.PROMOTION: (
        ChangeState.READY_FOR_PROMOTION,
        ChangeState.WAITING_PROMOTION_APPROVAL,
        ChangeState.WAITING_PROMOTION_APPROVAL,
    ),
}


@dataclass(frozen=True, slots=True)
class GateChallenge:
    gate_id: str
    change_id: str
    kind: GateKind
    artifact_id: str
    artifact_digest: str
    created_at: str


@dataclass(frozen=True, slots=True)
class GateDecision:
    challenge: GateChallenge
    approved: bool
    actor_id: str
    source_session_id: str
    source_turn_id: str
    request_key: str
    decided_at: str


class GateService:
    def __init__(
        self,
        store: ChangeStore,
        *,
        verify_owner: Callable[[str, str, str, GateChallenge, str], bool],
    ) -> None:
        self.store = store
        self._verify_owner = verify_owner

    @staticmethod
    def _challenge(row: sqlite3.Row) -> GateChallenge:
        return GateChallenge(
            row["gate_id"],
            row["change_id"],
            GateKind(row["kind"]),
            row["artifact_id"],
            row["artifact_digest"],
            row["created_at"],
        )

    def present(
        self, change_id: str, kind: GateKind, artifact_id: str
    ) -> GateChallenge:
        required, waiting, _ = _STATES[kind]
        artifact = self.store.get_artifact(artifact_id)
        if (
            artifact is None
            or artifact.change_id != change_id
            or artifact.kind != kind.value
        ):
            raise ChangeConflict("gate artifact does not match kind or change")
        work = self.store.work
        with work._lock, work._connect() as db:
            change = self._require_change(db, change_id)
            if change.state not in {required, waiting}:
                raise ChangeConflict("change is not ready for this gate")
            row = db.execute(
                "SELECT * FROM engineering_change_gates WHERE change_id=? AND kind=? AND artifact_id=?",
                (change_id, kind.value, artifact_id),
            ).fetchone()
            if row is None:
                challenge = GateChallenge(
                    "gate_" + uuid.uuid4().hex[:16],
                    change_id,
                    kind,
                    artifact_id,
                    artifact.digest,
                    _now(),
                )
                db.execute(
                    "INSERT INTO engineering_change_gates VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        challenge.gate_id,
                        change_id,
                        kind.value,
                        artifact_id,
                        artifact.digest,
                        challenge.created_at,
                    ),
                )
            else:
                challenge = self._challenge(row)
            if change.state is required:
                db.execute(
                    "UPDATE engineering_changes SET state=?, version=version+1, updated_at=? WHERE change_id=?",
                    (waiting.value, _now(), change_id),
                )
            return challenge

    def _require_change(self, db: sqlite3.Connection, change_id: str):
        row = db.execute(
            "SELECT * FROM engineering_changes WHERE change_id=?", (change_id,)
        ).fetchone()
        if row is None:
            raise ChangeConflict("unknown change")
        return self.store._from_row(row)

    def get(self, gate_id: str) -> GateDecision | GateChallenge | None:
        work = self.store.work
        with work._lock, work._connect() as db:
            gate = db.execute(
                "SELECT * FROM engineering_change_gates WHERE gate_id=?", (gate_id,)
            ).fetchone()
            if gate is None:
                return None
            challenge = self._challenge(gate)
            decision = db.execute(
                "SELECT * FROM engineering_change_decisions WHERE gate_id=?", (gate_id,)
            ).fetchone()
            return (
                challenge if decision is None else self._decision(challenge, decision)
            )

    @staticmethod
    def _decision(challenge: GateChallenge, row: sqlite3.Row) -> GateDecision:
        return GateDecision(
            challenge,
            bool(row["approved"]),
            row["actor_id"],
            row["source_session_id"],
            row["source_turn_id"],
            row["request_key"],
            row["decided_at"],
        )

    def decide(
        self,
        gate_id: str,
        *,
        approved: bool,
        artifact_digest: str,
        actor_id: str,
        source_session_id: str,
        source_turn_id: str,
        request_key: str,
    ) -> GateDecision:
        if not all(
            (
                actor_id.strip(),
                source_session_id.strip(),
                source_turn_id.strip(),
                request_key.strip(),
            )
        ):
            raise ChangeConflict(
                "trusted owner source and request identity are required"
            )
        work = self.store.work
        with work._lock, work._connect() as db:
            gate = db.execute(
                "SELECT * FROM engineering_change_gates WHERE gate_id=?", (gate_id,)
            ).fetchone()
            if gate is None:
                raise ChangeConflict("unknown gate")
            challenge = self._challenge(gate)
            if artifact_digest != challenge.artifact_digest:
                raise ChangeConflict("reviewed artifact digest does not match")
            existing = db.execute(
                "SELECT * FROM engineering_change_decisions WHERE gate_id=?", (gate_id,)
            ).fetchone()
            if existing is not None:
                result = self._decision(challenge, existing)
                if (
                    result.approved,
                    result.actor_id,
                    result.source_session_id,
                    result.source_turn_id,
                    result.request_key,
                ) != (
                    approved,
                    actor_id,
                    source_session_id,
                    source_turn_id,
                    request_key,
                ):
                    raise ChangeConflict("gate decision already differs")
                return result
            if not self._verify_owner(
                actor_id,
                source_session_id,
                source_turn_id,
                challenge,
                artifact_digest,
            ):
                raise ChangeConflict("trusted owner verification denied")
            latest = db.execute(
                """SELECT artifact_id, digest FROM engineering_change_artifacts
                WHERE change_id=? AND kind=? ORDER BY revision DESC LIMIT 1""",
                (challenge.change_id, challenge.kind.value),
            ).fetchone()
            if latest is None or (latest["artifact_id"], latest["digest"]) != (
                challenge.artifact_id,
                challenge.artifact_digest,
            ):
                raise ChangeConflict("reviewed artifact was superseded")
            change = self._require_change(db, challenge.change_id)
            _, waiting, approved_state = _STATES[challenge.kind]
            if change.state is not waiting:
                raise ChangeConflict("change is no longer awaiting this gate")
            decided_at = _now()
            try:
                db.execute(
                    "INSERT INTO engineering_change_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        gate_id,
                        int(approved),
                        actor_id,
                        source_session_id,
                        source_turn_id,
                        request_key,
                        decided_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ChangeConflict("owner decision request key already used") from exc
            db.execute(
                "UPDATE engineering_changes SET state=?, version=version+1, updated_at=? WHERE change_id=?",
                (
                    (approved_state if approved else ChangeState.REJECTED).value,
                    decided_at,
                    challenge.change_id,
                ),
            )
            return GateDecision(
                challenge,
                approved,
                actor_id,
                source_session_id,
                source_turn_id,
                request_key,
                decided_at,
            )
