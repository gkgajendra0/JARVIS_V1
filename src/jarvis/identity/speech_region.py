from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from livekit import rtc
from livekit.agents import inference, vad

from jarvis.identity.speaker_turn import SpeakerTurnAudio


@dataclass(frozen=True, slots=True)
class SpeechRegionResult:
    turn: SpeakerTurnAudio | None
    segment_count: int
    reason: str


class SpeechRegionDetector(Protocol):
    async def extract(self, turn: SpeakerTurnAudio) -> SpeechRegionResult: ...


class LiveKitSileroSpeechRegionDetector:
    """Trim provider-sized turns to one local speech-active region.

    The detector reuses LiveKit's bundled local Silero VAD. Raw audio remains
    memory-only. The longest continuous speech region is selected because active
    speaker scoring requires one temporally coherent audio/visual segment rather
    than a stitched set of disjoint speech islands.
    """

    def __init__(
        self,
        *,
        min_speech_duration: float = 0.08,
        min_silence_duration: float = 0.18,
        prefix_padding_duration: float = 0.12,
        activation_threshold: float = 0.5,
    ) -> None:
        if min_speech_duration <= 0:
            raise ValueError("speech-region minimum speech duration must be positive")
        if min_silence_duration <= 0:
            raise ValueError("speech-region minimum silence duration must be positive")
        if prefix_padding_duration < 0:
            raise ValueError("speech-region prefix padding must be non-negative")
        if not 0 < activation_threshold < 1:
            raise ValueError("speech-region activation threshold must be in (0, 1)")
        self._min_silence_duration = min_silence_duration
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
            return SpeechRegionResult(None, 0, "speech_region_audio_timestamps_missing")

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
            async for event in stream:
                if event.type is not vad.VADEventType.END_OF_SPEECH:
                    continue
                candidate = _candidate_from_end_event(turn, event)
                if candidate is not None:
                    candidates.append(candidate)
        finally:
            await stream.aclose()

        if not candidates:
            return SpeechRegionResult(None, 0, "speech_region_not_detected")
        selected = max(candidates, key=lambda candidate: candidate.duration_seconds)
        return SpeechRegionResult(selected, len(candidates), "speech_region_selected")


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
    start_sample = min(
        turn.samples.size,
        max(0, round(buffered_start_offset * turn.sample_rate)),
    )
    end_sample = min(
        turn.samples.size,
        max(start_sample, round(speech_end_offset * turn.sample_rate)),
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
