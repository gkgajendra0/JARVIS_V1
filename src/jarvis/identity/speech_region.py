from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from livekit import rtc
from livekit.agents import inference, vad

from jarvis.identity.speaker_turn import SpeakerTurnAudio

_SILERO_INFERENCE_WINDOW_SECONDS = 0.032
_DEFAULT_UTTERANCE_MERGE_GAP_SECONDS = 0.8


@dataclass(frozen=True, slots=True)
class SpeechRegionResult:
    turn: SpeakerTurnAudio | None
    segment_count: int
    reason: str
    max_vad_probability: float | None = None


@dataclass(frozen=True, slots=True)
class _ProbabilityObservation:
    timestamp: float
    probability: float


class SpeechRegionDetector(Protocol):
    async def extract(self, turn: SpeakerTurnAudio) -> SpeechRegionResult: ...


class LiveKitSileroSpeechRegionDetector:
    """Trim a committed recent-audio window to one local speech-active region.

    The detector reuses LiveKit's bundled local Silero VAD. Raw audio remains
    memory-only. A committed user message may arrive after a bounded recent-audio
    window that still contains older speech leakage. Nearby Silero speech islands
    are therefore consolidated across bounded conversational pauses while keeping
    their real silence and timestamps intact, then the most recent consolidated
    utterance is selected.

    LiveKit's normal END_OF_SPEECH event is authoritative when available. For
    bounded offline turns, end_input() also establishes a hard reset boundary, so
    a probability-derived fallback is retained for the case where Silero detected
    speech windows but did not publish a complete endpoint event before reset.
    """

    def __init__(
        self,
        *,
        min_speech_duration: float = 0.08,
        min_silence_duration: float = 0.18,
        prefix_padding_duration: float = 0.12,
        activation_threshold: float = 0.30,
        utterance_merge_gap_seconds: float = _DEFAULT_UTTERANCE_MERGE_GAP_SECONDS,
    ) -> None:
        if min_speech_duration <= 0:
            raise ValueError("speech-region minimum speech duration must be positive")
        if min_silence_duration <= 0:
            raise ValueError("speech-region minimum silence duration must be positive")
        if prefix_padding_duration < 0:
            raise ValueError("speech-region prefix padding must be non-negative")
        if not 0 < activation_threshold < 1:
            raise ValueError("speech-region activation threshold must be in (0, 1)")
        if utterance_merge_gap_seconds <= 0:
            raise ValueError("speech-region utterance merge gap must be positive")
        self._min_speech_duration = min_speech_duration
        self._min_silence_duration = min_silence_duration
        self._prefix_padding_duration = prefix_padding_duration
        self._activation_threshold = activation_threshold
        self._utterance_merge_gap_seconds = utterance_merge_gap_seconds
        self._vad = inference.VAD(
            model="silero",
            min_speech_duration=min_speech_duration,
            min_silence_duration=min_silence_duration,
            prefix_padding_duration=prefix_padding_duration,
            max_buffered_speech=20.0,
            activation_threshold=activation_threshold,
        )

    async def extract(self, turn: SpeakerTurnAudio) -> SpeechRegionResult:
        if turn.start_monotonic is None or turn.end_monotonic is None:
            return SpeechRegionResult(
                None,
                0,
                "speech_region_audio_timestamps_missing",
            )

        stream = self._vad.stream()
        try:
            _push_pcm(stream, turn.samples, turn.sample_rate)
            flush_samples = np.zeros(
                round((self._min_silence_duration + 0.12) * turn.sample_rate),
                dtype=np.int16,
            )
            _push_pcm(stream, flush_samples, turn.sample_rate)
            stream.end_input()

            candidates: list[SpeakerTurnAudio] = []
            observations: list[_ProbabilityObservation] = []
            max_probability: float | None = None
            async for event in stream:
                if event.type is vad.VADEventType.INFERENCE_DONE:
                    probability = float(event.probability)
                    if np.isfinite(probability):
                        observations.append(
                            _ProbabilityObservation(
                                timestamp=max(0.0, float(event.timestamp)),
                                probability=probability,
                            )
                        )
                        max_probability = (
                            probability
                            if max_probability is None
                            else max(max_probability, probability)
                        )
                    continue
                if event.type is not vad.VADEventType.END_OF_SPEECH:
                    continue
                candidate = _candidate_from_end_event(turn, event)
                if candidate is not None:
                    candidates.append(candidate)
        finally:
            await stream.aclose()

        if candidates:
            consolidated = _consolidate_candidates(
                turn,
                candidates,
                max_gap_seconds=self._utterance_merge_gap_seconds,
            )
            selected = _select_latest_candidate(consolidated)
            reason = (
                "speech_region_selected_consolidated"
                if len(consolidated) < len(candidates)
                else "speech_region_selected"
            )
            return SpeechRegionResult(
                selected,
                len(candidates),
                reason,
                max_probability,
            )

        fallback_candidates = _candidates_from_probability_observations(
            turn,
            observations,
            activation_threshold=self._activation_threshold,
            min_speech_duration=self._min_speech_duration,
            min_silence_duration=self._min_silence_duration,
            prefix_padding_duration=self._prefix_padding_duration,
        )
        if fallback_candidates:
            consolidated = _consolidate_candidates(
                turn,
                fallback_candidates,
                max_gap_seconds=self._utterance_merge_gap_seconds,
            )
            selected = _select_latest_candidate(consolidated)
            reason = (
                "speech_region_selected_probability_fallback_consolidated"
                if len(consolidated) < len(fallback_candidates)
                else "speech_region_selected_probability_fallback"
            )
            return SpeechRegionResult(
                selected,
                len(fallback_candidates),
                reason,
                max_probability,
            )

        probability_reason = (
            "n/a" if max_probability is None else f"{max_probability:.4f}"
        )
        return SpeechRegionResult(
            None,
            0,
            f"speech_region_not_detected:max_vad_probability={probability_reason}",
            max_probability,
        )


