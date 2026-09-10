"""Single voice-facing handoff to the mature JARVIS Hands orchestrator."""

from __future__ import annotations

import asyncio
import logging

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator
from jarvis.hands.planner import HandsPlanningError
from jarvis.voice.hands_transaction import (
    HandsGoalSuperseded,
    LeaseAwareCapabilityRuntime,
    LeaseAwareHandsPlanner,
)

LOGGER = logging.getLogger(__name__)

_TRANSCRIPT_WAIT_SECONDS = 4.0
_TRANSCRIPT_POLL_SECONDS = 0.02

# Compatibility alias for older imports/tests while the implementation is no longer a
# phrase/keyword grounding parser.
HandsGoalGroundingError = HandsOrchestrationError


class HandsGoalAgentTools:
    """Hand one canonical USER goal at a time to the governed Hands orchestrator."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        conversation: ConversationSession,
        *,
        orchestrator: HandsOrchestrator | None = None,
        transcript_wait_seconds: float = _TRANSCRIPT_WAIT_SECONDS,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        if transcript_wait_seconds <= 0:
            raise ValueError("transcript_wait_seconds must be positive")
        self._runtime = runtime
        self._conversation = conversation
        self._orchestrator = orchestrator
        self._transcript_wait_seconds = float(transcript_wait_seconds)
        self._claimed_user_generations: set[int] = set()
        self._execution_lock = asyncio.Lock()

    @property
    def tools(self) -> list:
        return [self.use_computer]

    def _turn_for_generation(self, generation: int) -> ConversationTurn | None:
        return next(
            (
                candidate
                for candidate in reversed(self._conversation.turns)
                if candidate.role is ConversationRole.USER
                and candidate.user_utterance_generation == generation
            ),
            None,
        )

    async def _claim_current_user_turn(self) -> tuple[ConversationTurn, int]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._transcript_wait_seconds
        generation = self._conversation.user_utterance_generation

        while generation <= 0:
            if loop.time() >= deadline:
                raise HandsOrchestrationError(
                    "JARVIS Hands timed out waiting for the current USER utterance"
                )
            await asyncio.sleep(_TRANSCRIPT_POLL_SECONDS)
            generation = self._conversation.user_utterance_generation

        while True:
            if self._conversation.user_utterance_generation != generation:
                raise HandsGoalSuperseded(
                    "Hands tool call was superseded before its canonical transcript arrived"
                )
            turn = self._turn_for_generation(generation)
            if turn is not None:
                if generation in self._claimed_user_generations:
                    raise HandsOrchestrationError(
                        "JARVIS Hands already accepted this USER utterance"
                    )
                self._claimed_user_generations.add(generation)
                LOGGER.info(
                    "Hands voice lease claimed | generation=%s | turn_id=%s",
                    generation,
                    turn.turn_id,
                )
                return turn, generation
            if loop.time() >= deadline:
                raise HandsOrchestrationError(
                    "JARVIS Hands timed out waiting for the canonical USER transcript"
                )
            await asyncio.sleep(_TRANSCRIPT_POLL_SECONDS)

    def _recent_user_turns(self, latest: ConversationTurn) -> tuple[str, ...]:
        users = [
            turn.text
            for turn in self._conversation.turns
            if turn.role is ConversationRole.USER and turn.turn_id != latest.turn_id
        ]
        return tuple(users[-6:])

    def _build_orchestrator(self, is_current) -> HandsOrchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        planner = self._runtime.hands_planner
        if planner is None:
            raise HandsOrchestrationError(
                "JARVIS Hands semantic planner is not configured"
            )
        return HandsOrchestrator(
            LeaseAwareCapabilityRuntime(self._runtime, is_current),
            LeaseAwareHandsPlanner(planner, is_current),
        )

    async def execute_goal(self) -> dict[str, object]:
        turn, generation = await self._claim_current_user_turn()

        def is_current() -> bool:
            return self._conversation.user_utterance_generation == generation

        async with self._execution_lock:
            if not is_current():
                LOGGER.info(
                    "Hands voice lease superseded before execution | generation=%s | "
                    "turn_id=%s",
                    generation,
                    turn.turn_id,
                )
                return {
                    "ok": False,
                    "status": "superseded",
                    "goal": turn.text,
                    "reason": "a newer USER utterance replaced this computer goal",
                    "canonical_user_turn_id": turn.turn_id,
                }
            try:
                result = await self._build_orchestrator(is_current).execute_goal(
                    session_id=self._conversation.session_id,
                    goal=turn.text,
                    recent_user_turns=self._recent_user_turns(turn),
                )
            except HandsGoalSuperseded as exc:
                LOGGER.info(
                    "Hands voice lease superseded during orchestration | generation=%s | "
                    "turn_id=%s",
                    generation,
                    turn.turn_id,
                )
                return {
                    "ok": False,
                    "status": "superseded",
                    "goal": turn.text,
                    "reason": str(exc),
                    "canonical_user_turn_id": turn.turn_id,
                }
        result["canonical_user_turn_id"] = turn.turn_id
        return result

    @function_tool()
    async def use_computer(self, context: RunContext) -> dict[str, object]:
        """Hand the current accepted USER computer goal to JARVIS Hands.

        Call this whenever the USER asks JARVIS to operate or inspect the local computer.
        Do not construct capability names, operation plans, selectors, app IDs, package IDs,
        or execution parameters yourself. This tool takes no plan arguments: JARVIS Hands
        internally performs semantic routing, canonical entity resolution, strongly typed
        planning, proportional Authority, verified execution, and bounded recovery.

        A realtime provider may call this before its final transcript is emitted. JARVIS
        therefore binds the call to the current speech generation and waits for the canonical
        transcript. A newer USER utterance supersedes stale planning before another action may
        start. An atomic local action that already started is allowed to finish safely. If the
        result status is ``superseded``, do not report the older goal as a failure; continue
        with the newer USER request.

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
