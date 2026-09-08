"""Voice tool for provider-neutral current web research."""

from __future__ import annotations

import logging

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.knowledge.research import CurrentResearchService, ResearchMode

LOGGER = logging.getLogger(__name__)


class ResearchToolGroundingError(ValueError):
    pass


class ResearchAgentTools:
    """Expose one read-only research tool grounded to canonical JARVIS conversation."""

    def __init__(
        self,
        service: CurrentResearchService,
        conversation: ConversationSession,
    ) -> None:
        if not isinstance(service, CurrentResearchService):
            raise TypeError("service must be a CurrentResearchService")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._service = service
        self._conversation = conversation

    @property
    def tools(self) -> list:
        return [self.research_current]

    def _latest_user_turn(self) -> ConversationTurn:
        turn = next(
            (
                candidate
                for candidate in reversed(self._conversation.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise ResearchToolGroundingError(
                "web research requires a latest accepted user utterance"
            )
        return turn

    async def research(self, *, mode: str = "current") -> dict[str, object]:
        turn = self._latest_user_turn()
        resolved_mode = ResearchMode.parse(mode)
        result = await self._service.research(turn.text, mode=resolved_mode)
        LOGGER.info(
            "Current research completed | turn_id=%s | provider=%s | model=%s | "
            "mode=%s | status=%s | sources=%s | queries=%s",
            turn.turn_id,
            result.provider,
            result.model,
            result.mode.value,
            result.status.value,
            len(result.sources),
            len(result.executed_queries),
        )
        return result.to_tool_payload()

    @function_tool()
    async def research_current(
        self,
        context: RunContext,
        mode: str = "current",
    ) -> dict[str, object]:
        """Research the latest USER question on the live web with real sources.

        Call this tool when the user explicitly asks to search, research, verify, or
        fact-check online, or when the answer materially depends on current/latest/
        recent information. The research question itself is NOT provided by you:
        JARVIS reads the latest canonical accepted USER utterance, so do not rewrite
        the user's request into a different question.

        `mode` may be `current`, `fact_check`, or `authoritative`. Use `fact_check`
        for claims that need corroboration. Use `authoritative` for high-stakes or
        specialist requests where primary/official evidence should be preferred.

        Stable explanations, writing, brainstorming, and reasoning from user-provided
        text normally do not need this tool. If the returned result has `ok=false`,
        say that live verification was insufficient/unavailable and do not present a
        stale model-only answer as if it was freshly verified. Never invent sources
        beyond the tool result.
        """
        del context
        try:
            return await self.research(mode=mode)
        except (ResearchToolGroundingError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