def _candidate_from_end_event(
    turn: SpeakerTurnAudio,
    event: vad.VADEvent,
) -> SpeakerTurnAudio | None:
    if turn.start_monotonic is None:
        return None
    frame_samples = sum(frame.samples_per_channel for frame in event.frames)
    if frame_samples <= 0:
        return None

    event_timestamp = max(0.0, float(event.timestamp))
    buffered_start_offset = max(
        0.0,
        event_timestamp - frame_samples / turn.sample_rate,
    )
    speech_end_offset = max(
        buffered_start_offset,
        event_timestamp - max(0.0, float(event.silence_duration)),
    )
    return _candidate_from_offsets(
        turn,
        buffered_start_offset,
        speech_end_offset,
    )


def _candidates_from_probability_observations(
    turn: SpeakerTurnAudio,
    observations: list[_ProbabilityObservation],
    *,
    activation_threshold: float,
    min_speech_duration: float,
    min_silence_duration: float,
    prefix_padding_duration: float,
) -> list[SpeakerTurnAudio]:
    active = [
        observation
        for observation in observations
        if observation.timestamp <= turn.duration_seconds + min_silence_duration
        and observation.probability >= activation_threshold
    ]
    if not active:
        return []

    groups: list[list[_ProbabilityObservation]] = [[active[0]]]
    maximum_active_gap = min_silence_duration + _SILERO_INFERENCE_WINDOW_SECONDS
    for observation in active[1:]:
        if observation.timestamp - groups[-1][-1].timestamp <= maximum_active_gap:
            groups[-1].append(observation)
        else:
            groups.append([observation])

    candidates: list[SpeakerTurnAudio] = []
    for group in groups:
        speech_start = max(
            0.0,
            group[0].timestamp
            - _SILERO_INFERENCE_WINDOW_SECONDS
            - prefix_padding_duration,
        )
        speech_end = min(turn.duration_seconds, group[-1].timestamp)
        active_duration = (
            group[-1].timestamp - group[0].timestamp + _SILERO_INFERENCE_WINDOW_SECONDS
        )
        if active_duration < min_speech_duration:
            continue
        candidate = _candidate_from_offsets(turn, speech_start, speech_end)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _consolidate_candidates(
    turn: SpeakerTurnAudio,
    candidates: list[SpeakerTurnAudio],
    *,
    max_gap_seconds: float,
) -> list[SpeakerTurnAudio]:
    if max_gap_seconds <= 0:
        raise ValueError("speech-region consolidation gap must be positive")
    if not candidates:
        return []
    if turn.start_monotonic is None:
        raise ValueError("speech-region consolidation requires turn timestamps")

    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.start_monotonic
            if candidate.start_monotonic is not None
            else float("inf")
        ),
    )
    groups: list[list[SpeakerTurnAudio]] = [[ordered[0]]]
    for candidate in ordered[1:]:
        previous = groups[-1][-1]
        if (
            previous.end_monotonic is None
            or candidate.start_monotonic is None
            or candidate.end_monotonic is None
        ):
            raise ValueError(
                "speech-region consolidation requires candidate timestamps"
            )
        gap = candidate.start_monotonic - previous.end_monotonic
        if gap <= max_gap_seconds:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])

    consolidated: list[SpeakerTurnAudio] = []
    for group in groups:
        start_monotonic = group[0].start_monotonic
        end_monotonic = group[-1].end_monotonic
        if start_monotonic is None or end_monotonic is None:
            raise ValueError(
                "speech-region consolidation requires candidate timestamps"
            )
        candidate = _candidate_from_offsets(
            turn,
            max(0.0, start_monotonic - turn.start_monotonic),
            max(0.0, end_monotonic - turn.start_monotonic),
        )
        if candidate is not None:
            consolidated.append(candidate)
    return consolidated


def _select_latest_candidate(candidates: list[SpeakerTurnAudio]) -> SpeakerTurnAudio:
    if not candidates:
        raise ValueError(
            "speech-region candidate selection requires at least one region"
        )
    return max(
        candidates,
        key=lambda candidate: (
            candidate.end_monotonic if candidate.end_monotonic is not None else -1.0
        ),
    )


def _candidate_from_offsets(
    turn: SpeakerTurnAudio,
    start_offset: float,
    end_offset: float,
) -> SpeakerTurnAudio | None:
    if turn.start_monotonic is None:
        return None
    start_sample = min(
        turn.samples.size,
        max(0, round(start_offset * turn.sample_rate)),
    )
    end_sample = min(
        turn.samples.size,
        max(start_sample, round(end_offset * turn.sample_rate)),
    )
    if end_sample <= start_sample:
        return None

    return SpeakerTurnAudio(
        samples=turn.samples[start_sample:end_sample].copy(),
        sample_rate=turn.sample_rate,
        start_monotonic=turn.start_monotonic + start_sample / turn.sample_rate,
        end_monotonic=turn.start_monotonic + end_sample / turn.sample_rate,
    )


def _push_pcm(stream: vad.VADStream, samples: np.ndarray, sample_rate: int) -> None:
    if samples.ndim != 1 or samples.dtype != np.int16:
        raise ValueError("speech-region PCM must be one-dimensional int16")
    frame_samples = max(1, round(sample_rate * 0.02))
    for start in range(0, samples.size, frame_samples):
        chunk = samples[start : start + frame_samples]
        if chunk.size == 0:
            continue
        stream.push_frame(
            rtc.AudioFrame(
                data=chunk.tobytes(),
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=chunk.size,
            )
        )
