"""Bounded multi-capability workflow runner for JARVIS Hands."""

from __future__ import annotations

from typing import Protocol

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityResult

from .models import HandsWorkflowResult, HandsWorkflowStep
from .registry import HandsCapabilityRegistry


class CapabilityRuntimeLike(Protocol):
    def execute_operation(
        self,
        *,
        session_id: str,
        operation: str,
        parameters: dict,
        origin: ActionOrigin = ActionOrigin.DIRECT_USER,
    ) -> CapabilityResult: ...


class HandsWorkflowRunner:
    """Execute a short fail-stop workflow through the canonical capability runtime.

    This runner never grants authority itself. Every step is independently prepared,
    authorized, permit-revalidated, executed, verified by its executor, and audited by
    CapabilityRuntime.
    """

    MAX_STEPS = 8

    def __init__(
        self,
        runtime: CapabilityRuntimeLike,
        *,
        registry: HandsCapabilityRegistry | None = None,
    ) -> None:
        self._runtime = runtime
        self._registry = registry or HandsCapabilityRegistry.default()

    def execute(
        self,
        *,
        session_id: str,
        steps: tuple[HandsWorkflowStep, ...],
        origin: ActionOrigin = ActionOrigin.DIRECT_USER,
    ) -> HandsWorkflowResult:
        if not steps:
            raise ValueError("hands workflow must contain at least one step")
        if len(steps) > self.MAX_STEPS:
            raise ValueError(f"hands workflow exceeds {self.MAX_STEPS} steps")

        results: list[CapabilityResult] = []
        for step in steps:
            self._registry.require(step.operation)
            result = self._runtime.execute_operation(
                session_id=session_id,
                operation=step.operation,
                parameters=dict(step.parameters),
                origin=origin,
            )
            results.append(result)
            if not result.ok:
                return HandsWorkflowResult(
                    ok=False,
                    completed_steps=len(results) - 1,
                    results=tuple(results),
                    failed_operation=step.operation,
                    reason=result.reason or result.status.value,
                )

        return HandsWorkflowResult(
            ok=True,
            completed_steps=len(results),
            results=tuple(results),
        )
