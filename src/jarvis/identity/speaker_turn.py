from __future__ import annotations

import threading
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
    """Bounded thread-safe rolling mono PCM buffer for committed user turns.

    Provider user-state transitions are intentionally not used as biometric audio
    boundaries. Runtime audio producers continuously feed PCM here and take a bounded
    snapshot only when the conversation layer commits a user message. Raw audio stays
    memory-only and is discarded from the rolling buffer after the snapshot is taken.
    The internal lock also makes the same capture safe for native GStreamer callbacks.
    """

    def __init__(self, *, max_turn_seconds: float = 15.0) -> None:
        if max_turn_seconds <= 0:
            raise ValueError("speaker turn maximum duration must be positive")
        self.max_turn_seconds = max_turn_seconds
        self._lock = threading.RLock()
        self._sample_rate: int | None = None
        self._chunks: deque[tuple[bytes, int, float]] = deque()
        self._buffered_samples = 0

    def clear(self) -> None:
        with self._lock:
            self._sample_rate = None
            self._chunks.clear()
            self._buffered_samples = 0

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

        with self._lock:
            if self._sample_rate is None:
                self._sample_rate = sample_rate
            elif sample_rate != self._sample_rate:
                self._sample_rate = sample_rate
                self._chunks.clear()
                self._buffered_samples = 0

            self._chunks.append((payload, samples_per_channel, observed_at))
            self._buffered_samples += samples_per_channel
            self._trim_to_limit()

    def snapshot_recent_audio(self, *, clear: bool = True) -> SpeakerTurnAudio | None:
        with self._lock:
            sample_rate = self._sample_rate
            if sample_rate is None or not self._chunks or self._buffered_samples <= 0:
                return None

            chunks = tuple(self._chunks)
            sample_count = self._buffered_samples
            start_monotonic = chunks[0][2]
            _, final_samples, final_observed_at = chunks[-1]
            end_monotonic = final_observed_at + final_samples / sample_rate
            payload = b"".join(chunk for chunk, _, _ in chunks)
            samples = np.frombuffer(payload, dtype=np.int16, count=sample_count).copy()

            if clear:
                self._chunks.clear()
                self._buffered_samples = 0

        if samples.size == 0:
            return None
        return SpeakerTurnAudio(
            samples=samples,
            sample_rate=sample_rate,
            start_monotonic=start_monotonic,
            end_monotonic=end_monotonic,
        )

    def _trim_to_limit(self) -> None:
        sample_rate = self._sample_rate
        if sample_rate is None:
            return
        limit = max(1, round(self.max_turn_seconds * sample_rate))
        while self._chunks and self._buffered_samples > limit:
            payload, samples, observed_at = self._chunks.popleft()
            overflow = self._buffered_samples - limit
            if samples <= overflow:
                self._buffered_samples -= samples
                continue

            trim_samples = overflow
            remaining_samples = samples - trim_samples
            trimmed_payload = payload[trim_samples * 2 :]
            trimmed_observed_at = observed_at + trim_samples / sample_rate
            self._chunks.appendleft(
                (trimmed_payload, remaining_samples, trimmed_observed_at)
            )
            self._buffered_samples -= trim_samples
