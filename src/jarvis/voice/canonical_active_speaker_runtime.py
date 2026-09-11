"""Canonical user-PCM speaker and active-speaker shadow diagnostics.

The controller keeps speaker identity off the conversation critical path. Each
committed user turn is already submitted as a background task by VoiceRuntimeController;
this specialization trims the canonical PCM once, scores an enrolled CAM++ OWNER
voice template when available, and runs LR-ASD in parallel when enabled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.config import JarvisConfig
from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
)
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_shadow import EnrolledSpeakerShadowObserver
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.knowledge.research import CurrentResearchService
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.runtime import MemoryRuntime
from jarvis.voice.capability_tools import LocalReadAgentTools
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.research_tools import ResearchAgentTools
from jarvis.voice.runtime import VoiceRuntimeController

LOGGER = logging.getLogger(__name__)


class _SessionToolBundle:
    """Combine vision with per-session memory, research, and governed capabilities."""

    def __init__(
        self,
        vision_tools: Any | None,
        conversation_getter: Callable[[], ConversationSession | None],
        *,
        memory_runtime: MemoryRuntime | None,
        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None,
        research_service: CurrentResearchService | None,
        capability_runtime: CapabilityRuntime | None,
    ) -> None:
        self._vision_tools = vision_tools
        self._conversation_getter = conversation_getter
        self._memory_runtime = memory_runtime
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._capability_runtime = capability_runtime

    @property
    def tools(self) -> list:
        tools = list(self._vision_tools.tools) if self._vision_tools is not None else []
        conversation = self._conversation_getter()
        if conversation is None:
            return tools
        if self._memory_runtime is not None:
            tools.extend(
                MemoryAgentTools(
                    self._memory_runtime.service,
                    conversation,
                    semantic_query_coordinator=self._memory_query_coordinator,
                ).tools
            )
        if self._research_service is not None:
            tools.extend(ResearchAgentTools(self._research_service, conversation).tools)
        if self._capability_runtime is not None:
            tools.extend(
                LocalReadAgentTools(self._capability_runtime, conversation).tools
            )
        return tools


class CanonicalActiveSpeakerRuntimeController(VoiceRuntimeController):
    """Run CAM++ + LR-ASD shadow analysis on one canonical microphone timeline."""

    def __init__(
        self,
        *args: Any,
        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,
        memory_runtime: MemoryRuntime | None = None,
        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None = None,
        research_service: CurrentResearchService | None = None,
        capability_runtime: CapabilityRuntime | None = None,
        **kwargs: Any,
    ) -> None:
        original_session_factory = kwargs.pop("session_factory", create_voice_session)
        self._session_conversation: ConversationSession | None = None
        self._user_is_speaking = False
        self._session_ready_for_inactivity = False

        def capture_session(config: JarvisConfig):
            session, bridge = original_session_factory(config)
            self._session_conversation = bridge.conversation
            self._user_is_speaking = False
            self._session_ready_for_inactivity = False

            def track_agent_state(event: AgentStateChangedEvent) -> None:
                LOGGER.info(
                    "Voice agent state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if self._session_ready_for_inactivity:
                    return
                if event.new_state != "listening":
                    return

                self._session_ready_for_inactivity = True
                if self._user_is_speaking:
                    self._cancel_timeout()
                    return
                self._arm_timeout(config.initial_request_timeout_seconds)

            def track_user_activity(event: UserStateChangedEvent) -> None:
                LOGGER.info(
                    "Voice user state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if event.new_state == "speaking":
                    if bridge.conversation.status is ConversationStatus.ACTIVE:
                        bridge.conversation.begin_user_utterance()
                    self._user_is_speaking = True
                    self._cancel_timeout()
                    return
                if event.new_state != "listening":
                    return

                self._user_is_speaking = False
                if not self._session_ready_for_inactivity:
                    return
                has_user_turn = any(
                    turn.role is ConversationRole.USER
                    for turn in bridge.conversation.turns
                )
                timeout = (
                    config.follow_up_timeout_seconds
                    if has_user_turn
                    else config.initial_request_timeout_seconds
                )
                self._arm_timeout(timeout)

            session.on("agent_state_changed", track_agent_state)
            session.on("user_state_changed", track_user_activity)
            return session, bridge

        super().__init__(*args, session_factory=capture_session, **kwargs)
        self._speaker_shadow_observer = speaker_shadow_observer
        self._memory_runtime = memory_runtime
        if memory_query_coordinator is not None and memory_runtime is None:
            raise ValueError(
                "memory_query_coordinator requires an active memory runtime"
            )
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._capability_runtime = capability_runtime
        if (
            memory_runtime is not None
            or research_service is not None
            or capability_runtime is not None
        ):
            self._vision_tools = _SessionToolBundle(
                self._vision_tools,
                lambda: self._session_conversation,
                memory_runtime=memory_runtime,
                memory_query_coordinator=memory_query_coordinator,
                research_service=research_service,
                capability_runtime=capability_runtime,
            )

    def _arm_timeout(self, seconds: float) -> None:
        """Arm inactivity shutdown only after startup and only while user is silent."""

        if not self._session_ready_for_inactivity or self._user_is_speaking:
            self._cancel_timeout()
            return

        self._cancel_timeout()
        active_end = self._active_end
        if active_end is None:
            return

        def expire_inactivity() -> None:
            LOGGER.info(
                "Voice session inactivity timeout expired | seconds=%.2f | "
                "user_speaking=%s | canonical_user_turns=%s",
                seconds,
                self._user_is_speaking,
                (
                    sum(
                        turn.role is ConversationRole.USER
                        for turn in self._session_conversation.turns
                    )
                    if self._session_conversation is not None
                    else 0
                ),
            )
            active_end.set()

        self._timeout_handle = asyncio.get_running_loop().call_later(
            seconds,
            expire_inactivity,
        )

    async def run(self) -> None:
        memory_runtime = self._memory_runtime
        capability_runtime = self._capability_runtime
        if memory_runtime is not None:
            await memory_runtime.start()
            LOGGER.info(
                "JARVIS explicit persistent memory is active; implicit admission remains disabled"
            )
            if self._memory_query_coordinator is not None:
                LOGGER.warning(
                    "Bounded provider-assisted semantic recall is active | provider=%s | "
                    "model=%s | final semantic verification is probabilistic and fail-closed",
                    self._memory_query_coordinator.provider_name,
                    self._memory_query_coordinator.model_name,
                )
        if self._research_service is not None:
            LOGGER.info(
                "Step-6 web research tool is active | search_provider=%s | "
                "active_brain_independent=True",
                self._research_service.provider_name,
            )
        if capability_runtime is not None:
            capability_catalog = capability_runtime.refresh_catalog()
            browser_hands = capability_catalog.by_key("browser:playwright")
            LOGGER.info(
                "Governed local capabilities are active | local_reads=True | "
                "structured_desktop_control=True | visual_fallback=owner_opt_in | "
                "browser_control=%s | raw_shell=False",
                bool(browser_hands and browser_hands.execution_enabled),
            )
        try:
            await super().run()
        finally:
            self._session_ready_for_inactivity = False
            self._user_is_speaking = False
            self._session_conversation = None
            if capability_runtime is not None:
                capability_runtime.close()
            if self._research_service is not None:
                await self._research_service.close()
            if memory_runtime is not None:
                await memory_runtime.close()

    async def _score_enrolled_speaker(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
    ) -> None:
        observer = self._speaker_shadow_observer
        if observer is None:
            return
        try:
            result = await asyncio.to_thread(
                observer.score,
                turn.samples,
                sample_rate=turn.sample_rate,
            )
        except Exception:
            LOGGER.exception(
                "Enrolled speaker shadow turn %s failed; conversation is unaffected",
                audio_turn_id,
            )
            return
        LOGGER.info(
            "Enrolled speaker shadow turn %s | state=%s | max_owner_cosine=%s | "
            "embedding_ms=%.1f | threshold_selected=False | owner_classification=False | "
            "authority_effect=False | reasons=%s",
            audio_turn_id,
            result.state,
            (
                f"{result.max_reference_cosine:.4f}"
                if result.max_reference_cosine is not None
                else "n/a"
            ),
            result.embedding_ms,
            ",".join(result.reason_codes) if result.reason_codes else "none",
        )

    async def _inspect_shadow_turn(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
        active_speaker_turn: SpeakerTurnAudio | None = None,
    ) -> None:
        del active_speaker_turn

        analysis_turn = turn
        speech_segments = 0
        speech_detector = self._speech_region_detector
        if speech_detector is not None:
            region = await speech_detector.extract(turn)
            speech_segments = region.segment_count
            if region.turn is None:
                owner_context_live = bool(
                    self._owner_context_state is not None
                    and self._owner_context_state.has_fresh_live_owner_candidate()
                )
                LOGGER.info(
                    "Speaker shadow turn %s | source=canonical_livekit_pcm | "
                    "captured=%.2fs | speech=none | accepted=False | "
                    "live_owner_context=%s | enrolled_speaker_scored=False | "
                    "active_speaker_confirmed=False | prototype_admission=False | "
                    "reasons=%s",
                    audio_turn_id,
                    turn.duration_seconds,
                    owner_context_live,
                    region.reason,
                )
                return
            analysis_turn = region.turn

        quality = await asyncio.to_thread(
            assess_speaker_segment,
            analysis_turn.samples,
            sample_rate=analysis_turn.sample_rate,
        )
        owner_context_live = bool(
            self._owner_context_state is not None
            and self._owner_context_state.has_fresh_live_owner_candidate()
        )
        LOGGER.info(
            "Speaker shadow turn %s | source=canonical_livekit_pcm | captured=%.2fs | "
            "speech=%.2fs | segments=%s | rms %.1f dBFS | accepted=%s | "
            "live_owner_context=%s | active_speaker_confirmed=False | "
            "prototype_admission=False | reasons=%s",
            audio_turn_id,
            turn.duration_seconds,
            analysis_turn.duration_seconds,
            speech_segments,
            quality.rms_dbfs,
            quality.accepted,
            owner_context_live,
            ",".join(quality.reason_codes) if quality.reason_codes else "none",
        )

        tasks = [
            self._inspect_active_speaker_turn(
                analysis_turn,
                audio_turn_id=audio_turn_id,
                quality_accepted=quality.accepted,
            )
        ]
        if quality.accepted and self._speaker_shadow_observer is not None:
            tasks.append(
                self._score_enrolled_speaker(
                    analysis_turn,
                    audio_turn_id=audio_turn_id,
                )
            )
        elif self._speaker_shadow_observer is not None:
            LOGGER.info(
                "Enrolled speaker shadow turn %s | state=insufficient | "
                "threshold_selected=False | owner_classification=False | "
                "authority_effect=False | reasons=speaker_quality_rejected",
                audio_turn_id,
            )
        await asyncio.gather(*tasks)
