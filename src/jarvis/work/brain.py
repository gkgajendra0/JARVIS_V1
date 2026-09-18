"""Single-brain coordination contract for persistent JARVIS work."""

from __future__ import annotations

import asyncio
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


class BrainCoordinator:
    """Serialize background reasoning through JARVIS's one configured active brain.

    Background I/O and deterministic execution may run concurrently. Model reasoning is
    intentionally leased through this coordinator so independent work items cannot become
    independent provider-owned brains.
    """

    def __init__(self, reasoner: BrainReasoner) -> None:
        self._reasoner = reasoner
        self._lease = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lease.locked()

    async def decide(self, request: BrainRequest) -> BrainDecision:
        async with self._lease:
            decision = await self._reasoner.decide(request)
        allowed = {item.name for item in request.allowed_actions}
        if decision.action is not None and decision.action not in allowed:
            raise ValueError(
                f"brain selected action outside JARVIS allowance: {decision.action}"
            )
        return decision
