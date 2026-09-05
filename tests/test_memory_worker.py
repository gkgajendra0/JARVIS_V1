from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from jarvis.memory.worker import MemoryWorkerClosedError, SerialConnectionWorker


@pytest.mark.asyncio
async def test_worker_creates_and_uses_connection_on_one_thread(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    factory_thread_ids: list[int] = []

    def connection_factory() -> sqlite3.Connection:
        factory_thread_ids.append(threading.get_ident())
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE counter(value INTEGER NOT NULL)")
        connection.execute("INSERT INTO counter(value) VALUES (0)")
        connection.commit()
        return connection

    worker = SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-writer",
    )
    await worker.start()

    operation_thread_ids: list[int] = []

    def increment(connection: sqlite3.Connection) -> int:
        operation_thread_ids.append(threading.get_ident())
        connection.execute("UPDATE counter SET value = value + 1")
        connection.commit()
        return connection.execute("SELECT value FROM counter").fetchone()[0]

    values = [await worker.run(increment) for _ in range(5)]
    assert values == [1, 2, 3, 4, 5]
    assert factory_thread_ids == [worker.owner_thread_id]
    assert set(operation_thread_ids) == {worker.owner_thread_id}

    await worker.close()


@pytest.mark.asyncio
async def test_worker_serializes_concurrent_async_callers(tmp_path: Path) -> None:
    database_path = tmp_path / "serialized.db"

    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY)")
        connection.commit()
        return connection

    worker = SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-serial",
    )

    def insert_next(connection: sqlite3.Connection) -> int:
        current = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events"
        ).fetchone()[0]
        value = int(current) + 1
        connection.execute("INSERT INTO events(sequence) VALUES (?)", (value,))
        connection.commit()
        return value

    import asyncio

    values = await asyncio.gather(*(worker.run(insert_next) for _ in range(20)))
    assert sorted(values) == list(range(1, 21))
    assert await worker.run(
        lambda connection: connection.execute("SELECT count(*) FROM events").fetchone()[0]
    ) == 20

    await worker.close()


@pytest.mark.asyncio
async def test_closed_worker_rejects_new_operations() -> None:
    worker = SerialConnectionWorker(
        lambda: sqlite3.connect(":memory:"),
        thread_name="jarvis-memory-close",
    )
    await worker.start()
    await worker.close()
    await worker.close()

    with pytest.raises(MemoryWorkerClosedError):
        await worker.run(lambda connection: connection.execute("SELECT 1").fetchone()[0])
