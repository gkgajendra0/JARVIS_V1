"""Deterministic resource leases for concurrent JARVIS WorkItems."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Mapping


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    key: str
    capacity: int
    available: int


class ResourceLeaseManager:
    """Bound local concurrency without making resource ownership an LLM decision."""

    def __init__(self, capacities: Mapping[str, int] | None = None) -> None:
        normalized = dict(capacities or {"cpu": 2, "git": 1, "network": 4})
        if not normalized:
            raise ValueError("resource capacities must not be empty")
        self._capacity: dict[str, int] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        for raw_key, raw_capacity in normalized.items():
            key = str(raw_key).strip().casefold()
            if not key:
                raise ValueError("resource key must not be empty")
            if isinstance(raw_capacity, bool) or int(raw_capacity) <= 0:
                raise ValueError(f"resource capacity must be positive: {key}")
            capacity = int(raw_capacity)
            self._capacity[key] = capacity
            self._semaphores[key] = asyncio.Semaphore(capacity)

    def normalize(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({str(key).strip().casefold() for key in keys if str(key).strip()}))
        unknown = [key for key in normalized if key not in self._semaphores]
        if unknown:
            raise ValueError(f"unknown work resources: {unknown}")
        return normalized

    @asynccontextmanager
    async def lease(self, keys: tuple[str, ...]) -> AsyncIterator[tuple[str, ...]]:
        normalized = self.normalize(keys)
        acquired: list[asyncio.Semaphore] = []
        try:
            for key in normalized:
                semaphore = self._semaphores[key]
                await semaphore.acquire()
                acquired.append(semaphore)
            yield normalized
        finally:
            for semaphore in reversed(acquired):
                semaphore.release()

    def snapshot(self) -> tuple[ResourceSnapshot, ...]:
        return tuple(
            ResourceSnapshot(
                key=key,
                capacity=self._capacity[key],
                available=semaphore._value,  # noqa: SLF001 - diagnostics only
            )
            for key, semaphore in sorted(self._semaphores.items())
        )
