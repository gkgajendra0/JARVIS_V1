"""Synthetic SQLite proof for read-only revision metadata resolution.

No owner database, SQLCipher key, provider call or production write is touched.
The SQLite fixtures are disposable and contain only invented project facts.
"""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.revision_shadow import (
    RevisionDisposition,
    RevisionIntent,
    RevisionShadowInput,
    assess_revision_shadow,
)
from jarvis.memory.revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.candidates import MemoryExtractionSensitivity
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


def _ids(prefix: str):
    sequence = itertools.count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _draft(
    text: str, *, predicate: str = "reply_style", sensitivity=Sensitivity.STANDARD
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="personal",
        subject="owner",
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=sensitivity,
    )


def _source(
    ident: str,
    *,
    source_class=MemorySourceClass.OWNER_EXPLICIT,
    authority=AuthorityClass.OWNER_EXPLICIT,
    sensitivity=Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=ident,
        source_class=source_class,
        canonical_ref=f"conversation:synthetic:{ident}",
        observed_at=BASE,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _setup(path: Path):
    def writer_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    def reader_factory() -> sqlite3.Connection:
        # SQLite itself refuses all mutations on the research reader.
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection

    writer = SerialConnectionWorker(
        writer_factory, thread_name="revision-shadow-synthetic-writer"
    )
    read_worker = SerialConnectionWorker(
        reader_factory, thread_name="revision-shadow-synthetic-reader"
    )
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("synthetic"),
        operation_id_factory=_ids("operation"),
    )
    return writer, read_worker, lifecycle, CanonicalRevisionSnapshotReader(read_worker)


@pytest.mark.asyncio
async def test_derived_lineage_version_and_owner_source_metadata(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "facts.db")
    try:
        first = await lifecycle.create(
            _draft("short examples"), _source("owner-initial")
        )
        changed = await lifecycle.correct(
            first.assertion_id,
            _draft("detailed examples"),
            _source("owner-correction"),
        )
        snapshot = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        witness = snapshot.witness
        assert witness is not None
        assert witness.assertion_id == changed.assertion_id
        assert witness.assertion_version == 2
        assert witness.canonical_source_ref == "conversation:synthetic:owner-correction"
        assert witness.latest_version_verified
        assert witness.owner_authority_verified
        assert witness.meaning_equivalent_verified is None

        decision = assess_revision_shadow(
            RevisionShadowInput(
                accepted_user_turn=True,
                source_class=MemorySourceClass.OWNER_DIRECT,
                sensitivity=MemoryExtractionSensitivity.NORMAL,
                intent=RevisionIntent.FACT_CORRECTION,
                witness=witness,
            )
        )
        assert decision.disposition is RevisionDisposition.CONFLICT_REVIEW
        assert not hasattr(decision, "value")
        assert not hasattr(decision, "authorized_write")
        assert not hasattr(witness, "value")

        # The old assertion must never be accepted as the latest one.
        assert changed.supersedes_id == first.assertion_id
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_missing_or_ambiguous_canonical_target_is_not_guessed(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "ambiguous.db")
    try:
        missing = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert missing.witness is None
        assert missing.reason_code == "canonical_target_not_found"
        await lifecycle.create(_draft("small examples"), _source("owner-one"))
        await lifecycle.create(_draft("large examples"), _source("owner-two"))
        ambiguous = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert ambiguous.witness is None
        assert ambiguous.reason_code == "ambiguous_current_assertions"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_wrong_scope_and_untrusted_source_fail_closed(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "untrusted.db")
    try:
        await lifecycle.create(
            _draft("short examples"),
            _source(
                "untrusted-web",
                source_class=MemorySourceClass.EXTERNAL_WEB,
                authority=AuthorityClass.UNTRUSTED,
            ),
        )
        for scope, reason in [
            ("wrong-scope", "canonical_target_not_found"),
            ("personal", "canonical_owner_source_not_verified"),
        ]:
            result = await resolver.resolve_exact(
                subject_scope=scope, subject="owner", predicate="reply_style"
            )
            assert result.witness is None
            assert result.reason_code == reason
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_restricted_sensitive_assertion_never_returns_witness(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "private.db")
    try:
        await lifecycle.create(
            _draft("fictional sensitive item", sensitivity=Sensitivity.PRIVATE),
            _source("private", sensitivity=Sensitivity.PRIVATE),
        )
        result = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert result.witness is None
        assert result.reason_code == "canonical_sensitivity_restricted"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_retraction_removes_current_target_from_revision_resolver(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "retracted.db")
    try:
        original = await lifecycle.create(_draft("short examples"), _source("initial"))
        await lifecycle.retract(original.assertion_id, _source("retracted"))
        result = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert result.witness is None
        assert result.reason_code == "canonical_target_not_found"
    finally:
        await reader.close()
        await writer.close()
