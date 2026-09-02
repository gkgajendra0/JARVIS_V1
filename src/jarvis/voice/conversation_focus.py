"""Benchmark-only competing-speech focus boundary for JARVIS conversation audio.

Security/identity evidence must continue to consume the unmodified canonical mixed
Pocket3 PCM.  This module exists only to evaluate a separate conversation-focus
branch before wake/turn-taking/provider integration is considered.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from livekit import rtc


class ConversationFocusUnavailable(RuntimeError):
    pass


class _FrameProcessor(Protocol):
    def _process(self, frame: rtc.AudioFrame) -> rtc.AudioFrame: ...

    def _close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ConversationFocusRun:
    samples: np.ndarray
    audio_seconds: float
    processing_seconds: float
    realtime_factor: float
    frame_latencies_ms: tuple[float, ...]


def build_hush_focus_processor(*, strength: float) -> _FrameProcessor:
    """Build the pinned optional Hush processor without changing production audio."""
    if not 0.0 <= strength <= 1.0:
        raise ValueError("conversation-focus strength must be in [0, 1]")
    try:
        from livekit.plugins import hush
    except ImportError as exc:
        raise ConversationFocusUnavailable(
            "livekit-plugins-hush is required for the focus benchmark; install "
            'the optional extra with: pip install -e ".[conversation-focus-benchmark]"'
        ) from exc
    return hush.noise_suppression(
        strength=strength,
        atten_lim_db=100.0,
        debug_logging=False,
    )


def process_canonical_pcm(
    samples: np.ndarray,
    *,
    sample_rate: int,
    processor: _FrameProcessor,
    frame_ms: int = 10,
) -> ConversationFocusRun:
    """Process memory-only canonical PCM through a LiveKit FrameProcessor.

    The processor receives the same 10 ms mono int16 frame shape used by the
    accepted 48 kHz MediaDevices path.  Output is returned only in memory.
    """
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.dtype != np.int16 or pcm.size == 0:
        raise ValueError("conversation focus requires non-empty 1-D int16 PCM")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if frame_ms <= 0:
        raise ValueError("frame_ms must be positive")

    frame_samples = round(sample_rate * frame_ms / 1000.0)
    if frame_samples <= 0:
        raise ValueError("conversation-focus frame size is invalid")

    outputs: list[np.ndarray] = []
    latencies: list[float] = []
    started = time.perf_counter()
    try:
        for offset in range(0, pcm.size, frame_samples):
            chunk = pcm[offset : offset + frame_samples]
            original_size = int(chunk.size)
            if original_size < frame_samples:
                chunk = np.pad(chunk, (0, frame_samples - original_size))
            frame = rtc.AudioFrame(
                data=np.ascontiguousarray(chunk, dtype=np.int16).tobytes(),
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=frame_samples,
            )
            frame_started = time.perf_counter()
            focused = processor._process(frame)
            latencies.append((time.perf_counter() - frame_started) * 1000.0)
            if focused.sample_rate != sample_rate or focused.num_channels != 1:
                raise ConversationFocusUnavailable(
                    "focus processor changed canonical sample rate/channel contract"
                )
            focused_pcm = np.frombuffer(bytes(focused.data), dtype=np.int16)
            if focused_pcm.size < original_size:
                raise ConversationFocusUnavailable(
                    "focus processor returned fewer samples than the canonical frame"
                )
            outputs.append(focused_pcm[:original_size].copy())
    finally:
        processor._close()

    processing_seconds = time.perf_counter() - started
    output = np.concatenate(outputs)
    if output.size != pcm.size:
        raise ConversationFocusUnavailable(
            "focus processor changed canonical PCM sample count"
        )
    audio_seconds = pcm.size / sample_rate
    return ConversationFocusRun(
        samples=output,
        audio_seconds=audio_seconds,
        processing_seconds=processing_seconds,
        realtime_factor=processing_seconds / audio_seconds,
        frame_latencies_ms=tuple(latencies),
    )
