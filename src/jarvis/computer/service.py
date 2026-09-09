"""Bounded orchestration for a replaceable computer-use provider."""

from __future__ import annotations

import asyncio

from .executor import ComputerExecutor
from .models import ComputerUseResult, ComputerUseStatus
from .providers import ComputerUseProvider


class ComputerUseService:
    """Serialize desktop-control sessions and return truthful structured status."""

    MAX_TASK_CHARACTERS = 4000

    def __init__(
        self,
        *,
        provider: ComputerUseProvider,
        executor: ComputerExecutor,
        max_steps: int = 8,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("computer-use max_steps must be greater than zero")
        self._provider = provider
        self._executor = executor
        self._max_steps = max_steps
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    @property
    def max_steps(self) -> int:
        return self._max_steps

    async def execute(self, task: str) -> ComputerUseResult:
        normalized = str(task).strip()
        if not normalized:
            raise ValueError("computer-use task must not be empty")
        if len(normalized) > self.MAX_TASK_CHARACTERS:
            raise ValueError("computer-use task exceeds bounded input limit")

        async with self._lock:
            try:
                return await self._provider.execute(
                    normalized,
                    executor=self._executor,
                    max_steps=self._max_steps,
                )
            except Exception as exc:  # noqa: BLE001 - provider SDK errors vary.
                return ComputerUseResult(
                    status=ComputerUseStatus.FAILED,
                    provider=self.provider_name,
                    model=self.model_name,
                    steps=0,
                    reason=f"{type(exc).__name__}: {exc}",
                )
