"""Active-speaker diagnostics using the canonical LiveKit conversation PCM.

This controller deliberately does not open a second microphone. LR-ASD reuses
bounded, timestamped user-turn PCM already observed by JARVIS and aligns it with
the existing timestamped Vision frame/track buffer.
"""

from __future__ import annotations

import asyncio
import logging

from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.voice.runtime import VoiceRuntimeController

LOGGER = logging.getLogger(__name__)


class CanonicalActiveSpeakerRuntimeController(VoiceRuntimeController):
    """Run speaker + LR-ASD shadow analysis on one canonical microphone timeline."""

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
                    "live_owner_context=%s | active_speaker_confirmed=False | "
                    "prototype_admission=False | reasons=%s",
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

        await self._inspect_active_speaker_turn(
            analysis_turn,
            audio_turn_id=audio_turn_id,
            quality_accepted=quality.accepted,
        )
