from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


class MemoryWorkerError(RuntimeError):
    pass


class MemoryWorkerClosedError(MemoryWorkerError):
    pass


class SerialConnectionWorker:
    """Own one DB connection on one dedicated thread and serialize all access."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        thread_name: str,
    ) -> None:
        normalized_name = thread_name.strip()
        if not normalized_name:
            raise ValueError("thread_name must not be empty")
        self._connection_factory = connection_factory
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=normalized_name,
        )
        self._connection: Any | None = None
        self._owner_thread_id: int | None = None
        self._closed = False
        self._state_lock = asyncio.Lock()

    @property
    def owner_thread_id(self) -> int | None:
        return self._owner_thread_id

    async def start(self) -> None:
        async with self._state_lock:
            if self._closed:
                raise MemoryWorkerClosedError("memory connection worker is closed")
            if self._connection is not None:
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._open_on_worker)

    async def run(self, operation: Callable[[Any], T]) -> T:
        if not callable(operation):
            raise TypeError("operation must be callable")
        await self.start()
        if self._closed:
            raise MemoryWorkerClosedError("memory connection worker is closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self._run_on_worker, operation
        )

    async def close(self) -> None:
        async with self._state_lock:
            if self._closed:
                return
            self._closed = True
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._close_on_worker)
            self._executor.shutdown(wait=True, cancel_futures=True)

    def _open_on_worker(self) -> None:
        if self._connection is not None:
            return
        self._owner_thread_id = threading.get_ident()
        self._connection = self._connection_factory()

    def _run_on_worker(self, operation: Callable[[Any], T]) -> T:
        if self._connection is None:
            raise MemoryWorkerError("memory connection worker is not started")
        if threading.get_ident() != self._owner_thread_id:
            raise MemoryWorkerError("memory database connection left its owner thread")
        return operation(self._connection)

    def _close_on_worker(self) -> None:
        if self._connection is None:
            return
        if threading.get_ident() != self._owner_thread_id:
            raise MemoryWorkerError(
                "memory database connection closed off owner thread"
            )
        self._connection.close()
        self._connection = None
