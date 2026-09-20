"""Single-brain coordination contract for persistent JARVIS work."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any, Protocol

from jarvis.work.models import WorkItem, WorkStep


@dataclass(frozen=True, slots=True)
class BrainAction:
    name: str
    description: str
    parameter_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("brain action name must not be empty")
        if not self.description.strip():
            raise ValueError("brain action description must not be empty")


@dataclass(frozen=True, slots=True)
class BrainRequest:
    work: WorkItem
    recent_steps: tuple[WorkStep, ...]
    purpose: str
    allowed_actions: tuple[BrainAction, ...]
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise ValueError("brain request purpose must not be empty")
        if not self.allowed_actions:
            raise ValueError("brain request requires at least one allowed action")
        names = [item.name for item in self.allowed_actions]
        if len(names) != len(set(names)):
            raise ValueError("brain action names must be unique")


@dataclass(frozen=True, slots=True)
class BrainDecision:
    action: str | None
    summary: str
    parameters: dict[str, Any] = field(default_factory=dict)
    goal_complete: bool = False
    needs_owner: bool = False
    owner_question: str | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("brain decision summary must not be empty")
        if self.goal_complete and self.action is not None:
            raise ValueError("completed brain decisions cannot include an action")
        if self.needs_owner:
            question = (self.owner_question or "").strip()
            if not question:
                raise ValueError("owner-waiting decision requires owner_question")
            if self.action is not None:
                raise ValueError("owner-waiting decision cannot execute an action")
        if not self.goal_complete and not self.needs_owner and self.action is None:
            raise ValueError("brain decision must act, complete, or wait for owner")


class BrainReasoner(Protocol):
    """Provider adapter boundary. Workers never receive provider clients directly."""

    async def decide(self, request: BrainRequest) -> BrainDecision: ...


class BrainPreempted(RuntimeError):
    """Interactive voice took precedence over background model reasoning."""


class InteractiveBrainGate:
    """Give live owner conversation absolute priority over background reasoning."""

    def __init__(self) -> None:
        self._interactive_active = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._background_task: asyncio.Task[BrainDecision] | None = None
        self._interactive_preempted_task: asyncio.Task[BrainDecision] | None = None

    @property
    def interactive_active(self) -> bool:
        return self._interactive_active

    async def wait_until_idle(self) -> None:
        await self._idle.wait()

    def set_interactive_active(self, active: bool) -> None:
        normalized = bool(active)
        if normalized == self._interactive_active:
            return
        self._interactive_active = normalized
        if normalized:
            self._idle.clear()
            task = self._background_task
            if (
                task is not None
                and not task.done()
                and task.cancelling() == 0
                and task.cancel()
            ):
                # Record why this exact task was cancelled. Voice state can flicker
                # back to idle before the cancellation is observed by run_background,
                # so checking the *current* interactive flag in the exception handler
                # is racy and can leak CancelledError into the durable DBOS step.
                self._interactive_preempted_task = task
        else:
            self._idle.set()

    async def run_background(
        self,
        reasoner: BrainReasoner,
        request: BrainRequest,
    ) -> BrainDecision:
        await self.wait_until_idle()
        if self._interactive_active:
            raise BrainPreempted("interactive voice brain has priority")
        task = asyncio.create_task(
            reasoner.decide(request),
            name=f"jarvis-background-brain-{request.work.work_id}",
        )
        self._background_task = task
        try:
            return await task
        except asyncio.CancelledError as exc:
            if self._interactive_preempted_task is task:
                raise BrainPreempted(
                    "background reasoning was preempted by interactive voice"
                ) from exc
            raise
        finally:
            if self._background_task is task:
                self._background_task = None
            if self._interactive_preempted_task is task:
                self._interactive_preempted_task = None


class BrainCoordinator:
    """Serialize reasoning through one priority-aware JARVIS brain lease.

    Voice has absolute priority through the interactive gate. Deterministic background
    execution may continue concurrently, but provider reasoning is preempted whenever
    the owner is speaking or the live agent is thinking/speaking.
    """

    def __init__(
        self,
        reasoner: BrainReasoner,
        *,
        interactive_gate: InteractiveBrainGate | None = None,
    ) -> None:
        self._reasoner = reasoner
        self._interactive_gate = interactive_gate or InteractiveBrainGate()
        self._busy = False
        self._sequence = itertools.count()
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def interactive_gate(self) -> InteractiveBrainGate:
        return self._interactive_gate

    async def _acquire(self, request: BrainRequest) -> None:
        if not self._busy:
            self._busy = True
            return
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        heapq.heappush(
            self._waiters,
            (-int(request.work.priority), next(self._sequence), waiter),
        )
        try:
            await waiter
        except asyncio.CancelledError:
            waiter.cancel()
            raise

    def _release(self) -> None:
        while self._waiters:
            _, _, waiter = heapq.heappop(self._waiters)
            if waiter.cancelled():
                continue
            waiter.set_result(None)
            return
        self._busy = False

    async def decide(self, request: BrainRequest) -> BrainDecision:
        await self._acquire(request)
        try:
            decision = await self._interactive_gate.run_background(
                self._reasoner,
                request,
            )
            allowed = {item.name for item in request.allowed_actions}
            if decision.action is not None and decision.action not in allowed:
                raise ValueError(
                    f"brain selected action outside JARVIS allowance: {decision.action}"
                )
            return decision
        finally:
            self._release()
