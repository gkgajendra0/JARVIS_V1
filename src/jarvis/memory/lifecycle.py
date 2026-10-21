from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from .assertions import SemanticAssertionDraft, SemanticAssertionRecord
from .provenance import MemorySource
from .storage_rows import (
    SEMANTIC_ASSERTION_COLUMNS_SQL,
    semantic_assertion_record_from_row,
)
from .types import AssertionState, MemoryOperationType, VerificationState
from .worker import SerialConnectionWorker

T = TypeVar("T")
_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


class MemoryLifecycleError(RuntimeError):
    pass


class MemoryAssertionNotFound(MemoryLifecycleError):
    pass


class MemoryAssertionStateError(MemoryLifecycleError):
    pass


class MemorySourceConflictError(MemoryLifecycleError):
    pass


class MemoryCurrentFacetExistsError(MemoryLifecycleError):
    pass


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _db_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value, name="timestamp").isoformat().replace("+00:00", "Z")


def _reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("reason_code must be a string when provided")
    normalized = value.strip().casefold()
    if not _REASON_CODE.fullmatch(normalized):
        raise ValueError("reason_code must be a 1-64 character lowercase semantic code")
    return normalized


class MemoryLifecycleService:
    """Deterministic canonical semantic-memory lifecycle over one writer worker."""

    def __init__(
        self,
        writer: SerialConnectionWorker,
        *,
        clock: Callable[[], datetime] = _now,
        assertion_id_factory: Callable[[], str] = _new_id,
        operation_id_factory: Callable[[], str] = _new_id,
    ) -> None:
        self._writer = writer
        self._clock = clock
        self._assertion_id_factory = assertion_id_factory
        self._operation_id_factory = operation_id_factory

    async def create(
        self,
        draft: SemanticAssertionDraft,
        source: MemorySource,
        *,
        reason_code: str | None = None,
        require_absent_current: bool = False,
        commit_guard: Callable[[], None] | None = None,
    ) -> SemanticAssertionRecord:
        if type(require_absent_current) is not bool:
            raise TypeError("require_absent_current must be a bool")
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._create_sync(
                connection, draft, source, reason, require_absent_current, commit_guard
            )
        )

    async def historical_change(
        self,
        assertion_id: str,
        replacement: SemanticAssertionDraft,
        source: MemorySource,
        *,
        effective_at: datetime,
        reason_code: str | None = None,
    ) -> SemanticAssertionRecord:
        target = self._assertion_id(assertion_id)
        effective = _utc(effective_at, name="effective_at")
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._historical_change_sync(
                connection,
                target,
                replacement,
                source,
                effective,
                reason,
            )
        )

    async def correct(
        self,
        assertion_id: str,
        replacement: SemanticAssertionDraft,
        source: MemorySource,
        *,
        reason_code: str | None = None,
        commit_guard: Callable[[], None] | None = None,
    ) -> SemanticAssertionRecord:
        target = self._assertion_id(assertion_id)
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._correct_sync(
                connection,
                target,
                replacement,
                source,
                reason,
                commit_guard,
            )
        )

    async def retract(
        self,
        assertion_id: str,
        source: MemorySource,
        *,
        reason_code: str | None = None,
    ) -> SemanticAssertionRecord:
        target = self._assertion_id(assertion_id)
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._close_without_replacement_sync(
                connection,
                target,
                source,
                operation_type=MemoryOperationType.RETRACT,
                state=AssertionState.RETRACTED,
                effective_at=None,
                reason_code=reason,
            )
        )

    async def verify(
        self,
        assertion_id: str,
        source: MemorySource,
        *,
        verified_at: datetime,
        reason_code: str | None = None,
    ) -> SemanticAssertionRecord:
        target = self._assertion_id(assertion_id)
        verified = _utc(verified_at, name="verified_at")
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._verify_sync(
                connection,
                target,
                source,
                verified,
                reason,
            )
        )

    async def expire(
        self,
        assertion_id: str,
        source: MemorySource,
        *,
        effective_at: datetime,
        reason_code: str | None = None,
    ) -> SemanticAssertionRecord:
        target = self._assertion_id(assertion_id)
        effective = _utc(effective_at, name="effective_at")
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._close_without_replacement_sync(
                connection,
                target,
                source,
                operation_type=MemoryOperationType.EXPIRE,
                state=AssertionState.EXPIRED,
                effective_at=effective,
                reason_code=reason,
            )
        )

    async def forget(
        self,
        assertion_id: str,
        source: MemorySource,
        *,
        reason_code: str | None = "explicit_owner_request",
        commit_guard: Callable[[], None] | None = None,
        require_current: bool = False,
    ) -> bool:
        target = self._assertion_id(assertion_id)
        reason = _reason_code(reason_code)
        return await self._writer.run(
            lambda connection: self._forget_sync(
                connection,
                target,
                source,
                reason,
                commit_guard,
                require_current,
            )
        )

    async def get(self, assertion_id: str) -> SemanticAssertionRecord | None:
        target = self._assertion_id(assertion_id)
        return await self._writer.run(
            lambda connection: self._get_sync(connection, target)
        )

    async def get_current(self, assertion_id: str) -> SemanticAssertionRecord | None:
        target = self._assertion_id(assertion_id)
        return await self._writer.run(
            lambda connection: self._get_current_sync(connection, target)
        )

    async def apply_learning_batch(self, plan, permit, authority):
        return await self._writer.run(
            lambda connection: self._apply_learning_sync(
                connection, plan, permit, authority
            )
        )

    def _apply_learning_sync(self, connection, plan, permit, authority):
        from jarvis.authority.personal_learning import POLICY_VERSION

        from .learning_contracts import LearningAdmissionResult

        def guard():
            authority.validate_write(permit)
            if (
                authority.child_binding(permit) != plan.binding()
                or authority.source_for(permit) is not plan.source
            ):
                raise PermissionError("learning payload changed")

        def mutation():
            replayed = []
            for m in plan.mutations:
                row = connection.execute(
                    "SELECT payload_digest,target_id FROM personal_learning_receipt WHERE source_turn_id=? AND candidate_ordinal=? AND policy_version=?",
                    (plan.source.turn_id, m.ordinal, POLICY_VERSION),
                ).fetchone()
                if row and row[0] != plan.digest:
                    raise PermissionError("changed replay payload")
                replayed.append(row)
            if replayed and all(replayed):
                return LearningAdmissionResult(
                    "noop", tuple(row[1] for row in replayed)
                )
            if any(replayed):
                raise PermissionError("partial replay batch")
            for m in plan.mutations:
                row = connection.execute(
                    "SELECT epoch,suppressed FROM personal_learning_suppression WHERE category=?",
                    (m.category_key,),
                ).fetchone()
                epoch, suppressed = row if row else (0, 0)
                if suppressed or epoch != dict(plan.suppression_epochs).get(
                    m.category_key, 0
                ):
                    raise PermissionError("learning category epoch changed")
                current = connection.execute(
                    "SELECT assertion_id FROM current_semantic_assertion WHERE subject_scope='personal' AND subject='owner' AND predicate=?",
                    (m.predicate,),
                ).fetchall()
                if [r[0] for r in current] != (
                    [m.expected_assertion_id] if m.expected_assertion_id else []
                ):
                    return LearningAdmissionResult("stale")
            ids = []
            for m in plan.mutations:
                if m.action == "create":
                    record = self._create_sync(
                        connection,
                        m.draft,
                        m.source,
                        "automatic_learning",
                        True,
                        join_existing=True,
                    )
                elif m.action == "correct":
                    record = self._correct_sync(
                        connection,
                        m.expected_assertion_id,
                        m.draft,
                        m.source,
                        "automatic_learning",
                        join_existing=True,
                    )
                elif m.action == "change":
                    record = self._historical_change_sync(
                        connection,
                        m.expected_assertion_id,
                        m.draft,
                        m.source,
                        m.source.observed_at,
                        "automatic_learning",
                        join_existing=True,
                    )
                else:
                    record = self._close_without_replacement_sync(
                        connection,
                        m.expected_assertion_id,
                        m.source,
                        operation_type=MemoryOperationType.RETRACT,
                        state=AssertionState.RETRACTED,
                        effective_at=None,
                        reason_code="automatic_learning",
                        join_existing=True,
                    )
                ids.append(record.assertion_id)
                connection.execute(
                    "INSERT INTO personal_learning_receipt VALUES (?,?,?,?,?,?,?,?)",
                    (
                        plan.source.runtime_id,
                        plan.source.turn_id,
                        m.ordinal,
                        POLICY_VERSION,
                        m.category_key,
                        plan.digest,
                        m.source.source_id,
                        record.assertion_id,
                    ),
                )
            return LearningAdmissionResult("committed" if ids else "noop", tuple(ids))

        with authority.commit_scope(permit):
            return self._transaction(connection, mutation, guard)

    def _create_sync(
        self,
        connection: Any,
        draft: SemanticAssertionDraft,
        source: MemorySource,
        reason_code: str | None,
        require_absent_current: bool,
        commit_guard: Callable[[], None] | None = None,
        join_existing: bool = False,
    ) -> SemanticAssertionRecord:
        def mutation() -> SemanticAssertionRecord:
            if require_absent_current:
                existing = connection.execute(
                    "SELECT 1 FROM current_semantic_assertion "
                    "WHERE subject_scope = ? AND subject = ? AND predicate = ? LIMIT 1",
                    (draft.subject_scope, draft.subject, draft.predicate),
                ).fetchone()
                if existing is not None:
                    raise MemoryCurrentFacetExistsError(
                        "current memory already exists for the requested facet"
                    )
            now = self._clock_utc()
            self._ensure_source(connection, source)
            assertion_id = self._fresh_assertion_id()
            self._insert_assertion(
                connection,
                assertion_id=assertion_id,
                draft=draft,
                source_id=source.source_id,
                valid_from=draft.valid_from,
                system_from=now,
                supersedes_id=None,
                created_at=now,
            )
            self._insert_operation(
                connection,
                operation_type=MemoryOperationType.CREATE,
                target_id=assertion_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state=AssertionState.ACTIVE.value,
            )
            return self._require_record(connection, assertion_id)

        return self._transaction(
            connection, mutation, commit_guard, join_existing=join_existing
        )

    def _historical_change_sync(
        self,
        connection: Any,
        assertion_id: str,
        replacement: SemanticAssertionDraft,
        source: MemorySource,
        effective_at: datetime,
        reason_code: str | None,
        join_existing: bool = False,
    ) -> SemanticAssertionRecord:
        def mutation() -> SemanticAssertionRecord:
            now = self._clock_utc()
            self._ensure_source(connection, source)
            current = self._require_current(connection, assertion_id)
            if current.valid_from is not None and effective_at < current.valid_from:
                raise MemoryLifecycleError(
                    "historical change effective_at precedes current valid_from"
                )
            replacement_id = self._fresh_assertion_id()
            connection.execute(
                """
                UPDATE semantic_assertion
                SET valid_to = ?,
                    system_to = ?,
                    state = 'superseded',
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    _db_time(effective_at),
                    _db_time(now),
                    _db_time(now),
                    assertion_id,
                ),
            )
            self._insert_assertion(
                connection,
                assertion_id=replacement_id,
                draft=replacement,
                source_id=source.source_id,
                valid_from=effective_at,
                system_from=now,
                supersedes_id=assertion_id,
                created_at=now,
            )
            self._insert_operation(
                connection,
                operation_type=MemoryOperationType.HISTORICAL_CHANGE,
                target_id=replacement_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state=AssertionState.ACTIVE.value,
            )
            return self._require_record(connection, replacement_id)

        return self._transaction(connection, mutation, join_existing=join_existing)

    def _correct_sync(
        self,
        connection: Any,
        assertion_id: str,
        replacement: SemanticAssertionDraft,
        source: MemorySource,
        reason_code: str | None,
        commit_guard: Callable[[], None] | None = None,
        join_existing: bool = False,
    ) -> SemanticAssertionRecord:
        def mutation() -> SemanticAssertionRecord:
            now = self._clock_utc()
            self._ensure_source(connection, source)
            current = self._require_current(connection, assertion_id)
            replacement_id = self._fresh_assertion_id()
            connection.execute(
                """
                UPDATE semantic_assertion
                SET system_to = ?,
                    state = 'retracted',
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (_db_time(now), _db_time(now), assertion_id),
            )
            self._insert_assertion(
                connection,
                assertion_id=replacement_id,
                draft=replacement,
                source_id=source.source_id,
                valid_from=(
                    replacement.valid_from
                    if replacement.valid_from is not None
                    else current.valid_from
                ),
                system_from=now,
                supersedes_id=assertion_id,
                created_at=now,
            )
            self._insert_operation(
                connection,
                operation_type=MemoryOperationType.CORRECT,
                target_id=replacement_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state=AssertionState.ACTIVE.value,
            )
            return self._require_record(connection, replacement_id)

        return self._transaction(
            connection, mutation, commit_guard, join_existing=join_existing
        )

    def _close_without_replacement_sync(
        self,
        connection: Any,
        assertion_id: str,
        source: MemorySource,
        *,
        operation_type: MemoryOperationType,
        state: AssertionState,
        effective_at: datetime | None,
        reason_code: str | None,
        join_existing: bool = False,
    ) -> SemanticAssertionRecord:
        def mutation() -> SemanticAssertionRecord:
            now = self._clock_utc()
            self._ensure_source(connection, source)
            current = self._require_current(connection, assertion_id)
            if (
                effective_at is not None
                and current.valid_from is not None
                and effective_at < current.valid_from
            ):
                raise MemoryLifecycleError(
                    f"{operation_type.value} effective_at precedes current valid_from"
                )
            connection.execute(
                """
                UPDATE semantic_assertion
                SET valid_to = CASE WHEN ? IS NULL THEN valid_to ELSE ? END,
                    system_to = ?,
                    state = ?,
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    _db_time(effective_at),
                    _db_time(effective_at),
                    _db_time(now),
                    state.value,
                    _db_time(now),
                    assertion_id,
                ),
            )
            self._insert_operation(
                connection,
                operation_type=operation_type,
                target_id=assertion_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state=state.value,
            )
            return self._require_record(connection, assertion_id)

        return self._transaction(connection, mutation, join_existing=join_existing)

    def _verify_sync(
        self,
        connection: Any,
        assertion_id: str,
        source: MemorySource,
        verified_at: datetime,
        reason_code: str | None,
    ) -> SemanticAssertionRecord:
        def mutation() -> SemanticAssertionRecord:
            now = self._clock_utc()
            self._ensure_source(connection, source)
            existing = self._require_record(connection, assertion_id)
            if existing.state is AssertionState.RETRACTED:
                raise MemoryAssertionStateError(
                    "retracted assertion cannot be verified"
                )
            connection.execute(
                """
                UPDATE semantic_assertion
                SET verification_state = 'verified',
                    last_verified_at = ?,
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (_db_time(verified_at), _db_time(now), assertion_id),
            )
            self._insert_operation(
                connection,
                operation_type=MemoryOperationType.VERIFY,
                target_id=assertion_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state=VerificationState.VERIFIED.value,
            )
            return self._require_record(connection, assertion_id)

        return self._transaction(connection, mutation)

    def _forget_sync(
        self,
        connection: Any,
        assertion_id: str,
        source: MemorySource,
        reason_code: str | None,
        commit_guard: Callable[[], None] | None = None,
        require_current: bool = False,
    ) -> bool:
        def mutation() -> bool:
            target = self._get_sync(connection, assertion_id)
            if target is None:
                return False
            if require_current:
                self._require_current(connection, assertion_id)
            if source.source_id == target.source_id:
                raise MemorySourceConflictError(
                    "forget command provenance must be distinct from target provenance"
                )
            now = self._clock_utc()
            self._ensure_source(connection, source)
            target_source_id = target.source_id

            connection.execute(
                "DELETE FROM memory_operation WHERE target_id = ?",
                (assertion_id,),
            )
            connection.execute(
                "DELETE FROM semantic_assertion WHERE assertion_id = ?",
                (assertion_id,),
            )
            connection.execute(
                """
                DELETE FROM memory_source
                WHERE source_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM semantic_assertion
                      WHERE source_id = ?
                  )
                """,
                (target_source_id, target_source_id),
            )
            self._insert_operation(
                connection,
                operation_type=MemoryOperationType.FORGET,
                target_id=assertion_id,
                source_id=source.source_id,
                occurred_at=now,
                reason_code=reason_code,
                result_state="forgotten",
            )

            canonical_count = connection.execute(
                "SELECT count(*) FROM semantic_assertion WHERE assertion_id = ?",
                (assertion_id,),
            ).fetchone()[0]
            current_count = connection.execute(
                "SELECT count(*) FROM current_semantic_assertion WHERE assertion_id = ?",
                (assertion_id,),
            ).fetchone()[0]
            if canonical_count != 0 or current_count != 0:
                raise MemoryLifecycleError("forget failed to purge canonical assertion")
            return True

        return self._transaction(connection, mutation, commit_guard)

    def _ensure_source(self, connection: Any, source: MemorySource) -> None:
        if source.evidence_text is not None:
            raise MemoryLifecycleError(
                "canonical semantic memory must not copy raw source evidence text"
            )
        expected = (
            source.source_class.value,
            source.canonical_ref,
            _db_time(source.source_created_at),
            _db_time(source.observed_at),
            source.authority_class.value,
            source.sensitivity.value,
            None,
            source.evidence_hash,
            source.external_ref,
            _db_time(source.created_at),
        )
        existing = connection.execute(
            """
            SELECT
                source_class,
                canonical_ref,
                source_created_at,
                observed_at,
                authority_class,
                sensitivity,
                evidence_text,
                evidence_hash,
                external_ref,
                created_at
            FROM memory_source
            WHERE source_id = ?
            """,
            (source.source_id,),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO memory_source (
                    source_id,
                    source_class,
                    canonical_ref,
                    source_created_at,
                    observed_at,
                    authority_class,
                    sensitivity,
                    evidence_text,
                    evidence_hash,
                    external_ref,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source.source_id, *expected),
            )
            return
        if tuple(existing) != expected:
            raise MemorySourceConflictError(
                f"source_id {source.source_id!r} already exists with different provenance"
            )

    def _insert_assertion(
        self,
        connection: Any,
        *,
        assertion_id: str,
        draft: SemanticAssertionDraft,
        source_id: str,
        valid_from: datetime | None,
        system_from: datetime,
        supersedes_id: str | None,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO semantic_assertion (
                assertion_id,
                subject_scope,
                subject,
                predicate,
                value_type,
                value_json,
                normalized_text,
                source_id,
                valid_from,
                valid_to,
                system_from,
                system_to,
                last_verified_at,
                state,
                supersedes_id,
                verification_state,
                confidence,
                freshness_class,
                sensitivity,
                created_at,
                updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, 'active', ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                assertion_id,
                draft.subject_scope,
                draft.subject,
                draft.predicate,
                draft.value_type.value,
                draft.value_json,
                draft.normalized_text,
                source_id,
                _db_time(valid_from),
                _db_time(system_from),
                _db_time(draft.last_verified_at),
                supersedes_id,
                draft.verification_state.value,
                draft.confidence,
                draft.freshness_class.value,
                draft.sensitivity.value,
                _db_time(created_at),
                _db_time(created_at),
            ),
        )

    def _insert_operation(
        self,
        connection: Any,
        *,
        operation_type: MemoryOperationType,
        target_id: str,
        source_id: str | None,
        occurred_at: datetime,
        reason_code: str | None,
        result_state: str,
    ) -> None:
        operation_id = self._operation_id_factory()
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise MemoryLifecycleError("operation ID factory returned an invalid ID")
        connection.execute(
            """
            INSERT INTO memory_operation (
                operation_id,
                operation_type,
                target_kind,
                target_id,
                source_id,
                occurred_at,
                reason_code,
                result_state,
                content_fingerprint
            ) VALUES (?, ?, 'semantic_assertion', ?, ?, ?, ?, ?, NULL)
            """,
            (
                operation_id.strip(),
                operation_type.value,
                target_id,
                source_id,
                _db_time(occurred_at),
                reason_code,
                result_state,
            ),
        )

    def _get_sync(
        self,
        connection: Any,
        assertion_id: str,
    ) -> SemanticAssertionRecord | None:
        row = connection.execute(
            f"SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL} "
            "FROM semantic_assertion WHERE assertion_id = ?",
            (assertion_id,),
        ).fetchone()
        return None if row is None else semantic_assertion_record_from_row(row)

    def _get_current_sync(
        self,
        connection: Any,
        assertion_id: str,
    ) -> SemanticAssertionRecord | None:
        row = connection.execute(
            f"SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL} "
            "FROM current_semantic_assertion WHERE assertion_id = ?",
            (assertion_id,),
        ).fetchone()
        return None if row is None else semantic_assertion_record_from_row(row)

    def _require_record(
        self, connection: Any, assertion_id: str
    ) -> SemanticAssertionRecord:
        record = self._get_sync(connection, assertion_id)
        if record is None:
            raise MemoryAssertionNotFound(
                f"memory assertion {assertion_id!r} does not exist"
            )
        return record

    def _require_current(
        self, connection: Any, assertion_id: str
    ) -> SemanticAssertionRecord:
        current = self._get_current_sync(connection, assertion_id)
        if current is not None:
            return current
        existing = self._get_sync(connection, assertion_id)
        if existing is None:
            raise MemoryAssertionNotFound(
                f"memory assertion {assertion_id!r} does not exist"
            )
        raise MemoryAssertionStateError(
            f"memory assertion {assertion_id!r} is not current/active"
        )

    def _fresh_assertion_id(self) -> str:
        assertion_id = self._assertion_id_factory()
        return self._assertion_id(assertion_id)

    @staticmethod
    def _assertion_id(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("assertion_id must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("assertion_id must not be empty")
        return normalized

    def _clock_utc(self) -> datetime:
        return _utc(self._clock(), name="clock")

    @staticmethod
    def _transaction(
        connection: Any,
        mutation: Callable[[], T],
        commit_guard: Callable[[], None] | None = None,
        *,
        join_existing: bool = False,
    ) -> T:
        if join_existing:
            if not connection.in_transaction:
                raise MemoryLifecycleError("missing outer transaction")
            return mutation()
        connection.execute("BEGIN IMMEDIATE")
        try:
            if commit_guard is not None:
                commit_guard()
            result = mutation()
            if commit_guard is not None:
                commit_guard()
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
