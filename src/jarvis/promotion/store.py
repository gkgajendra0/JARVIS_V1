"""Durable idempotent promotion-attempt records in the canonical Work database."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from jarvis.engineering_change.models import ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest

from .models import PromotionAttempt, PromotionAttemptState


def _now() -> str:
    return datetime.now(UTC).isoformat()


_TRANSITIONS: dict[PromotionAttemptState, frozenset[PromotionAttemptState]] = {
    PromotionAttemptState.CREATED: frozenset(
        {
            PromotionAttemptState.EVIDENCE_READY,
            PromotionAttemptState.STALE,
            PromotionAttemptState.BLOCKED,
            PromotionAttemptState.FAILED,
        }
    ),
    PromotionAttemptState.EVIDENCE_READY: frozenset(
        {
            PromotionAttemptState.AUTHORIZED,
            PromotionAttemptState.STALE,
            PromotionAttemptState.BLOCKED,
            PromotionAttemptState.FAILED,
        }
    ),
    PromotionAttemptState.AUTHORIZED: frozenset(
        {
            PromotionAttemptState.MERGED,
            PromotionAttemptState.STALE,
            PromotionAttemptState.FAILED,
        }
    ),
    PromotionAttemptState.MERGED: frozenset(
        {PromotionAttemptState.DEPLOYING, PromotionAttemptState.FAILED}
    ),
    PromotionAttemptState.DEPLOYING: frozenset(
        {
            PromotionAttemptState.OBSERVING,
            PromotionAttemptState.ROLLED_BACK,
            PromotionAttemptState.FAILED,
        }
    ),
    PromotionAttemptState.OBSERVING: frozenset(
        {
            PromotionAttemptState.COMPLETED,
            PromotionAttemptState.ROLLED_BACK,
            PromotionAttemptState.FAILED,
        }
    ),
    PromotionAttemptState.STALE: frozenset(),
    PromotionAttemptState.BLOCKED: frozenset(),
    PromotionAttemptState.FAILED: frozenset(),
    PromotionAttemptState.COMPLETED: frozenset(),
    PromotionAttemptState.ROLLED_BACK: frozenset(),
}


class PromotionStore:
    """Operational promotion truth; EngineeringChange remains lifecycle authority."""

    _SCHEMA_VERSION = 1

    def __init__(self, changes: ChangeStore) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        self.changes = changes
        work = changes.work
        schema = """
            CREATE TABLE IF NOT EXISTS promotion_attempts (
                attempt_id TEXT PRIMARY KEY,
                change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
                candidate_artifact_id TEXT NOT NULL
                    REFERENCES engineering_change_artifacts(artifact_id),
                candidate_artifact_digest TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_digest TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                head_sha TEXT NOT NULL,
                state TEXT NOT NULL,
                pr_number INTEGER,
                promotion_artifact_id TEXT,
                promotion_artifact_digest TEXT,
                merge_sha TEXT,
                deployment_id TEXT,
                lkg_sha TEXT,
                last_reason TEXT,
                version INTEGER NOT NULL CHECK(version > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(change_id, candidate_artifact_id, candidate_digest)
            );
            CREATE INDEX IF NOT EXISTS idx_promotion_change
                ON promotion_attempts(change_id, created_at);
            CREATE TABLE IF NOT EXISTS promotion_schema (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL
            );
        """
        checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()
        with work._lock, work._connect() as db, db:
            db.executescript(schema)
            row = db.execute(
                "SELECT checksum FROM promotion_schema WHERE version=?",
                (self._SCHEMA_VERSION,),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO promotion_schema(version, checksum) VALUES (?, ?)",
                    (self._SCHEMA_VERSION, checksum),
                )
            elif row["checksum"] != checksum:
                raise ChangeConflict("promotion schema checksum mismatch")

    @staticmethod
    def _attempt_id(
        *,
        change_id: str,
        candidate_artifact_id: str,
        candidate_digest: str,
        base_sha: str,
        head_sha: str,
    ) -> str:
        digest = canonical_digest(
            {
                "change_id": change_id,
                "candidate_artifact_id": candidate_artifact_id,
                "candidate_digest": candidate_digest,
                "base_sha": base_sha,
                "head_sha": head_sha,
            }
        )
        return f"promotion_{digest[:16]}"

    @staticmethod
    def _from_row(row) -> PromotionAttempt:
        return PromotionAttempt(
            attempt_id=row["attempt_id"],
            change_id=row["change_id"],
            candidate_artifact_id=row["candidate_artifact_id"],
            candidate_artifact_digest=row["candidate_artifact_digest"],
            candidate_id=row["candidate_id"],
            candidate_digest=row["candidate_digest"],
            base_sha=row["base_sha"],
            head_sha=row["head_sha"],
            state=PromotionAttemptState(row["state"]),
            pr_number=row["pr_number"],
            promotion_artifact_id=row["promotion_artifact_id"],
            promotion_artifact_digest=row["promotion_artifact_digest"],
            merge_sha=row["merge_sha"],
            deployment_id=row["deployment_id"],
            lkg_sha=row["lkg_sha"],
            last_reason=row["last_reason"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_or_get(
        self,
        *,
        change_id: str,
        candidate_artifact_id: str,
        candidate_artifact_digest: str,
        candidate_id: str,
        candidate_digest: str,
        base_sha: str,
        head_sha: str,
    ) -> PromotionAttempt:
        self.changes.require(change_id)
        attempt_id = self._attempt_id(
            change_id=change_id,
            candidate_artifact_id=candidate_artifact_id,
            candidate_digest=candidate_digest,
            base_sha=base_sha,
            head_sha=head_sha,
        )
        timestamp = _now()
        work = self.changes.work
        with work._lock, work._connect() as db:
            existing = db.execute(
                "SELECT * FROM promotion_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                attempt = self._from_row(existing)
                expected = (
                    candidate_artifact_digest,
                    candidate_id,
                    candidate_digest,
                    base_sha,
                    head_sha,
                )
                observed = (
                    attempt.candidate_artifact_digest,
                    attempt.candidate_id,
                    attempt.candidate_digest,
                    attempt.base_sha,
                    attempt.head_sha,
                )
                if observed != expected:
                    raise ChangeConflict("promotion attempt identity conflict")
                return attempt
            db.execute(
                """INSERT INTO promotion_attempts (
                    attempt_id, change_id, candidate_artifact_id,
                    candidate_artifact_digest, candidate_id, candidate_digest,
                    base_sha, head_sha, state, pr_number, promotion_artifact_id,
                    promotion_artifact_digest, merge_sha, deployment_id, lkg_sha,
                    last_reason, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL,
                          NULL, NULL, 1, ?, ?)""",
                (
                    attempt_id,
                    change_id,
                    candidate_artifact_id,
                    candidate_artifact_digest,
                    candidate_id,
                    candidate_digest,
                    base_sha,
                    head_sha,
                    PromotionAttemptState.CREATED.value,
                    timestamp,
                    timestamp,
                ),
            )
            row = db.execute(
                "SELECT * FROM promotion_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        assert row is not None
        return self._from_row(row)

    def get(self, attempt_id: str) -> PromotionAttempt | None:
        work = self.changes.work
        with work._lock, work._connect() as db:
            row = db.execute(
                "SELECT * FROM promotion_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def require(self, attempt_id: str) -> PromotionAttempt:
        attempt = self.get(attempt_id)
        if attempt is None:
            raise ChangeConflict(f"unknown promotion attempt: {attempt_id}")
        return attempt

    def list_by_states(
        self,
        states: tuple[PromotionAttemptState, ...],
        *,
        limit: int = 20,
    ) -> tuple[PromotionAttempt, ...]:
        if not states or any(
            not isinstance(state, PromotionAttemptState) for state in states
        ):
            raise ValueError("promotion state filter must be non-empty and typed")
        if type(limit) is not int or limit <= 0:
            raise ValueError("promotion list limit must be positive")
        placeholders = ",".join("?" for _ in states)
        work = self.changes.work
        with work._lock, work._connect() as db:
            rows = db.execute(
                f"""SELECT * FROM promotion_attempts
                WHERE state IN ({placeholders})
                ORDER BY created_at, attempt_id
                LIMIT ?""",
                (*[state.value for state in states], limit),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def transition(
        self,
        attempt_id: str,
        state: PromotionAttemptState,
        *,
        expected_version: int,
        reason: str | None = None,
        pr_number: int | None = None,
        promotion_artifact_id: str | None = None,
        promotion_artifact_digest: str | None = None,
        merge_sha: str | None = None,
        deployment_id: str | None = None,
        lkg_sha: str | None = None,
    ) -> PromotionAttempt:
        if not isinstance(state, PromotionAttemptState):
            raise TypeError("state must be PromotionAttemptState")
        work = self.changes.work
        with work._lock, work._connect() as db:
            row = db.execute(
                "SELECT * FROM promotion_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ChangeConflict(f"unknown promotion attempt: {attempt_id}")
            current = self._from_row(row)
            if current.version != expected_version:
                raise ChangeConflict("stale promotion attempt update")
            if state is current.state:
                return current
            if state not in _TRANSITIONS[current.state]:
                raise ChangeConflict(
                    f"invalid promotion transition: {current.state.value} -> {state.value}"
                )
            timestamp = _now()
            values = {
                "pr_number": current.pr_number if pr_number is None else pr_number,
                "promotion_artifact_id": (
                    current.promotion_artifact_id
                    if promotion_artifact_id is None
                    else promotion_artifact_id
                ),
                "promotion_artifact_digest": (
                    current.promotion_artifact_digest
                    if promotion_artifact_digest is None
                    else promotion_artifact_digest
                ),
                "merge_sha": current.merge_sha if merge_sha is None else merge_sha,
                "deployment_id": (
                    current.deployment_id if deployment_id is None else deployment_id
                ),
                "lkg_sha": current.lkg_sha if lkg_sha is None else lkg_sha,
            }
            cursor = db.execute(
                """UPDATE promotion_attempts SET
                    state=?, pr_number=?, promotion_artifact_id=?,
                    promotion_artifact_digest=?, merge_sha=?, deployment_id=?,
                    lkg_sha=?, last_reason=?, version=version+1, updated_at=?
                    WHERE attempt_id=? AND version=?""",
                (
                    state.value,
                    values["pr_number"],
                    values["promotion_artifact_id"],
                    values["promotion_artifact_digest"],
                    values["merge_sha"],
                    values["deployment_id"],
                    values["lkg_sha"],
                    reason,
                    timestamp,
                    attempt_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ChangeConflict("stale promotion attempt update")
            updated = db.execute(
                "SELECT * FROM promotion_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        assert updated is not None
        return self._from_row(updated)
