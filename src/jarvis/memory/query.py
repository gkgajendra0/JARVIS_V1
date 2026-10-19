from __future__ import annotations

from datetime import datetime

from .assertions import SemanticAssertionRecord
from .provenance import MemorySource
from .storage_rows import (
    SEMANTIC_ASSERTION_COLUMNS_SQL,
    semantic_assertion_record_from_row,
)
from .types import AuthorityClass, MemorySourceClass, Sensitivity
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

    async def get_source(self, source_id: str) -> MemorySource | None:
        """Read immutable canonical provenance; this grants no release permission."""
        target = _text(source_id, name="source_id")

        def query(connection: object) -> MemorySource | None:
            row = connection.execute(  # type: ignore[attr-defined]
                "SELECT source_class, canonical_ref, observed_at, authority_class, "
                "sensitivity, created_at, source_created_at, evidence_hash, external_ref "
                "FROM memory_source WHERE source_id = ?",
                (target,),
            ).fetchone()
            if row is None:
                return None
            return MemorySource(
                source_id=target,
                source_class=MemorySourceClass(row[0]),
                canonical_ref=str(row[1]),
                observed_at=datetime.fromisoformat(str(row[2])),
                authority_class=AuthorityClass(row[3]),
                sensitivity=Sensitivity(row[4]),
                created_at=datetime.fromisoformat(str(row[5])),
                source_created_at=None
                if row[6] is None
                else datetime.fromisoformat(str(row[6])),
                evidence_hash=row[7],
                external_ref=row[8],
            )

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
