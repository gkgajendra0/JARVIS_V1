"""Local wake-word inference without microphone ownership."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from livekit import rtc

WAKE_SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 32_000
INFERENCE_STRIDE_SAMPLES = 1_280


class WakePredictor(Protocol):
    """Stateless score provider used by the replaceable detector boundary."""

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]: ...


@dataclass(frozen=True, slots=True)
class WakeDetection:
    name: str
    confidence: float
    detected_at: float


def load_livekit_predictor(model_path: Path) -> WakePredictor:
    """Load the pinned LiveKit classifier without its microphone listener."""
    if not model_path.is_file():
        raise FileNotFoundError(f"Wake-word model not found: {model_path}")

    from livekit.wakeword import WakeWordModel

    return WakeWordModel(models=[model_path])


class LiveKitWakeDetector:
    """Score a rolling 16 kHz window supplied by JARVIS-owned audio."""

    def __init__(
        self,
        predictor: WakePredictor,
        *,
        threshold: float,
        debounce_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError("wake threshold must be greater than 0 and at most 1")
        if debounce_seconds < 0:
            raise ValueError("wake debounce must not be negative")

        self._predictor = predictor
        self._threshold = threshold
        self._debounce_seconds = debounce_seconds
        self._clock = clock
        self._resampler = rtc.AudioResampler(
            input_rate=48_000,
            output_rate=WAKE_SAMPLE_RATE,
            num_channels=1,
        )
        self._chunks: deque[np.ndarray] = deque()
        self._sample_count = 0
        self._samples_since_inference = 0
        self._enabled = False
        self._closed = False
        self._last_detection = float("-inf")
        self._inference_task: asyncio.Task[None] | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="wakeword"
        )
        self._detections: asyncio.Queue[WakeDetection] = asyncio.Queue(maxsize=1)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self, *, clear_buffer: bool = True) -> None:
        if self._closed:
            raise RuntimeError("wake detector is closed")
        if clear_buffer:
            self.clear_buffer()
        self._enabled = True

    def disable(self, *, clear_buffer: bool = True) -> None:
        self._enabled = False
        if clear_buffer:
            self.clear_buffer()

    def clear_buffer(self) -> None:
        self._chunks.clear()
        self._sample_count = 0
        self._samples_since_inference = 0
        while not self._detections.empty():
            self._detections.get_nowait()

    def feed(self, frame: rtc.AudioFrame) -> None:
        if self._closed or not self._enabled:
            return
        if frame.num_channels != 1:
            raise ValueError("wake detector requires mono audio")

        frames = (
            [frame]
            if frame.sample_rate == WAKE_SAMPLE_RATE
            else self._resampler.push(frame)
        )
        for resampled in frames:
            samples = np.frombuffer(resampled.data, dtype=np.int16).copy()
            self._chunks.append(samples)
            self._sample_count += len(samples)
            self._samples_since_inference += len(samples)

        self._trim_window()
        if (
            self._sample_count >= WINDOW_SAMPLES
            and self._samples_since_inference >= INFERENCE_STRIDE_SAMPLES
            and (self._inference_task is None or self._inference_task.done())
        ):
            self._samples_since_inference %= INFERENCE_STRIDE_SAMPLES
            window = self._window()
            self._inference_task = asyncio.create_task(self._score(window))

    def _trim_window(self) -> None:
        while (
            self._chunks and self._sample_count - len(self._chunks[0]) >= WINDOW_SAMPLES
        ):
            self._sample_count -= len(self._chunks.popleft())

    def _window(self) -> np.ndarray:
        audio = np.concatenate(tuple(self._chunks))
        return audio[-WINDOW_SAMPLES:].copy()

    async def _score(self, window: np.ndarray) -> None:
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            self._executor,
            self._predictor.predict,
            window,
        )
        if not self._enabled or self._closed:
            return

        now = self._clock()
        for name, confidence in scores.items():
            if confidence < self._threshold:
                continue
            if now - self._last_detection < self._debounce_seconds:
                continue
            self._last_detection = now
            self._enabled = False
            detection = WakeDetection(name, confidence, now)
            if self._detections.full():
                self._detections.get_nowait()
            self._detections.put_nowait(detection)
            break

    async def wait_for_detection(self) -> WakeDetection:
        if self._closed:
            raise RuntimeError("wake detector is closed")
        return await self._detections.get()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._enabled = False
        if self._inference_task is not None:
            await asyncio.gather(self._inference_task, return_exceptions=True)
        self._executor.shutdown(wait=True)
        self.clear_buffer()
