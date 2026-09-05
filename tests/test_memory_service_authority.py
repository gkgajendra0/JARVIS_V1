from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.service import MemoryService, MemoryServiceError
from jarvis.memory.types import (
    AuthorityClass,
    MemorySourceClass,
    Sensitivity,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 11, 30, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _workers(path: Path) -> tuple[SerialConnectionWorker, SerialConnectionWorker]:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return (
        SerialConnectionWorker(factory, thread_name="memory-authority-writer"),
        SerialConnectionWorker(factory, thread_name="memory-authority-reader"),
    )


def _service(
    writer: SerialConnectionWorker,
    reader: SerialConnectionWorker,
) -> MemoryService:
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    return MemoryService(lifecycle, CanonicalMemoryReader(reader))


def _source(
    source_id: str,
    *,
    source_class: MemorySourceClass = MemorySourceClass.OWNER_EXPLICIT,
    authority_class: AuthorityClass = AuthorityClass.OWNER_EXPLICIT,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=source_class,
        canonical_ref=f"conversation:session:turn:{source_id}",
        observed_at=BASE,
        authority_class=authority_class,
        sensitivity=sensitivity,
        created_at=BASE,
    )


@pytest.mark.asyncio
async def test_explicit_memory_service_rejects_non_explicit_source_authority(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "authority.db")
    service = _service(writer, reader)
    try:
        with pytest.raises(MemoryServiceError, match="owner-explicit source"):
            await service.remember_text(
                predicate="home city",
                value="Sagar",
                source=_source(
                    "direct",
                    source_class=MemorySourceClass.OWNER_DIRECT,
                    authority_class=AuthorityClass.OWNER_DIRECT,
                ),
            )

        count = await reader.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM semantic_assertion"
            ).fetchone()[0]
        )
        assert count == 0
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_explicit_memory_service_rejects_source_sensitivity_mismatch(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "sensitivity.db")
    service = _service(writer, reader)
    try:
        with pytest.raises(MemoryServiceError, match="sensitivity must match"):
            await service.remember_text(
                predicate="home city",
                value="Sagar",
                source=_source("private-source", sensitivity=Sensitivity.PRIVATE),
                sensitivity=Sensitivity.STANDARD,
            )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_forget_rechecks_owner_explicit_authority_before_delete(
    tmp_path: Path,
) -> None:
    writer, reader = _workers(tmp_path / "forget-authority.db")
    service = _service(writer, reader)
    try:
        remembered = await service.remember_text(
            predicate="home city",
            value="Sagar",
            source=_source("remember"),
        )
        with pytest.raises(MemoryServiceError, match="owner-explicit source"):
            await service.forget_exact(
                predicate="home city",
                source=_source(
                    "forget-direct",
                    source_class=MemorySourceClass.OWNER_DIRECT,
                    authority_class=AuthorityClass.OWNER_DIRECT,
                ),
            )

        still_present = await service.inspect_exact(predicate="home city")
        assert still_present.record.assertion_id == remembered.record.assertion_id
    finally:
        await reader.close()
        await writer.close()
