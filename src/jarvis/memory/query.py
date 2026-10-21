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


class CanonicalMemoryReader:
    """Deterministic read-only query surface over a dedicated reader worker."""

    def __init__(self, reader: SerialConnectionWorker) -> None:
        self._reader = reader

    async def learning_current(self):
        """Bounded standard owner snapshot; caller must hold learning read authority."""

        def query(connection):
            rows = connection.execute(
                "SELECT "
                + ", ".join(
                    "a." + c.strip() for c in SEMANTIC_ASSERTION_COLUMNS_SQL.split(",")
                )
                + " FROM current_semantic_assertion a JOIN memory_source s ON s.source_id=a.source_id"
                " WHERE a.subject_scope='personal' AND a.subject='owner'"
                " AND a.sensitivity='standard' AND s.sensitivity='standard'"
                " AND s.authority_class IN ('owner_explicit','owner_direct','verified')"
                " AND s.source_class IN ('owner_explicit','owner_direct')"
                " AND a.freshness_class != 'time_sensitive'"
                " ORDER BY a.predicate, a.assertion_id LIMIT 33"
            ).fetchall()
            if len(rows) > 32:
                raise ValueError("learning_catalog_overflow")
            return tuple(semantic_assertion_record_from_row(r) for r in rows)

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
