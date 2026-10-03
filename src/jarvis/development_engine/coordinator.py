"""Durable admission and execution coordinator for DevelopmentEngine work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from jarvis.work.resources import ResourceLeaseManager, ResourcePressure

from .admission import build_development_reasoning_fingerprint
from .contracts import (
    DevelopmentDisposition,
    DevelopmentResultV1,
    DevelopmentTicketV1,
)
from .protocol import DevelopmentEngine, DevelopmentToolPort
from .session_store import DevelopmentSessionStore


@dataclass(frozen=True, slots=True)
class DevelopmentCoordinationResult:
    """One admitted or durably reused engineering outcome."""

    result: DevelopmentResultV1
    reasoning_fingerprint: str
    reused: bool


class DevelopmentEngineCoordinator:
    """Admit expensive engineering intelligence only when canonical facts changed."""

    def __init__(
        self,
        *,
        engine: DevelopmentEngine,
        sessions: DevelopmentSessionStore,
        resources: ResourceLeaseManager | None = None,
        resource_keys: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(sessions, DevelopmentSessionStore):
            raise TypeError("sessions must be DevelopmentSessionStore")
        self._engine = engine
        self._sessions = sessions
        self._resources = resources
        self._resource_keys = (
            () if resources is None else resources.normalize(resource_keys)
        )

    async def execute(
        self,
        ticket: DevelopmentTicketV1,
        *,
        tools: DevelopmentToolPort,
        evidence_refs: Iterable[str] = (),
        failure_refs: Iterable[str] = (),
        tool_contract_version: int = 1,
    ) -> DevelopmentCoordinationResult:
        if not isinstance(ticket, DevelopmentTicketV1):
            raise TypeError("ticket must be DevelopmentTicketV1")

        fingerprint = build_development_reasoning_fingerprint(
            ticket,
            evidence_refs=evidence_refs,
            failure_refs=failure_refs,
            tool_contract_version=tool_contract_version,
        )
        reusable = self._sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=fingerprint,
        )
        if reusable is not None:
            return DevelopmentCoordinationResult(
                result=reusable,
                reasoning_fingerprint=fingerprint,
                reused=True,
            )

        self._sessions.begin(
            ticket=ticket,
            engine_id=self._engine.engine_id,
            engine_version=self._engine.engine_version,
            reasoning_fingerprint=fingerprint,
        )

        try:
            if self._resources is not None and self._resource_keys:
                async with self._resources.lease(self._resource_keys):
                    result = await self._engine.execute(ticket, tools=tools)
            else:
                result = await self._engine.execute(ticket, tools=tools)
        except ResourcePressure as exc:
            result = DevelopmentResultV1.create(
                ticket=ticket,
                disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
                engine_id=self._engine.engine_id,
                engine_version=self._engine.engine_version,
                summary="Development intelligence is waiting for shared capacity.",
                reason=str(exc),
                blocker_code="development_intelligence_capacity",
            )

        self._sessions.record_result(
            ticket=ticket,
            result=result,
            reasoning_fingerprint=fingerprint,
        )
        return DevelopmentCoordinationResult(
            result=result,
            reasoning_fingerprint=fingerprint,
            reused=False,
        )
