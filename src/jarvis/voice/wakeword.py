"""Local wake-word inference without microphone ownership."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

import numpy as np
from livekit import rtc

LOGGER = logging.getLogger(__name__)

WAKE_SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 32_000
INFERENCE_STRIDE_SAMPLES = 1_280


class WakePredictor(Protocol):
    """Score provider used by the replaceable detector boundary."""

    window_samples: int

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]: ...

    def reset(self) -> None: ...


class OpenWakeWordStreamingPredictor:
    """Incremental openWakeWord frontend for a compatible ONNX classifier."""

    window_samples = INFERENCE_STRIDE_SAMPLES

    def __init__(self, model_path: Path) -> None:
        try:
            from livekit.wakeword.resources import (
                get_embedding_model_path,
                get_mel_model_path,
            )
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError(
                "Streaming wake inference requires livekit-wakeword resources and "
                "openwakeword==0.6.0."
            ) from exc

        mel_model_path = get_mel_model_path()
        embedding_model_path = get_embedding_model_path()
        if not mel_model_path.is_file() or not embedding_model_path.is_file():
            raise RuntimeError(
                "Bundled LiveKit wake feature models are missing; reinstall the "
                "livekit-wakeword package before starting JARVIS."
            )

        self._lock = Lock()
        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
            ncpu=1,
            melspec_model_path=str(mel_model_path),
            embedding_model_path=str(embedding_model_path),
        )
        LOGGER.info(
            "Streaming wake-word frontend loaded via openWakeWord: model=%s "
            "frame_ms=80 onnx_threads=1 feature_models=livekit-bundled",
            model_path.name,
        )

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]:
        samples = np.asarray(audio_chunk, dtype=np.int16).reshape(-1)
        if samples.size != self.window_samples:
            raise ValueError(
                "streaming wake predictor requires exactly "
                f"{self.window_samples} samples; got {samples.size}"
            )
        with self._lock:
            scores = self._model.predict(samples)
        return {str(name): float(score) for name, score in scores.items()}

    def reset(self) -> None:
        with self._lock:
            self._model.reset()


@dataclass(frozen=True, slots=True)
class WakeDetection:
    name: str
    confidence: float
    detected_at: float


def load_livekit_predictor(model_path: Path) -> WakePredictor:
    """Load the LiveKit-trained classifier on the streaming openWakeWord frontend."""
    if not model_path.is_file():
        raise FileNotFoundError(f"Wake-word model not found: {model_path}")
    return OpenWakeWordStreamingPredictor(model_path)


class LiveKitWakeDetector:
    """Score JARVIS-owned 16 kHz audio through a replaceable wake predictor."""

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

        predictor_window_samples = getattr(predictor, "window_samples", WINDOW_SAMPLES)
        if predictor_window_samples <= 0:
            raise ValueError("wake predictor window_samples must be positive")

        self._predictor = predictor
        self._predictor_window_samples = int(predictor_window_samples)
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

    def clear_buffer(self, *, reset_predictor: bool = True) -> None:
        self._chunks.clear()
        self._sample_count = 0
        self._samples_since_inference = 0
        while not self._detections.empty():
            self._detections.get_nowait()
        if reset_predictor:
            reset = getattr(self._predictor, "reset", None)
            if callable(reset):
                reset()

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
            self._sample_count >= self._predictor_window_samples
            and self._samples_since_inference >= INFERENCE_STRIDE_SAMPLES
            and (self._inference_task is None or self._inference_task.done())
        ):
            self._samples_since_inference %= INFERENCE_STRIDE_SAMPLES
            window = self._window(self._predictor_window_samples)
            self._inference_task = asyncio.create_task(self._score(window))

    def _trim_window(self) -> None:
        while (
            self._chunks
            and self._sample_count - len(self._chunks[0])
            >= self._predictor_window_samples
        ):
            self._sample_count -= len(self._chunks.popleft())

    def _window(self, samples: int) -> np.ndarray:
        audio = np.concatenate(tuple(self._chunks))
        return audio[-samples:].copy()

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
        self.clear_buffer(reset_predictor=False)
