"""Runtime ownership for the encrypted canonical JARVIS memory service."""

from __future__ import annotations

from pathlib import Path

from jarvis.machine_config import default_machine_config_path
from jarvis.security import WindowsDpapiKeyProtector

from .database import SqlCipherMemoryDatabaseFactory
from .lifecycle import MemoryLifecycleService
from .query import CanonicalMemoryReader
from .service import MemoryService
from .worker import SerialConnectionWorker


def default_memory_database_path() -> Path:
    """Return the canonical per-machine memory database location."""

    return default_machine_config_path().parent / "memory.db"


class MemoryRuntime:
    """Own the writer/reader workers behind one public MemoryService."""

    def __init__(
        self,
        service: MemoryService,
        *,
        writer: SerialConnectionWorker,
        reader: SerialConnectionWorker,
    ) -> None:
        if not isinstance(service, MemoryService):
            raise TypeError("service must be a MemoryService")
        self.service = service
        self._writer = writer
        self._reader = reader
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("memory runtime is closed")
        if self._started:
            return
        try:
            await self._writer.start()
            await self._reader.start()
        except BaseException:
            await self._reader.close()
            await self._writer.close()
            self._closed = True
            raise
        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._reader.close()
        await self._writer.close()


def build_default_memory_runtime(
    database_path: str | Path | None = None,
) -> MemoryRuntime:
    """Build the fail-closed Windows SQLCipher + DPAPI memory runtime."""

    resolved_path = (
        Path(database_path) if database_path is not None else default_memory_database_path()
    )
    factory = SqlCipherMemoryDatabaseFactory(
        resolved_path,
        key_protector=WindowsDpapiKeyProtector(),
    )
    writer = SerialConnectionWorker(
        factory.open,
        thread_name="jarvis-memory-writer",
    )
    reader = SerialConnectionWorker(
        factory.open,
        thread_name="jarvis-memory-reader",
    )
    lifecycle = MemoryLifecycleService(writer)
    service = MemoryService(lifecycle, CanonicalMemoryReader(reader))
    return MemoryRuntime(service, writer=writer, reader=reader)
