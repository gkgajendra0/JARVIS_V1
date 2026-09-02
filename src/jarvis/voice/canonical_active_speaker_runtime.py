"""Canonical user-PCM speaker, overlap, and active-speaker shadow diagnostics.

The controller keeps identity diagnostics off the conversation critical path. Each
committed user turn is already submitted as a background task by VoiceRuntimeController;
this specialization runs overlap evidence on the full canonical turn, trims voiced
PCM once for CAM++/LR-ASD, and keeps every diagnostic non-authoritative.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from jarvis.identity.overlap_shadow import NativeOverlapShadowObserver
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_shadow import EnrolledSpeakerShadowObserver
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.voice.runtime import VoiceRuntimeController

LOGGER = logging.getLogger(__name__)


class CanonicalActiveSpeakerRuntimeController(VoiceRuntimeController):
    """Run CAM++, Sortformer, and LR-ASD shadow analysis on canonical microphone PCM."""

    def __init__(
        self,
        *args: Any,
        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,
        overlap_shadow_observer: NativeOverlapShadowObserver | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._speaker_shadow_observer = speaker_shadow_observer
        self._overlap_shadow_observer = overlap_shadow_observer

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            observer = self._overlap_shadow_observer
            if observer is not None:
                await asyncio.to_thread(observer.close)

    def _owner_context_diagnostic(self) -> tuple[bool, str, str]:
        context = self._owner_context_state
        if context is None:
            return False, "unavailable", "owner_context_state_not_configured"
        snapshot = context.snapshot()
        assessment = snapshot.assessment
        if assessment is None:
            return (
                False,
                "none",
                snapshot.invalidation_reason or "owner_context_not_observed",
            )
        live = context.has_fresh_live_owner_candidate()
        reasons = ",".join(assessment.reason_codes) if assessment.reason_codes else "none"
        return live, assessment.state.value, reasons

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

    async def _score_overlap(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
    ) -> None:
        observer = self._overlap_shadow_observer
        if observer is None:
            return
        try:
            result = await asyncio.to_thread(observer.score, turn)
        except Exception:
            LOGGER.exception(
                "Overlap shadow turn %s failed; conversation is unaffected",
                audio_turn_id,
            )
            return
        evidence = result.evidence
        LOGGER.info(
            "Overlap shadow turn %s | source=canonical_livekit_pcm | state=%s | "
            "frames=%s | speech=%s | overlap=%s | longest_overlap_run=%s | "
            "peak_active=%s | overlap_fraction=%.3f | stable_runs=%s | "
            "inference_ms=%.1f | rtf=%.3f | threshold_promoted=False | "
            "authority_effect=False | reasons=%s",
            audio_turn_id,
            evidence.state.value,
            evidence.frame_count,
            evidence.speech_frames,
            evidence.overlap_frames,
            evidence.longest_overlap_run,
            evidence.active_speaker_peak,
            evidence.overlap_fraction,
            evidence.stable_speaker_runs or "none",
            result.inference_ms,
            result.realtime_factor,
            ",".join(evidence.reason_codes) if evidence.reason_codes else "none",
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

        # Overlap is intentionally independent of the local Silero/CAM++ quality
        # path. The full committed turn may still contain useful concurrent-speaker
        # evidence even when speaker identity or LR-ASD must return INSUFFICIENT.
        overlap_task: asyncio.Task[None] | None = None
        if self._overlap_shadow_observer is not None:
            overlap_task = asyncio.create_task(
                self._score_overlap(turn, audio_turn_id=audio_turn_id),
                name=f"jarvis-overlap-shadow-{audio_turn_id[:8]}",
            )

        analysis_turn = turn
        speech_segments = 0
        speech_detector = self._speech_region_detector
        if speech_detector is not None:
            region = await speech_detector.extract(turn)
            speech_segments = region.segment_count
            if region.turn is None:
                owner_context_live, owner_context_state, owner_context_reasons = (
                    self._owner_context_diagnostic()
                )
                LOGGER.info(
                    "Speaker shadow turn %s | source=canonical_livekit_pcm | "
                    "captured=%.2fs | speech=none | accepted=False | "
                    "live_owner_context=%s | owner_context_state=%s | "
                    "owner_context_reasons=%s | enrolled_speaker_scored=False | "
                    "active_speaker_confirmed=False | prototype_admission=False | "
                    "reasons=%s",
                    audio_turn_id,
                    turn.duration_seconds,
                    owner_context_live,
                    owner_context_state,
                    owner_context_reasons,
                    region.reason,
                )
                if overlap_task is not None:
                    await overlap_task
                return
            analysis_turn = region.turn

        quality = await asyncio.to_thread(
            assess_speaker_segment,
            analysis_turn.samples,
            sample_rate=analysis_turn.sample_rate,
        )
        owner_context_live, owner_context_state, owner_context_reasons = (
            self._owner_context_diagnostic()
        )
        LOGGER.info(
            "Speaker shadow turn %s | source=canonical_livekit_pcm | captured=%.2fs | "
            "speech=%.2fs | segments=%s | rms %.1f dBFS | accepted=%s | "
            "live_owner_context=%s | owner_context_state=%s | "
            "owner_context_reasons=%s | active_speaker_confirmed=False | "
            "prototype_admission=False | reasons=%s",
            audio_turn_id,
            turn.duration_seconds,
            analysis_turn.duration_seconds,
            speech_segments,
            quality.rms_dbfs,
            quality.accepted,
            owner_context_live,
            owner_context_state,
            owner_context_reasons,
            ",".join(quality.reason_codes) if quality.reason_codes else "none",
        )

        tasks: list[asyncio.Future[Any] | asyncio.Task[Any] | Any] = [
            self._inspect_active_speaker_turn(
                analysis_turn,
                audio_turn_id=audio_turn_id,
                quality_accepted=quality.accepted,
            )
        ]
        if overlap_task is not None:
            tasks.append(overlap_task)
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
