from __future__ import annotations

from .assertions import SemanticAssertionRecord
from .storage_rows import (
    SEMANTIC_ASSERTION_COLUMNS_SQL,
    semantic_assertion_record_from_row,
)
from .worker import SerialConnectionWorker


def _text(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _learning_current_scoped_sync(connection):
    from jarvis.personal_learning_scope import (
        LEGACY_FACETS,
        POLICY_VERSION,
        SUPPRESSION_KEYS,
        record_scope,
    )

    marks = ",".join("?" for _ in LEGACY_FACETS)
    scope_marks = ",".join("?" for _ in SUPPRESSION_KEYS)
    # An explicit text correction keeps the registered facet identity.
    # Its classification comes only from canonical typed admission history,
    # never from a guessed predicate prefix or the replacement text.
    registration = (
        "h.subject_scope=a.subject_scope AND h.subject=a.subject AND h.predicate=a.predicate"
        " AND h.sensitivity='standard' AND h.value_type='json'"
        " AND r.policy_version=? AND r.category IN (" + scope_marks + ")"
        " AND json_extract(h.value_json,'$.schema')=?"
        " AND json_extract(h.value_json,'$.category') IN ('owned_item','routine','goal','personal_fact','activity','event','plan')"
        " AND r.category=CASE json_extract(h.value_json,'$.category')"
        " WHEN 'owned_item' THEN 'owned_item.'||json_extract(h.value_json,'$.kind')"
        " ELSE json_extract(h.value_json,'$.category') END"
    )
    registration_values = (POLICY_VERSION, *SUPPRESSION_KEYS, POLICY_VERSION)
    registered_exists = (
        "SELECT 1 FROM personal_learning_receipt r JOIN semantic_assertion h ON h.assertion_id=r.target_id WHERE "
        + registration
    )
    rows = connection.execute(
        "SELECT "
        + ", ".join("a." + c.strip() for c in SEMANTIC_ASSERTION_COLUMNS_SQL.split(","))
        + " FROM current_semantic_assertion a JOIN memory_source s ON s.source_id=a.source_id"
        " WHERE a.subject_scope='personal' AND a.subject='owner'"
        " AND a.sensitivity='standard' AND s.sensitivity='standard'"
        " AND s.authority_class IN ('owner_explicit','owner_direct','verified')"
        " AND s.source_class IN ('owner_explicit','owner_direct')"
        " AND a.freshness_class != 'time_sensitive'"
        f" AND (a.predicate IN ({marks}) OR ("
        " json_extract(a.value_json,'$.schema')=? AND ("
        " (json_extract(a.value_json,'$.category')='owned_item' AND substr(a.predicate,1,11)='owned_item_' AND json_extract(a.value_json,'$.kind') IN ('vehicle','device','other')) OR"
        " (json_extract(a.value_json,'$.category')='routine' AND substr(a.predicate,1,8)='routine_') OR"
        " (json_extract(a.value_json,'$.category')='goal' AND substr(a.predicate,1,5)='goal_') OR"
        " (json_extract(a.value_json,'$.category') IN ('personal_fact','activity','event','plan') AND instr(a.predicate,json_extract(a.value_json,'$.category')||'_')=1)))"
        " OR (a.value_type='text' AND EXISTS (" + registered_exists + ")))"
        " ORDER BY a.predicate, a.assertion_id LIMIT 33",
        (*LEGACY_FACETS, POLICY_VERSION, *registration_values),
    ).fetchall()
    if len(rows) > 32:
        raise ValueError("learning_catalog_overflow")
    scoped = []
    for row in rows:
        record = semantic_assertion_record_from_row(row)
        scope = record_scope(record)
        if scope is None and record.value_type.value == "text":
            registered = connection.execute(
                "SELECT DISTINCT r.category FROM personal_learning_receipt r"
                " JOIN semantic_assertion h ON h.assertion_id=r.target_id"
                " JOIN current_semantic_assertion a ON a.assertion_id=? WHERE "
                + registration,
                (record.assertion_id, *registration_values),
            ).fetchall()
            if len(registered) == 1:
                scope = registered[0][0]
        if scope is not None:
            scoped.append((record, scope))
    return tuple(scoped)


class CanonicalMemoryReader:
    """Deterministic read-only query surface over a dedicated reader worker."""

    def __init__(self, reader: SerialConnectionWorker) -> None:
        self._reader = reader

    async def learning_suppression(self):
        from .learning_contracts import LearningSuppressionSnapshot

        rows = await self._reader.run(
            lambda c: c.execute(
                "SELECT category,epoch,suppressed FROM personal_learning_suppression"
            ).fetchall()
        )
        return LearningSuppressionSnapshot(
            {r[0]: r[1] for r in rows}, frozenset(r[0] for r in rows if r[2])
        )

    async def learning_current(self):
        return tuple(record for record, _ in await self.learning_current_scoped())

    async def learning_current_scoped(self):
        """Bounded standard owner snapshot; caller must hold learning read authority."""
        return await self._reader.run(_learning_current_scoped_sync)

    async def learning_context_snapshot(self):
        """Read current scoped facts and suppression in one coherent read transaction."""
        from jarvis.personal_learning_scope import SUPPRESSION_KEYS

        from .personal_context_projection import ScopedContextSnapshot

        def query(connection):
            connection.execute("SAVEPOINT personal_context_snapshot")
            try:
                entries = _learning_current_scoped_sync(connection)
                rows = connection.execute(
                    "SELECT category,epoch,suppressed FROM personal_learning_suppression"
                ).fetchall()
                epochs = {r[0]: (r[1], bool(r[2])) for r in rows}
                snapshot = ScopedContextSnapshot(
                    entries,
                    tuple(
                        (k, *epochs.get(k, (0, False)))
                        for k in sorted(SUPPRESSION_KEYS)
                    ),
                )
                connection.execute("RELEASE personal_context_snapshot")
                return snapshot
            except BaseException:
                connection.execute("ROLLBACK TO personal_context_snapshot")
                connection.execute("RELEASE personal_context_snapshot")
                raise

        return await self._reader.run(query)

    async def get_current(
        self,
        assertion_id: str,
    ) -> SemanticAssertionRecord | None:
        target = _text(assertion_id, name="assertion_id")

        def query(connection: object) -> SemanticAssertionRecord | None:
            row = connection.execute(  # type: ignore[attr-defined]
                f"SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL} "
                "FROM current_semantic_assertion WHERE assertion_id = ?",
                (target,),
            ).fetchone()
            if row is None:
                return None
            return semantic_assertion_record_from_row(row)

        return await self._reader.run(query)

    async def find_current_exact(
        self,
        *,
        subject_scope: str,
        subject: str,
        predicate: str,
    ) -> tuple[SemanticAssertionRecord, ...]:
        scope = _text(subject_scope, name="subject_scope")
        target_subject = _text(subject, name="subject")
        target_predicate = _text(predicate, name="predicate")

        def query(connection: object) -> tuple[SemanticAssertionRecord, ...]:
            rows = connection.execute(  # type: ignore[attr-defined]
                f"SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL} "
                "FROM current_semantic_assertion "
                "WHERE subject_scope = ? AND subject = ? AND predicate = ? "
                "ORDER BY system_from DESC, assertion_id ASC",
                (scope, target_subject, target_predicate),
            ).fetchall()
            return tuple(semantic_assertion_record_from_row(row) for row in rows)

        return await self._reader.run(query)
