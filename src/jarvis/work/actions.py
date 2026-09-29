"""Initial bounded work executors built from existing JARVIS capabilities."""

from __future__ import annotations

import uuid
from typing import Any

from jarvis.knowledge.research import CurrentResearchService, ResearchMode
from jarvis.model_routing.cost import ProviderCostEvent, ProviderCostEventStore
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType


class ResearchWorkExecutor:
    descriptor = BrainAction(
        name="research_web",
        description=(
            "Retrieve current web evidence through JARVIS CurrentResearchService. "
            "Use parameters query:string and mode:current|fact_check|authoritative."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 600},
                "mode": {
                    "type": "string",
                    "enum": ["current", "fact_check", "authoritative"],
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.RESEARCH, WorkType.DIAGNOSTICS})

    def __init__(
        self,
        service: CurrentResearchService,
        *,
        cost_store: ProviderCostEventStore | None = None,
    ) -> None:
        self._service = service
        self._cost_store = cost_store

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("network",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        query = str(parameters.get("query") or "").strip()
        if not query:
            raise ValueError("research_web requires query")
        mode = ResearchMode.parse(str(parameters.get("mode") or "current"))
        result = await self._service.research(query, mode=mode)
        if self._cost_store is not None:
            for estimate in self._service.cost_estimates(result):
                self._cost_store.record(
                    ProviderCostEvent(
                        event_id=f"provider_cost_{uuid.uuid4().hex}",
                        work_id=work.work_id,
                        provider_id=result.provider,
                        service_key=estimate.service_key,
                        cost_kind=estimate.cost_kind,
                        quantity=estimate.quantity,
                        unit_cost_usd=estimate.unit_cost_usd,
                        estimated_cost_usd=estimate.estimated_cost_usd,
                        pricing_basis=estimate.pricing_basis,
                        occurred_at_epoch=result.researched_at.timestamp(),
                        stage_key="research",
                    )
                )
        return result.to_tool_payload()
