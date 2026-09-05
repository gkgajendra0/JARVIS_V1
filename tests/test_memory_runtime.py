from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.database import SqlCipherUnavailableError
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.runtime import (
    MemoryRuntime,
    build_default_memory_runtime,
    default_memory_database_path,
)
from jarvis.memory.service import MemoryService
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 11, 0, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _runtime(path: Path) -> MemoryRuntime:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    writer = SerialConnectionWorker(factory, thread_name="memory-runtime-writer")
    reader = SerialConnectionWorker(factory, thread_name="memory-runtime-reader")
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    service = MemoryService(lifecycle, CanonicalMemoryReader(reader))
    return MemoryRuntime(service, writer=writer, reader=reader)


def test_default_memory_path_uses_machine_config_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine_path = tmp_path / "machine-root" / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(machine_path))
    assert default_memory_database_path() == machine_path.parent / "memory.db"


@pytest.mark.asyncio
async def test_memory_runtime_owns_worker_start_and_close(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime.db")
    await runtime.start()
    await runtime.start()
    await runtime.close()
    await runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.start()


@pytest.mark.asyncio
async def test_default_runtime_fails_closed_when_sqlcipher_driver_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import jarvis.memory.runtime as runtime_module

    class FakeFactory:
        def __init__(self, database_path, *, key_protector) -> None:
            del database_path, key_protector

        def open(self):
            raise SqlCipherUnavailableError("approved SQLCipher runtime is unavailable")

    monkeypatch.setattr(runtime_module, "WindowsDpapiKeyProtector", lambda: object())
    monkeypatch.setattr(runtime_module, "SqlCipherMemoryDatabaseFactory", FakeFactory)

    runtime = build_default_memory_runtime(tmp_path / "memory.db")
    with pytest.raises(SqlCipherUnavailableError, match="approved SQLCipher"):
        await runtime.start()
