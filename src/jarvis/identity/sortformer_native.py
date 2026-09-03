from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import numpy as np


class SortformerNativeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SortformerGeometry:
    """Explicit NeMo-Speech.cpp streaming geometry overrides.

    Values are expressed in Sortformer encoder frames. The current v2 model emits
    one frame every 80 ms. These overrides are benchmark inputs only until a real
    JARVIS-machine latency/quality bake-off accepts one configuration.
    """

    name: str
    chunk_frames: int
    right_context_frames: int
    left_context_frames: int
    fifo_frames: int
    spkcache_frames: int
    update_period_frames: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Sortformer geometry name must not be empty")
        if self.chunk_frames < 1:
            raise ValueError("chunk_frames must be positive")
        if self.right_context_frames < 0 or self.left_context_frames < 0:
            raise ValueError("Sortformer context frames must be non-negative")
        if self.fifo_frames < 0:
            raise ValueError("fifo_frames must be non-negative")
        if self.spkcache_frames < 1 or self.update_period_frames < 1:
            raise ValueError("Sortformer cache/update frames must be positive")

    @property
    def input_buffer_frames(self) -> int:
        return self.chunk_frames + self.right_context_frames


# Published nvidia/diar_streaming_sortformer_4spk-v2 operating points.
# Model-card latency is input buffering only and excludes compute time.
NVIDIA_SORTFORMER_LOW_LATENCY = SortformerGeometry(
    name="nvidia_low_latency_1p04s",
    chunk_frames=6,
    right_context_frames=7,
    left_context_frames=0,
    fifo_frames=188,
    spkcache_frames=188,
    update_period_frames=144,
)
NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY = SortformerGeometry(
    name="nvidia_ultra_low_latency_0p32s",
    chunk_frames=3,
    right_context_frames=1,
    left_context_frames=0,
    fifo_frames=188,
    spkcache_frames=188,
    update_period_frames=144,
)


class _DiarModelConfig(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_size_t),
        ("model_path", ctypes.c_char_p),
        ("gpu", ctypes.c_int32),
        ("preset", ctypes.c_char_p),
        ("chunk_frames", ctypes.c_int32),
        ("right_context_frames", ctypes.c_int32),
        ("left_context_frames", ctypes.c_int32),
        ("fifo_frames", ctypes.c_int32),
        ("spkcache_frames", ctypes.c_int32),
        ("update_period_frames", ctypes.c_int32),
    ]


@dataclass(frozen=True, slots=True)
class SortformerRun:
    probabilities: np.ndarray
    frame_count: int
    num_speakers: int
    seconds_per_frame: float
    audio_seconds: float
    inference_seconds: float
    realtime_factor: float
    push_latencies_ms: tuple[float, ...]


def find_nemo_speech_library(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)

    env_path = os.environ.get("JARVIS_NEMO_SPEECH_DLL")
    if env_path:
        candidates.append(Path(env_path))

    found = ctypes.util.find_library("nemo_speech_asr_c")
    if found:
        candidates.append(Path(found))

    executable = shutil.which("nemo-speech")
    if executable:
        binary_dir = Path(executable).resolve().parent
        candidates.extend(
            (
                binary_dir / "nemo_speech_asr_c.dll",
                binary_dir / "libnemo_speech_asr_c.so",
                binary_dir / "libnemo_speech_asr_c.dylib",
            )
        )

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        binary_dir = Path(local_app_data) / "Programs" / "NeMoSpeech" / "bin"
        candidates.append(binary_dir / "nemo_speech_asr_c.dll")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise SortformerNativeError(
        "NeMo-Speech.cpp C ABI library was not found. Install the native runtime or "
        "set JARVIS_NEMO_SPEECH_DLL to nemo_speech_asr_c.dll."
    )


def resolve_sortformer_model(explicit: Path | None = None) -> Path:
    candidate = explicit
    if candidate is None:
        env_path = os.environ.get("JARVIS_SORTFORMER_MODEL_PATH")
        candidate = Path(env_path) if env_path else None
    if candidate is None or not candidate.is_file():
        raise SortformerNativeError(
            "Sortformer GGUF model was not found. Pass --model or set "
            "JARVIS_SORTFORMER_MODEL_PATH."
        )
    return candidate.resolve()


