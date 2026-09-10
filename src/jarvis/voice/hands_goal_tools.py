"""Single voice-facing handoff to the mature JARVIS Hands orchestrator."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator
from jarvis.hands.planner import HandsPlanningError

# Compatibility alias for older imports/tests while the implementation is no longer a
# phrase/keyword grounding parser.
HandsGoalGroundingError = HandsOrchestrationError


class HandsGoalAgentTools:
    """Hand the canonical USER goal to Hands; the realtime model never builds plans."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        conversation: ConversationSession,
        *,
        orchestrator: HandsOrchestrator | None = None,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._runtime = runtime
        self._conversation = conversation
        self._orchestrator = orchestrator

    @property
    def tools(self) -> list:
        return [self.use_computer]

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
            raise HandsOrchestrationError(
                "JARVIS Hands requires a latest accepted USER utterance"
            )
        return turn

    def _recent_user_turns(self, latest: ConversationTurn) -> tuple[str, ...]:
        users = [
            turn.text
            for turn in self._conversation.turns
            if turn.role is ConversationRole.USER and turn.turn_id != latest.turn_id
        ]
        return tuple(users[-6:])

    def _get_orchestrator(self) -> HandsOrchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        planner = self._runtime.hands_planner
        if planner is None:
            raise HandsOrchestrationError(
                "JARVIS Hands semantic planner is not configured"
            )
        self._orchestrator = HandsOrchestrator(self._runtime, planner)
        return self._orchestrator

    async def execute_goal(self) -> dict[str, object]:
        turn = self._latest_user_turn()
        result = await self._get_orchestrator().execute_goal(
            session_id=self._conversation.session_id,
            goal=turn.text,
            recent_user_turns=self._recent_user_turns(turn),
        )
        result["canonical_user_turn_id"] = turn.turn_id
        return result

    @function_tool()
    async def use_computer(self, context: RunContext) -> dict[str, object]:
        """Hand the latest accepted USER computer goal to JARVIS Hands.

        Call this whenever the USER asks JARVIS to operate or inspect the local computer.
        Do not construct capability names, operation plans, selectors, app IDs, package IDs,
        or execution parameters yourself. This tool takes no plan arguments: JARVIS Hands
        internally performs semantic routing, canonical entity resolution, strongly typed
        planning, proportional Authority, verified execution, and bounded recovery.

        If the result has status ``clarification_required``, ask the returned clarification
        question. Otherwise treat the tool result as authoritative and never claim success
        for denied, failed, unavailable, or unverified work.
        """
        del context
        try:
            return await self.execute_goal()
        except (
            HandsOrchestrationError,
            HandsPlanningError,
            TypeError,
            ValueError,
        ) as exc:
            raise ToolError(str(exc)) from exc
