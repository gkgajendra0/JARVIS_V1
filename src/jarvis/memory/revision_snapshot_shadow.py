"""Read-only canonical metadata snapshot for Step-4 revision research.

The injected SerialConnectionWorker MUST be a research-controlled reader, not
a production writer or a memory database opened by this module. This module
queries metadata and provenance only, never values or source evidence text.
It does not run an LLM, approve a mutation, or invoke ContextAssembler.

SQLite fixtures in tests are synthetic. A positive witness confirms only
versioned assertion identity, source classification and exact key matching;
semantic equivalence is deliberately unknown and no auto-write is permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .revision_shadow import CanonicalRevisionWitness
from .types import AuthorityClass, MemorySourceClass, Sensitivity
from .worker import SerialConnectionWorker

_MAX_LINEAGE = 64
_OWNER_PROVENANCE = {
    (MemorySourceClass.OWNER_DIRECT.value, AuthorityClass.OWNER_DIRECT.value),
    (MemorySourceClass.OWNER_EXPLICIT.value, AuthorityClass.OWNER_EXPLICIT.value),
}


@dataclass(frozen=True, slots=True)
class CanonicalSnapshotResolution:
    witness: CanonicalRevisionWitness | None
    reason_code: str


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


class CanonicalRevisionSnapshotReader:
    """Isolated research reader using an *injected* serialized connection.

    Never constructs a database, inspects an owner database path, or performs
    a SQL mutation. Its queries contain no raw memory value or source text.
    """

    def __init__(self, reader: SerialConnectionWorker) -> None:
        if not isinstance(reader, SerialConnectionWorker):
            raise TypeError("reader must be a SerialConnectionWorker")
        self._reader = reader

    async def resolve_exact(
        self,
        *,
        subject_scope: str,
        subject: str,
        predicate: str,
    ) -> CanonicalSnapshotResolution:
        scope = _required_text(subject_scope, "subject_scope")
        owner = _required_text(subject, "subject")
        key = _required_text(predicate, "predicate")
        return await self._reader.run(
            lambda connection: _resolve_metadata(
                connection, subject_scope=scope, subject=owner, predicate=key
            )
        )


def _resolve_metadata(
    connection: Any, *, subject_scope: str, subject: str, predicate: str
) -> CanonicalSnapshotResolution:
    # Exact matching and LIMIT 2: never arbitrarily select among duplicates.
    rows = connection.execute(
        """
        SELECT a.assertion_id, a.supersedes_id, a.source_id,
               a.sensitivity, s.source_class, s.authority_class,
               s.sensitivity, s.canonical_ref
          FROM current_semantic_assertion a
          LEFT JOIN memory_source s ON s.source_id = a.source_id
         WHERE a.subject_scope = ? AND a.subject = ? AND a.predicate = ?
         ORDER BY a.assertion_id ASC
         LIMIT 2
        """,
        (subject_scope, subject, predicate),
    ).fetchall()
    if not rows:
        return CanonicalSnapshotResolution(None, "canonical_target_not_found")
    if len(rows) != 1:
        return CanonicalSnapshotResolution(None, "ambiguous_current_assertions")

    assertion_id, predecessor, source_id, sensitivity, source_class, authority, source_sensitivity, source_ref = rows[0]
    if (
        sensitivity != Sensitivity.STANDARD.value
        or source_sensitivity != Sensitivity.STANDARD.value
    ):
        return CanonicalSnapshotResolution(None, "canonical_sensitivity_restricted")
    if (source_class, authority) not in _OWNER_PROVENANCE or not source_ref:
        return CanonicalSnapshotResolution(None, "canonical_owner_source_not_verified")
    if not isinstance(source_id, str) or not source_id:
        return CanonicalSnapshotResolution(None, "canonical_source_missing")

    # A current record with any active descendant cannot be certified as the
    # latest version, even if an inconsistent external writer created one.
    successor = connection.execute(
        """
        SELECT assertion_id FROM semantic_assertion
         WHERE supersedes_id = ? AND state = 'active'
           AND system_to IS NULL AND valid_to IS NULL
         LIMIT 1
        """,
        (assertion_id,),
    ).fetchone()
    if successor is not None:
        return CanonicalSnapshotResolution(None, "canonical_version_not_latest")

    # Each lifecycle replacement gets a new assertion_id; *no stored integer*
    # version exists. Derive a bounded ordinal from the supersedes chain.
    # Missing ancestors or a cycle mean we cannot certify the version.
    seen: set[str] = {assertion_id}
    revision_count = 1
    next_id = predecessor
    while next_id is not None:
        if revision_count >= _MAX_LINEAGE or next_id in seen:
            return CanonicalSnapshotResolution(None, "canonical_lineage_unverified")
        ancestor = connection.execute(
            """
            SELECT assertion_id, supersedes_id, subject_scope, subject, predicate
              FROM semantic_assertion WHERE assertion_id = ?
            """,
            (next_id,),
        ).fetchone()
        if ancestor is None or ancestor[2:] != (
            subject_scope,
            subject,
            predicate,
        ):
            return CanonicalSnapshotResolution(None, "canonical_lineage_unverified")
        seen.add(ancestor[0])
        revision_count += 1
        next_id = ancestor[1]

    return CanonicalSnapshotResolution(
        witness=CanonicalRevisionWitness(
            assertion_id=assertion_id,
            assertion_version=revision_count,
            # This is the actual persisted source reference, *not* a fabricated
            # "canonical:" label or proof of semantic equivalence.
            canonical_source_ref=source_ref,
            active=True,
            latest_version_verified=True,
            owner_authority_verified=True,
            same_subject_predicate_verified=True,
            meaning_equivalent_verified=None,
        ),
        reason_code="canonical_metadata_exact_match_only",
    )
