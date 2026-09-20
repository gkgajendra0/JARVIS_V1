"""Deterministic resource leases for concurrent JARVIS WorkItems."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psutil


class ResourcePressure(RuntimeError):
    """Physical resource pressure prevents a new bounded work step from starting."""


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    key: str
    capacity: int
    available: int


class ResourceLeaseManager:
    """Bound local concurrency without making resource ownership an LLM decision."""

    def __init__(
        self,
        capacities: Mapping[str, int] | None = None,
        *,
        min_available_memory_mb: int = 0,
        available_memory_bytes: Callable[[], int] | None = None,
    ) -> None:
        normalized = dict(capacities or {"cpu": 2, "git": 1, "network": 4})
        if not normalized:
            raise ValueError("resource capacities must not be empty")
        if isinstance(min_available_memory_mb, bool) or min_available_memory_mb < 0:
            raise ValueError("minimum available memory must be a non-negative integer")
        self._min_available_memory_bytes = int(min_available_memory_mb) * 1024 * 1024
        self._available_memory_bytes = available_memory_bytes or (
            lambda: int(psutil.virtual_memory().available)
        )
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
        normalized = tuple(
            sorted({str(key).strip().casefold() for key in keys if str(key).strip()})
        )
        unknown = [key for key in normalized if key not in self._semaphores]
        if unknown:
            raise ValueError(f"unknown work resources: {unknown}")
        return normalized

    def _check_memory_pressure(self, keys: tuple[str, ...]) -> None:
        if self._min_available_memory_bytes <= 0:
            return
        if not {"work", "cpu", "gpu"}.intersection(keys):
            return
        available = int(self._available_memory_bytes())
        if available < self._min_available_memory_bytes:
            available_mb = max(0, available // (1024 * 1024))
            required_mb = self._min_available_memory_bytes // (1024 * 1024)
            raise ResourcePressure(
                f"available memory {available_mb} MiB is below the "
                f"{required_mb} MiB safety floor"
            )

    @asynccontextmanager
    async def lease(self, keys: tuple[str, ...]) -> AsyncIterator[tuple[str, ...]]:
        normalized = self.normalize(keys)
        acquired: list[asyncio.Semaphore] = []
        try:
            self._check_memory_pressure(normalized)
            for key in normalized:
                semaphore = self._semaphores[key]
                await semaphore.acquire()
                acquired.append(semaphore)
            self._check_memory_pressure(normalized)
            yield normalized
        finally:
            for semaphore in reversed(acquired):
                semaphore.release()

    def snapshot(self) -> tuple[ResourceSnapshot, ...]:
        return tuple(
            ResourceSnapshot(
                key=key,
                capacity=self._capacity[key],
                available=semaphore._value,
            )
            for key, semaphore in sorted(self._semaphores.items())
        )
