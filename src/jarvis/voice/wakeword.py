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
STREAMING_PRETRIGGER_THRESHOLD = 0.05
_EMBEDDING_WINDOW = 76
_EMBEDDING_STRIDE = 8
_MIN_EMBEDDINGS = 16


class WakePredictor(Protocol):
    """Score provider used by the replaceable detector boundary."""

    window_samples: int

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]: ...

    def reset(self) -> None: ...


class StatelessWakePredictor(Protocol):
    """Exact full-window scorer used only after a streaming pre-trigger."""

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]: ...


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


def _bounded_ort_session(model_path: Path):
    """Create a CPU ONNX session without per-session worker-pool spinning."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


class BoundedLiveKitWakeVerifier:
    """LiveKit-0.2.1-compatible full-window scoring with bounded ORT threads.

    This deliberately mirrors the released LiveKit wake inference contract while
    controlling ONNX Runtime session scheduling that LiveKit 0.2.1 does not
    expose through its public constructor.
    """

    def __init__(self, model_path: Path) -> None:
        from livekit.wakeword.resources import (
            get_embedding_model_path,
            get_mel_model_path,
        )

        mel_model_path = get_mel_model_path()
        embedding_model_path = get_embedding_model_path()
        for feature_path in (mel_model_path, embedding_model_path, model_path):
            if not feature_path.is_file():
                raise FileNotFoundError(f"Wake verifier model not found: {feature_path}")

        self._model_name = model_path.stem
        self._mel_session = _bounded_ort_session(mel_model_path)
        self._embedding_session = _bounded_ort_session(embedding_model_path)
        self._classifier_session = _bounded_ort_session(model_path)
        self._mel_input = self._mel_session.get_inputs()[0].name
        self._embedding_input = self._embedding_session.get_inputs()[0].name
        self._classifier_input = self._classifier_session.get_inputs()[0].name
        LOGGER.info(
            "Bounded exact wake verifier loaded: model=%s window_ms=2000 "
            "onnx_sessions=3 intra_threads=1 spinning=off",
            model_path.name,
        )

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]:
        audio = np.asarray(audio_chunk).reshape(-1)
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32, copy=False)

        mel_output = self._mel_session.run(
            None,
            {self._mel_input: audio[np.newaxis, :]},
        )[0]
        mel = np.asarray(mel_output)
        if mel.ndim == 4:
            mel = mel[:, 0, :, :]
        if mel.ndim == 3:
            mel = mel[0]
        mel = mel.astype(np.float32, copy=False) / 10.0 + 2.0

        if mel.shape[0] < _EMBEDDING_WINDOW:
            return {self._model_name: 0.0}

        embeddings: list[np.ndarray] = []
        for start in range(
            0,
            mel.shape[0] - _EMBEDDING_WINDOW + 1,
            _EMBEDDING_STRIDE,
        ):
            window = mel[start : start + _EMBEDDING_WINDOW]
            embedding_output = self._embedding_session.run(
                None,
                {self._embedding_input: window[np.newaxis, :, :, np.newaxis]},
            )[0]
            embedding = np.asarray(embedding_output).reshape(1, -1)[0]
            embeddings.append(embedding.astype(np.float32, copy=False))

        if len(embeddings) < _MIN_EMBEDDINGS:
            return {self._model_name: 0.0}

        classifier_input = np.stack(embeddings[-_MIN_EMBEDDINGS:], axis=0)
        classifier_input = classifier_input[np.newaxis, :, :].astype(np.float32)
        classifier_output = self._classifier_session.run(
            None,
            {self._classifier_input: classifier_input},
        )[0]
        score = float(np.asarray(classifier_output).reshape(-1)[0])
        return {self._model_name: score}


class CascadedWakePredictor:
    """Cheap streaming proposal stage plus exact full-window verifier."""

    window_samples = INFERENCE_STRIDE_SAMPLES

    def __init__(
        self,
        streaming_predictor: WakePredictor,
        verifier: StatelessWakePredictor,
        *,
        pretrigger_threshold: float = STREAMING_PRETRIGGER_THRESHOLD,
    ) -> None:
        if not 0 < pretrigger_threshold < 1:
            raise ValueError("wake pretrigger threshold must be between 0 and 1")
        self._streaming = streaming_predictor
        self._verifier = verifier
        self._pretrigger_threshold = pretrigger_threshold
        self._raw_chunks: deque[np.ndarray] = deque()
        self._raw_sample_count = 0
        self._lock = Lock()

    def _append_raw(self, samples: np.ndarray) -> None:
        self._raw_chunks.append(samples.copy())
        self._raw_sample_count += samples.size
        while (
            self._raw_chunks
            and self._raw_sample_count - self._raw_chunks[0].size >= WINDOW_SAMPLES
        ):
            self._raw_sample_count -= self._raw_chunks.popleft().size

    def _full_window(self) -> np.ndarray:
        audio = np.concatenate(tuple(self._raw_chunks))
        return audio[-WINDOW_SAMPLES:].copy()

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]:
        samples = np.asarray(audio_chunk, dtype=np.int16).reshape(-1)
        if samples.size != self.window_samples:
            raise ValueError(
                "wake cascade requires exactly "
                f"{self.window_samples} samples; got {samples.size}"
            )

        with self._lock:
            self._append_raw(samples)
            streaming_scores = self._streaming.predict(samples)
            suppressed = {name: 0.0 for name in streaming_scores}

            if self._raw_sample_count < WINDOW_SAMPLES:
                return suppressed

            streaming_peak = max(streaming_scores.values(), default=0.0)
            if streaming_peak < self._pretrigger_threshold:
                return suppressed

            exact_scores = {
                str(name): float(score)
                for name, score in self._verifier.predict(self._full_window()).items()
            }
            exact_peak = max(exact_scores.values(), default=0.0)
            LOGGER.info(
                "Wake cascade verifier ran: streaming_peak=%.3f exact_peak=%.3f",
                streaming_peak,
                exact_peak,
            )
            return exact_scores

    def reset(self) -> None:
        with self._lock:
            self._streaming.reset()
            self._raw_chunks.clear()
            self._raw_sample_count = 0


@dataclass(frozen=True, slots=True)
class WakeDetection:
    name: str
    confidence: float
    detected_at: float


def load_livekit_predictor(model_path: Path) -> WakePredictor:
    """Load the low-CPU streaming proposal + bounded exact verifier cascade."""
    if not model_path.is_file():
        raise FileNotFoundError(f"Wake-word model not found: {model_path}")

    streaming = OpenWakeWordStreamingPredictor(model_path)
    verifier = BoundedLiveKitWakeVerifier(model_path)
    LOGGER.info(
        "Wake cascade loaded: streaming_pretrigger=%.2f exact_window_ms=2000 "
        "exact_verifier=bounded-livekit-compatible decision_threshold=outer-detector",
        STREAMING_PRETRIGGER_THRESHOLD,
    )
    return CascadedWakePredictor(streaming, verifier)


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
