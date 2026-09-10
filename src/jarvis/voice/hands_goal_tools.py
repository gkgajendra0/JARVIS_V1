"""Single voice-facing handoff to the mature JARVIS Hands orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator
from jarvis.hands.planner import HandsPlanningError
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator
from jarvis.voice.hands_transaction import (
    HandsGoalSuperseded,
    LeaseAwareCapabilityRuntime,
    LeaseAwareHandsPlanner,
)

LOGGER = logging.getLogger(__name__)

_TRANSCRIPT_WAIT_SECONDS = 4.0
_TRANSCRIPT_POLL_SECONDS = 0.02
_VOICE_RESULT_DATA_CHARACTERS = 4_000

# Compatibility alias for older imports/tests while the implementation is no longer a
# phrase/keyword grounding parser.
HandsGoalGroundingError = HandsOrchestrationError


def _bounded_voice_data(value: object) -> object:
    """Keep useful final evidence without injecting the full Hands trace into Realtime."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) <= _VOICE_RESULT_DATA_CHARACTERS:
        return value
    return {
        "truncated": True,
        "preview": encoded[:_VOICE_RESULT_DATA_CHARACTERS],
    }


def _compact_voice_result(result: dict[str, object]) -> dict[str, object]:
    """Return only decision-relevant Hands evidence to the conversational model.

    The full orchestration trace remains available to JARVIS logs/tests. Sending every
    UIA observation and intermediate result back into a Realtime session needlessly
    consumes token bandwidth and can trigger provider token-rate limits. The voice model
    needs status, clarification/failure context and the final observed machine state.
    """

    compact: dict[str, object] = {}
    for key in (
        "ok",
        "status",
        "completed_steps",
        "failed_operation",
        "reason",
        "clarification_question",
        "canonical_user_turn_id",
    ):
        if key in result and result[key] is not None:
            compact[key] = result[key]

    results = result.get("results")
    if isinstance(results, list) and results:
        final = results[-1]
        if isinstance(final, dict):
            compact["final_result"] = {
                key: _bounded_voice_data(value) if key == "data" else value
                for key, value in final.items()
                if key in {"ok", "status", "operation", "capability", "data", "reason"}
                and value is not None
            }

    observations = result.get("observations")
    if isinstance(observations, list) and observations:
        final_observation = observations[-1]
        if isinstance(final_observation, dict):
            compact["final_observation"] = {
                key: _bounded_voice_data(value) if key == "data" else value
                for key, value in final_observation.items()
                if key in {"operation", "status", "ok", "verified", "reason", "data"}
                and value is not None
            }
    return compact


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
                    raise HandsGoalSuperseded(
                        "duplicate Hands tool call for this USER utterance was ignored"
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
        return VoiceHandsOrchestrator(
            LeaseAwareCapabilityRuntime(self._runtime, is_current),
            LeaseAwareHandsPlanner(planner, is_current),
        )

    @staticmethod
    def _superseded_result(reason: str) -> dict[str, object]:
        return {
            "ok": False,
            "status": "superseded",
            "reason": reason,
        }

    async def execute_goal(self) -> dict[str, object]:
        try:
            turn, generation = await self._claim_current_user_turn()
        except HandsGoalSuperseded as exc:
            LOGGER.info("Hands voice lease ignored before claim: %s", exc)
            return self._superseded_result(str(exc))

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
                result = self._superseded_result(
                    "a newer USER utterance replaced this computer goal"
                )
                result["goal"] = turn.text
                result["canonical_user_turn_id"] = turn.turn_id
                return result
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
                result = self._superseded_result(str(exc))
                result["goal"] = turn.text
                result["canonical_user_turn_id"] = turn.turn_id
                return result
        result["canonical_user_turn_id"] = turn.turn_id
        return result

    @function_tool()
    async def use_computer(self, context: RunContext) -> dict[str, object]:
        """Hand the current accepted USER computer goal to JARVIS Hands.

        Call this whenever the USER asks JARVIS to operate OR inspect the local computer.
        Questions about what is visible, open, written, selected, listed or displayed
        inside a desktop app/window/screen belong here. Do not refuse those questions
        because the Pocket3 camera cannot read the monitor; physical-camera vision and
        desktop UI inspection are separate capabilities.

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
            return _compact_voice_result(await self.execute_goal())
        except (
            HandsOrchestrationError,
            HandsPlanningError,
            TypeError,
            ValueError,
        ) as exc:
            raise ToolError(str(exc)) from exc