def _to_float32_mono(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples)
    if array.ndim != 1:
        array = array.reshape(-1)
    if np.issubdtype(array.dtype, np.integer):
        info = np.iinfo(array.dtype)
        scale = float(max(abs(info.min), info.max))
        array = array.astype(np.float32) / scale
    else:
        array = array.astype(np.float32, copy=False)
    if not np.isfinite(array).all():
        raise ValueError("audio contains non-finite values")
    return np.ascontiguousarray(np.clip(array, -1.0, 1.0), dtype=np.float32)


class NativeSortformerDiarizer:
    """Thin ctypes wrapper over NeMo-Speech.cpp's stable standalone diarization ABI.

    This adapter is benchmark-only until real JARVIS-machine acceptance. It never
    owns a microphone; callers provide already-captured canonical PCM.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        library_path: Path | None = None,
        gpu: int = 0,
        preset: str = "streaming",
        geometry: SortformerGeometry | None = None,
    ) -> None:
        if not model_path.is_file():
            raise SortformerNativeError(
                f"Sortformer model does not exist: {model_path}"
            )
        if not preset:
            raise ValueError("preset must not be empty")

        self.model_path = model_path.resolve()
        self.library_path = find_nemo_speech_library(library_path)
        self.geometry = geometry
        self._dll_dir_handle = None
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(str(self.library_path.parent))
        loader = ctypes.WinDLL if sys.platform == "win32" else ctypes.CDLL
        try:
            self._lib = loader(str(self.library_path))
        except OSError as exc:
            self._close_dll_directory()
            raise SortformerNativeError(
                f"failed to load NeMo-Speech.cpp library {self.library_path}: {exc}"
            ) from exc

        self._configure_abi()
        self._model = ctypes.c_void_p()
        model_path_bytes = os.fsencode(self.model_path)
        preset_bytes = preset.encode("utf-8")
        config = _DiarModelConfig(
            size=ctypes.sizeof(_DiarModelConfig),
            model_path=model_path_bytes,
            gpu=gpu,
            preset=preset_bytes,
            chunk_frames=geometry.chunk_frames if geometry is not None else 0,
            right_context_frames=(
                geometry.right_context_frames if geometry is not None else 0
            ),
            left_context_frames=(
                geometry.left_context_frames if geometry is not None else -1
            ),
            fifo_frames=geometry.fifo_frames if geometry is not None else 0,
            spkcache_frames=geometry.spkcache_frames if geometry is not None else 0,
            update_period_frames=(
                geometry.update_period_frames if geometry is not None else 0
            ),
        )
        started = time.perf_counter()
        status = self._lib.nemo_speech_diar_create(
            ctypes.byref(config),
            ctypes.byref(self._model),
        )
        self.model_load_seconds = time.perf_counter() - started
        self._check(status, "nemo_speech_diar_create")
        if not self._model.value:
            self.close()
            raise SortformerNativeError(
                "NeMo-Speech.cpp returned a null diarization model"
            )

        self.num_speakers = int(self._lib.nemo_speech_diar_num_speakers(self._model))
        self.seconds_per_frame = float(
            self._lib.nemo_speech_diar_seconds_per_frame(self._model)
        )
        if self.num_speakers < 2 or self.seconds_per_frame <= 0.0:
            self.close()
            raise SortformerNativeError(
                "invalid Sortformer model metadata from runtime"
            )

    def _configure_abi(self) -> None:
        lib = self._lib
        lib.nemo_speech_asr_last_error.argtypes = []
        lib.nemo_speech_asr_last_error.restype = ctypes.c_char_p
        lib.nemo_speech_asr_version.argtypes = []
        lib.nemo_speech_asr_version.restype = ctypes.c_char_p

        lib.nemo_speech_diar_create.argtypes = [
            ctypes.POINTER(_DiarModelConfig),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.nemo_speech_diar_create.restype = ctypes.c_int
        lib.nemo_speech_diar_destroy.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_destroy.restype = None
        lib.nemo_speech_diar_num_speakers.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_num_speakers.restype = ctypes.c_int32
        lib.nemo_speech_diar_seconds_per_frame.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_seconds_per_frame.restype = ctypes.c_double

        lib.nemo_speech_diar_stream_open.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.nemo_speech_diar_stream_open.restype = ctypes.c_int
        lib.nemo_speech_diar_stream_push_f32.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.c_int32,
        ]
        lib.nemo_speech_diar_stream_push_f32.restype = ctypes.c_int
        lib.nemo_speech_diar_stream_finish.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_stream_finish.restype = ctypes.c_int
        lib.nemo_speech_diar_stream_close.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_stream_close.restype = None
        lib.nemo_speech_diar_frame_count.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_frame_count.restype = ctypes.c_int64
        lib.nemo_speech_diar_frame_probs_start.argtypes = [ctypes.c_void_p]
        lib.nemo_speech_diar_frame_probs_start.restype = ctypes.c_int64
        lib.nemo_speech_diar_frame_probs.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
        ]
        lib.nemo_speech_diar_frame_probs.restype = ctypes.c_int

    @property
    def runtime_version(self) -> str:
        value = self._lib.nemo_speech_asr_version()
        return value.decode("utf-8", errors="replace") if value else "unknown"

    def _last_error(self) -> str:
        value = self._lib.nemo_speech_asr_last_error()
        return value.decode("utf-8", errors="replace") if value else "unknown error"

    def _check(self, status: int, operation: str) -> None:
        if int(status) != 0:
            raise SortformerNativeError(f"{operation} failed: {self._last_error()}")

    def run_streaming(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
        push_seconds: float = 0.32,
    ) -> SortformerRun:
        if not self._model.value:
            raise SortformerNativeError("Sortformer model is closed")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if push_seconds <= 0.0:
            raise ValueError("push_seconds must be positive")

        audio = _to_float32_mono(samples)
        if audio.size == 0:
            raise ValueError("audio must not be empty")
        audio_seconds = float(audio.size / sample_rate)
        push_size = max(1, round(sample_rate * push_seconds))
        stream = ctypes.c_void_p()
        self._check(
            self._lib.nemo_speech_diar_stream_open(
                self._model,
                ctypes.byref(stream),
            ),
            "nemo_speech_diar_stream_open",
        )
        if not stream.value:
            raise SortformerNativeError(
                "NeMo-Speech.cpp returned a null diarization stream"
            )

        push_latencies: list[float] = []
        started = time.perf_counter()
        try:
            for offset in range(0, audio.size, push_size):
                chunk = np.ascontiguousarray(audio[offset : offset + push_size])
                chunk_started = time.perf_counter()
                self._check(
                    self._lib.nemo_speech_diar_stream_push_f32(
                        stream,
                        chunk.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        chunk.size,
                        sample_rate,
                    ),
                    "nemo_speech_diar_stream_push_f32",
                )
                push_latencies.append((time.perf_counter() - chunk_started) * 1000.0)
            self._check(
                self._lib.nemo_speech_diar_stream_finish(stream),
                "nemo_speech_diar_stream_finish",
            )
            inference_seconds = time.perf_counter() - started
            frame_count = int(self._lib.nemo_speech_diar_frame_count(stream))
            frame_start = int(self._lib.nemo_speech_diar_frame_probs_start(stream))
            retained_frames = frame_count - frame_start
            if retained_frames < 0:
                raise SortformerNativeError("invalid retained Sortformer frame range")
            probabilities = np.empty(
                (retained_frames, self.num_speakers),
                dtype=np.float32,
            )
            if probabilities.size:
                self._check(
                    self._lib.nemo_speech_diar_frame_probs(
                        stream,
                        probabilities.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        probabilities.size,
                    ),
                    "nemo_speech_diar_frame_probs",
                )
        finally:
            self._lib.nemo_speech_diar_stream_close(stream)

        realtime_factor = (
            inference_seconds / audio_seconds if audio_seconds else float("inf")
        )
        return SortformerRun(
            probabilities=probabilities,
            frame_count=frame_count,
            num_speakers=self.num_speakers,
            seconds_per_frame=self.seconds_per_frame,
            audio_seconds=audio_seconds,
            inference_seconds=inference_seconds,
            realtime_factor=realtime_factor,
            push_latencies_ms=tuple(push_latencies),
        )

    def close(self) -> None:
        model = getattr(self, "_model", None)
        if model is not None and model.value:
            self._lib.nemo_speech_diar_destroy(model)
            model.value = None
        self._close_dll_directory()

    def _close_dll_directory(self) -> None:
        handle = getattr(self, "_dll_dir_handle", None)
        if handle is not None:
            handle.close()
            self._dll_dir_handle = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.close()
