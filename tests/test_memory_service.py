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
from jarvis.memory.service import (
    MemoryAlreadyExistsError,
    MemoryAmbiguousError,
    MemoryNotFoundError,
    MemoryService,
    canonical_memory_predicate,
)
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 9, 30, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(
    source_id: str, sensitivity: Sensitivity = Sensitivity.STANDARD
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:session:turn:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _workers(path: Path) -> tuple[SerialConnectionWorker, SerialConnectionWorker]:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return (
        SerialConnectionWorker(factory, thread_name="memory-service-writer"),
        SerialConnectionWorker(factory, thread_name="memory-service-reader"),
    )


def _services(
    writer: SerialConnectionWorker,
    reader: SerialConnectionWorker,
) -> tuple[MemoryLifecycleService, MemoryService]:
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    service = MemoryService(lifecycle, CanonicalMemoryReader(reader))
    return lifecycle, service


@pytest.mark.asyncio
async def test_explicit_remember_inspect_correct_forget_round_trip(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "memory-service.db")
    _, service = _services(writer, reader)
    try:
        remembered = await service.remember_text(
            predicate="Jimny tyre size",
            value="235/75 R15",
            source=_source("remember"),
        )
        assert remembered.predicate == "jimny_tyre_size"
        assert remembered.record.value == "235/75 R15"
        assert remembered.record.subject_scope == "personal"
        assert remembered.record.subject == "owner"

        inspected = await service.inspect_exact(predicate="jimny-tyre size")
        assert inspected.record.assertion_id == remembered.record.assertion_id

        corrected = await service.correct_text(
            predicate="jimny tyre size",
            value="215/75 R15",
            source=_source("correct"),
        )
        assert corrected.record.value == "215/75 R15"
        assert corrected.record.supersedes_id == remembered.record.assertion_id

        forgotten = await service.forget_exact(
            predicate="jimny tyre size",
            source=_source("forget"),
        )
        assert forgotten == "jimny_tyre_size"
        with pytest.raises(MemoryNotFoundError):
            await service.inspect_exact(predicate="jimny tyre size")
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_remember_existing_exact_predicate_requires_correction(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "memory-exists.db")
    _, service = _services(writer, reader)
    try:
        await service.remember_text(
            predicate="home city",
            value="Sagar",
            source=_source("first"),
        )
        with pytest.raises(MemoryAlreadyExistsError, match="use correction"):
            await service.remember_text(
                predicate="home-city",
                value="Indore",
                source=_source("second"),
            )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_exact_target_resolution_fails_closed_when_ambiguous(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "memory-ambiguous.db")
    lifecycle, service = _services(writer, reader)
    try:
        for index, value in enumerate(("one", "two"), start=1):
            await lifecycle.create(
                SemanticAssertionDraft(
                    subject_scope="personal",
                    subject="owner",
                    predicate="duplicate_key",
                    value_type=ValueType.TEXT,
                    value=value,
                    normalized_text=f"duplicate key: {value}",
                    freshness_class=FreshnessClass.CHANGEABLE,
                    sensitivity=Sensitivity.STANDARD,
                ),
                _source(f"duplicate-{index}"),
            )

        with pytest.raises(MemoryAmbiguousError):
            await service.inspect_exact(predicate="duplicate key")
        with pytest.raises(MemoryAmbiguousError):
            await service.forget_exact(
                predicate="duplicate key",
                source=_source("forget-command"),
            )
    finally:
        await reader.close()
        await writer.close()


def test_predicate_normalization_is_deterministic_and_unicode_safe() -> None:
    assert canonical_memory_predicate(" Jimny Tyre-Size ") == "jimny_tyre_size"
    assert canonical_memory_predicate("पसंदीदा जगह") == "पसंदीदा_जगह"
    with pytest.raises(ValueError):
        canonical_memory_predicate("---")


def test_predicate_normalization_folds_spoken_number_variants() -> None:
    assert canonical_memory_predicate("phase 4 test city") == "phase_4_test_city"
    assert canonical_memory_predicate("phase four test city") == "phase_4_test_city"
    assert canonical_memory_predicate("चरण चार परीक्षण शहर") == "चरण_4_परीक्षण_शहर"
