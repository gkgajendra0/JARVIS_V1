"""Initial bounded work executors built from existing JARVIS capabilities."""

from __future__ import annotations

from typing import Any

from jarvis.knowledge.research import CurrentResearchService, ResearchMode
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
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(self, service: CurrentResearchService) -> None:
        self._service = service

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work
        query = str(parameters.get("query") or "").strip()
        if not query:
            raise ValueError("research_web requires query")
        mode = ResearchMode.parse(str(parameters.get("mode") or "current"))
        result = await self._service.research(query, mode=mode)
        return result.to_tool_payload()
