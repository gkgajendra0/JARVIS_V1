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
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 7, 0, tzinfo=UTC)


def ids(prefix: str):
    sequence = itertools.count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def source(source_id: str) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:reader-test:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=Sensitivity.STANDARD,
        created_at=BASE,
    )


def draft(
    value: str,
    *,
    predicate: str = "vehicle_preference",
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="owner",
        subject="owner",
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=value,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=Sensitivity.STANDARD,
    )


def workers_for(
    database_path: Path,
) -> tuple[SerialConnectionWorker, SerialConnectionWorker]:
    def writer_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    def reader_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    return (
        SerialConnectionWorker(
            writer_factory,
            thread_name="jarvis-memory-query-writer",
        ),
        SerialConnectionWorker(
            reader_factory,
            thread_name="jarvis-memory-query-reader",
        ),
    )


@pytest.mark.asyncio
async def test_reader_uses_separate_connection_and_tracks_committed_current_truth(
    tmp_path: Path,
) -> None:
    writer, reader_worker = workers_for(tmp_path / "reader.db")
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=ids("assertion"),
        operation_id_factory=ids("operation"),
    )
    reader = CanonicalMemoryReader(reader_worker)

    await writer.start()
    await reader_worker.start()
    try:
        assert writer.owner_thread_id is not None
        assert reader_worker.owner_thread_id is not None
        assert writer.owner_thread_id != reader_worker.owner_thread_id

        original = await lifecycle.create(
            draft("235/75 R15"),
            source("source-original"),
        )
        first = await reader.find_current_exact(
            subject_scope="owner",
            subject="owner",
            predicate="vehicle_preference",
        )
        assert [record.assertion_id for record in first] == [original.assertion_id]
        assert first[0].freshness_class is FreshnessClass.CHANGEABLE
        assert await reader.get_current(original.assertion_id) == first[0]

        changed = await lifecycle.historical_change(
            original.assertion_id,
            draft("215/75 R15"),
            source("source-change"),
            effective_at=datetime(2026, 9, 6, tzinfo=UTC),
        )
        current = await reader.find_current_exact(
            subject_scope="owner",
            subject="owner",
            predicate="vehicle_preference",
        )
        assert [record.assertion_id for record in current] == [changed.assertion_id]
        assert await reader.get_current(original.assertion_id) is None
        assert await reader.get_current(changed.assertion_id) == current[0]
    finally:
        await reader_worker.close()
        await writer.close()


@pytest.mark.asyncio
async def test_exact_reader_filters_and_orders_multiple_current_matches(
    tmp_path: Path,
) -> None:
    writer, reader_worker = workers_for(tmp_path / "exact.db")
    assertion_ids = iter(("z-assertion", "a-assertion", "other-assertion"))
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=lambda: next(assertion_ids),
        operation_id_factory=ids("operation"),
    )
    reader = CanonicalMemoryReader(reader_worker)

    await writer.start()
    await reader_worker.start()
    try:
        await lifecycle.create(draft("first"), source("source-first"))
        await lifecycle.create(draft("second"), source("source-second"))
        await lifecycle.create(
            draft("unrelated", predicate="audio_preference"),
            source("source-other"),
        )

        matches = await reader.find_current_exact(
            subject_scope="owner",
            subject="owner",
            predicate="vehicle_preference",
        )
        assert [record.assertion_id for record in matches] == [
            "a-assertion",
            "z-assertion",
        ]
        assert [record.value for record in matches] == ["second", "first"]

        assert (
            await reader.find_current_exact(
                subject_scope="owner",
                subject="someone-else",
                predicate="vehicle_preference",
            )
            == ()
        )
    finally:
        await reader_worker.close()
        await writer.close()
