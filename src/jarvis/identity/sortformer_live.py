from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from typing import Self

import numpy as np

from jarvis.identity.sortformer_native import (
    NativeSortformerDiarizer,
    SortformerNativeError,
    _to_float32_mono,
)


@dataclass(frozen=True, slots=True)
class SortformerLiveSnapshot:
    frame_start: int
    frame_count: int
    num_speakers: int
    seconds_per_frame: float
    probabilities: np.ndarray

    @property
    def retained_frames(self) -> int:
        return int(self.frame_count - self.frame_start)


@dataclass(frozen=True, slots=True)
class SortformerLivePush:
    audio_seconds_total: float
    push_latency_ms: float
    snapshot: SortformerLiveSnapshot


class NativeSortformerLiveStream:
    """One long-lived NeMo-Speech.cpp diarization stream over caller-owned PCM.

    The model remains owned by ``NativeSortformerDiarizer``. This stream never owns
    an audio device and never changes JARVIS authority. Callers may inspect live
    frame probabilities after every push, exactly as supported by NVIDIA's C ABI.
    """

    def __init__(self, diarizer: NativeSortformerDiarizer) -> None:
        model = getattr(diarizer, "_model", None)
        if model is None or not model.value:
            raise SortformerNativeError("Sortformer model is closed")
        self._diarizer = diarizer
        self._stream = ctypes.c_void_p()
        diarizer._check(  # noqa: SLF001 - same-package ABI adapter
            diarizer._lib.nemo_speech_diar_stream_open(  # noqa: SLF001
                model,
                ctypes.byref(self._stream),
            ),
            "nemo_speech_diar_stream_open",
        )
        if not self._stream.value:
            raise SortformerNativeError(
                "NeMo-Speech.cpp returned a null diarization stream"
            )
        self._sample_rate: int | None = None
        self._samples_pushed = 0
        self._finished = False

    @property
    def audio_seconds_total(self) -> float:
        if self._sample_rate is None or self._sample_rate <= 0:
            return 0.0
        return float(self._samples_pushed / self._sample_rate)

    def push(self, samples: np.ndarray, *, sample_rate: int) -> SortformerLivePush:
        if not self._stream.value:
            raise SortformerNativeError("Sortformer live stream is closed")
        if self._finished:
            raise SortformerNativeError("Sortformer live stream is already finished")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self._sample_rate is None:
            self._sample_rate = sample_rate
        elif sample_rate != self._sample_rate:
            raise ValueError(
                "sample_rate cannot change within a Sortformer live stream"
            )

        audio = _to_float32_mono(samples)
        if audio.size == 0:
            raise ValueError("audio must not be empty")
        started = time.perf_counter()
        self._diarizer._check(  # noqa: SLF001
            self._diarizer._lib.nemo_speech_diar_stream_push_f32(  # noqa: SLF001
                self._stream,
                audio.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                audio.size,
                sample_rate,
            ),
            "nemo_speech_diar_stream_push_f32",
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._samples_pushed += int(audio.size)
        return SortformerLivePush(
            audio_seconds_total=self.audio_seconds_total,
            push_latency_ms=latency_ms,
            snapshot=self.snapshot(),
        )

    def snapshot(self) -> SortformerLiveSnapshot:
        if not self._stream.value:
            raise SortformerNativeError("Sortformer live stream is closed")
        lib = self._diarizer._lib  # noqa: SLF001
        frame_count = int(lib.nemo_speech_diar_frame_count(self._stream))
        frame_start = int(lib.nemo_speech_diar_frame_probs_start(self._stream))
        retained_frames = frame_count - frame_start
        if retained_frames < 0:
            raise SortformerNativeError("invalid retained Sortformer frame range")
        probabilities = np.empty(
            (retained_frames, self._diarizer.num_speakers),
            dtype=np.float32,
        )
        if probabilities.size:
            self._diarizer._check(  # noqa: SLF001
                lib.nemo_speech_diar_frame_probs(
                    self._stream,
                    probabilities.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    probabilities.size,
                ),
                "nemo_speech_diar_frame_probs",
            )
        return SortformerLiveSnapshot(
            frame_start=frame_start,
            frame_count=frame_count,
            num_speakers=self._diarizer.num_speakers,
            seconds_per_frame=self._diarizer.seconds_per_frame,
            probabilities=probabilities,
        )

    def finish(self) -> SortformerLiveSnapshot:
        if not self._stream.value:
            raise SortformerNativeError("Sortformer live stream is closed")
        if not self._finished:
            self._diarizer._check(  # noqa: SLF001
                self._diarizer._lib.nemo_speech_diar_stream_finish(  # noqa: SLF001
                    self._stream
                ),
                "nemo_speech_diar_stream_finish",
            )
            self._finished = True
        return self.snapshot()

    def close(self) -> None:
        if self._stream.value:
            self._diarizer._lib.nemo_speech_diar_stream_close(  # noqa: SLF001
                self._stream
            )
            self._stream.value = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.close()
