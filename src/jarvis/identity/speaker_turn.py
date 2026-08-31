from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SpeakerTurnAudio:
    """One memory-only mono PCM user turn from the canonical JARVIS audio path."""

    samples: np.ndarray
    sample_rate: int
    start_monotonic: float | None = None
    end_monotonic: float | None = None

    def __post_init__(self) -> None:
        if self.samples.ndim != 1 or self.samples.dtype != np.int16:
            raise ValueError("speaker turn audio must be one-dimensional int16 PCM")
        if self.samples.size == 0:
            raise ValueError("speaker turn audio must not be empty")
        if self.sample_rate <= 0:
            raise ValueError("speaker turn sample_rate must be positive")
        if (self.start_monotonic is None) != (self.end_monotonic is None):
            raise ValueError("speaker turn timestamps must be supplied together")
        if self.start_monotonic is not None:
            if self.start_monotonic < 0 or self.end_monotonic is None:
                raise ValueError("speaker turn timestamps must be non-negative")
            if self.end_monotonic <= self.start_monotonic:
                raise ValueError("speaker turn end timestamp must follow its start")

    @property
    def duration_seconds(self) -> float:
        return self.samples.size / self.sample_rate


class InMemorySpeakerTurnCapture:
    """Bounded turn capture driven by LiveKit user speaking/listening transitions.

    No raw audio is written to disk. A small rolling pre-roll protects the first
    phoneme when LiveKit's user-state event arrives just after speech begins.
    Canonical-frame arrival timestamps are retained only in memory so downstream
    audio-visual evidence can bind to the same monotonic clock as camera frames.
    """

    def __init__(
        self,
        *,
        pre_roll_seconds: float = 0.20,
        max_turn_seconds: float = 15.0,
    ) -> None:
        if pre_roll_seconds < 0:
            raise ValueError("speaker turn pre-roll must be non-negative")
        if max_turn_seconds <= 0:
            raise ValueError("speaker turn maximum duration must be positive")
        if pre_roll_seconds > max_turn_seconds:
            raise ValueError("speaker turn pre-roll must fit inside maximum duration")
        self.pre_roll_seconds = pre_roll_seconds
        self.max_turn_seconds = max_turn_seconds
        self._sample_rate: int | None = None
        self._pre_roll: deque[tuple[bytes, int, float]] = deque()
        self._pre_roll_samples = 0
        self._turn_chunks: list[bytes] = []
        self._turn_samples = 0
        self._turn_start_monotonic: float | None = None
        self._turn_end_monotonic: float | None = None
        self._recording = False

    @property
    def recording(self) -> bool:
        return self._recording

    def clear(self) -> None:
        self._sample_rate = None
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        self._turn_chunks.clear()
        self._turn_samples = 0
        self._turn_start_monotonic = None
        self._turn_end_monotonic = None
        self._recording = False

    def push_frame(
        self,
        data: bytes | bytearray | memoryview,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        observed_at_monotonic: float | None = None,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("speaker frame sample_rate must be positive")
        if num_channels != 1:
            raise ValueError("speaker shadow capture requires mono PCM")
        if samples_per_channel <= 0:
            raise ValueError("speaker frame samples_per_channel must be positive")
        observed_at = (
            time.monotonic() if observed_at_monotonic is None else observed_at_monotonic
        )
        if observed_at < 0:
            raise ValueError("speaker frame timestamp must be non-negative")
        payload = bytes(data)
        expected_bytes = samples_per_channel * 2
        if len(payload) != expected_bytes:
            raise ValueError("speaker frame byte length does not match int16 mono PCM")

        if self._sample_rate is None:
            self._sample_rate = sample_rate
        elif sample_rate != self._sample_rate:
            self.clear()
            self._sample_rate = sample_rate

        frame_end = observed_at + samples_per_channel / sample_rate
        if self._recording:
            remaining = self._max_turn_samples() - self._turn_samples
            if remaining <= 0:
                return
            accepted_samples = min(samples_per_channel, remaining)
            accepted_bytes = accepted_samples * 2
            if self._turn_start_monotonic is None:
                self._turn_start_monotonic = observed_at
            self._turn_chunks.append(payload[:accepted_bytes])
            self._turn_samples += accepted_samples
            self._turn_end_monotonic = observed_at + accepted_samples / sample_rate
            return

        self._pre_roll.append((payload, samples_per_channel, observed_at))
        self._pre_roll_samples += samples_per_channel
        limit = self._pre_roll_limit_samples()
        while self._pre_roll and self._pre_roll_samples > limit:
            _, removed_samples, _ = self._pre_roll.popleft()
            self._pre_roll_samples -= removed_samples
        if self._pre_roll:
            self._turn_end_monotonic = frame_end

    def start_turn(self) -> None:
        if self._recording:
            return
        self._recording = True
        self._turn_chunks = [payload for payload, _, _ in self._pre_roll]
        self._turn_samples = self._pre_roll_samples
        self._turn_start_monotonic = self._pre_roll[0][2] if self._pre_roll else None
        if self._pre_roll and self._sample_rate is not None:
            payload, samples, observed_at = self._pre_roll[-1]
            del payload
            self._turn_end_monotonic = observed_at + samples / self._sample_rate
        else:
            self._turn_end_monotonic = None
        self._pre_roll.clear()
        self._pre_roll_samples = 0

    def finish_turn(self) -> SpeakerTurnAudio | None:
        if not self._recording:
            return None
        self._recording = False
        chunks = self._turn_chunks
        sample_count = self._turn_samples
        start_monotonic = self._turn_start_monotonic
        end_monotonic = self._turn_end_monotonic
        self._turn_chunks = []
        self._turn_samples = 0
        self._turn_start_monotonic = None
        self._turn_end_monotonic = None
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        sample_rate = self._sample_rate
        if not chunks or sample_count <= 0 or sample_rate is None:
            return None
        payload = b"".join(chunks)
        samples = np.frombuffer(payload, dtype=np.int16, count=sample_count).copy()
        if samples.size == 0:
            return None
        return SpeakerTurnAudio(
            samples=samples,
            sample_rate=sample_rate,
            start_monotonic=start_monotonic,
            end_monotonic=end_monotonic,
        )

    def _pre_roll_limit_samples(self) -> int:
        if self._sample_rate is None:
            return 0
        return round(self.pre_roll_seconds * self._sample_rate)

    def _max_turn_samples(self) -> int:
        assert self._sample_rate is not None
        return round(self.max_turn_seconds * self._sample_rate)
