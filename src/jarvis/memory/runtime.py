"""Runtime ownership for the encrypted canonical JARVIS memory service."""

from __future__ import annotations

from pathlib import Path

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.machine_config import default_machine_config_path
from jarvis.security import WindowsDpapiKeyProtector

from .conversation_checkpoint import EncryptedTopicCheckpointStore
from .database import SqlCipherMemoryDatabaseFactory
from .lifecycle import MemoryLifecycleService
from .query import CanonicalMemoryReader
from .retrieval import SemanticRetrievalService
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
        self.retrieval = SemanticRetrievalService(reader)
        # No separate connection or key: checkpoints share canonical SQLCipher workers.
        self.topic_checkpoints = EncryptedTopicCheckpointStore(
            writer=writer, reader=reader
        )
        self._writer = writer
        self._reader = reader
        # None means fail closed; no voice callback may guess a generation.
        self._plan_epoch: int | None = None
        self.service.bind_plan_epoch_refresher(self._refresh_plan_epoch)
        self._started = False
        self._closed = False

    def bind_learning_authority(self, authority):
        self.service.bind_learning_authority(authority)

    def accepted_plan_epoch(self, turn: ConversationTurn) -> int:
        """Synchronous O(1) epoch capture for an accepted canonical USER turn."""
        if (
            self._closed
            or not self._started
            or not isinstance(turn, ConversationTurn)
            or turn.role is not ConversationRole.USER
            or self._plan_epoch is None
        ):
            raise PermissionError("trusted plan epoch unavailable")
        return self._plan_epoch

    async def _refresh_plan_epoch(self) -> None:
        self._plan_epoch = None
        try:
            suppression = await self.service.learning_suppression()
            version = suppression.epochs.get("plan", 0)
            if type(version) is not int or version < 0:
                raise RuntimeError("canonical plan suppression epoch invalid")
        except BaseException:
            self._plan_epoch = None
            raise
        self._plan_epoch = version

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("memory runtime is closed")
        if self._started:
            return
        try:
            await self._writer.start()
            await self._reader.start()
            await self._refresh_plan_epoch()
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
        self._plan_epoch = None
        await self._reader.close()
        await self._writer.close()


def build_default_memory_runtime(
    database_path: str | Path | None = None,
) -> MemoryRuntime:
    """Build the fail-closed Windows SQLCipher + DPAPI memory runtime."""

    resolved_path = (
        Path(database_path)
        if database_path is not None
        else default_memory_database_path()
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
