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

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_shadow import EnrolledSpeakerShadowObserver
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.memory.runtime import MemoryRuntime
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.runtime import VoiceRuntimeController

LOGGER = logging.getLogger(__name__)


class _SessionToolBundle:
    """Combine existing vision tools with per-session explicit memory tools."""

    def __init__(
        self,
        vision_tools: Any | None,
        memory_runtime: MemoryRuntime,
        conversation_getter: Callable[[], ConversationSession | None],
    ) -> None:
        self._vision_tools = vision_tools
        self._memory_runtime = memory_runtime
        self._conversation_getter = conversation_getter

    @property
    def tools(self) -> list:
        tools = list(self._vision_tools.tools) if self._vision_tools is not None else []
        conversation = self._conversation_getter()
        if conversation is not None:
            tools.extend(
                MemoryAgentTools(
                    self._memory_runtime.service,
                    conversation,
                ).tools
            )
        return tools


class CanonicalActiveSpeakerRuntimeController(VoiceRuntimeController):
    """Run CAM++ + LR-ASD shadow analysis on one canonical microphone timeline."""

    def __init__(
        self,
        *args: Any,
        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,
        memory_runtime: MemoryRuntime | None = None,
        **kwargs: Any,
    ) -> None:
        original_session_factory = kwargs.pop("session_factory", create_voice_session)
        self._memory_conversation: ConversationSession | None = None

        def capture_session(config: JarvisConfig):
            session, bridge = original_session_factory(config)
            self._memory_conversation = bridge.conversation
            return session, bridge

        super().__init__(*args, session_factory=capture_session, **kwargs)
        self._speaker_shadow_observer = speaker_shadow_observer
        self._memory_runtime = memory_runtime
        if memory_runtime is not None:
            self._vision_tools = _SessionToolBundle(
                self._vision_tools,
                memory_runtime,
                lambda: self._memory_conversation,
            )

    async def run(self) -> None:
        memory_runtime = self._memory_runtime
        if memory_runtime is None:
            await super().run()
            return

        await memory_runtime.start()
        LOGGER.info(
            "JARVIS explicit persistent memory is active; implicit admission remains disabled"
        )
        try:
            await super().run()
        finally:
            self._memory_conversation = None
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
        # Historical paired-audio callers are intentionally ignored in this
        # production specialization. ADR-013 establishes one Pocket3 mic owner.
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
