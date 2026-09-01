"""Canonical JARVIS audio runtime backed by paired GStreamer PCM.

The paired sensor source owns the physical Pocket 3 microphone and Tribit playback
inside one GStreamer clock domain. GStreamer's WebRTC AEC produces the canonical
conversation PCM; raw paired PCM remains separate for synchronized active-speaker
analysis. No PortAudio device and no Python-side reverse-stream delay estimator are
used by this runtime.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from livekit import rtc
from livekit.agents.voice import io

from jarvis.sensors.gstreamer_av import GStreamerPairedAVSource
from jarvis.voice.audio import (
    DEVICE_CHANNELS,
    DEVICE_SAMPLE_RATE,
    FRAME_SAMPLES,
    SessionAudioInput,
)
from jarvis.voice.wakeword import LiveKitWakeDetector

_NATIVE_QUEUE_CAPACITY = 500
_FRAME_SECONDS = FRAME_SAMPLES / DEVICE_SAMPLE_RATE
_FRAME_BYTES = FRAME_SAMPLES * 2
_PLAYBACK_SETTLE_SECONDS = 0.12


@dataclass(frozen=True, slots=True)
class _TimedAudioFrame:
    frame: rtc.AudioFrame
    observed_at_monotonic: float


@dataclass(slots=True)
class _PlaybackSegment:
    samples: int
    started_at_wall: float
    started_at_monotonic: float
    generation: int
    completed: bool = False


class GStreamerPairedAudioOutput(io.AudioOutput):
    """LiveKit output sink backed by the paired GStreamer playback/AEC branch."""

    def __init__(self, source: GStreamerPairedAVSource) -> None:
        super().__init__(
            label="JARVIS GStreamer speaker",
            capabilities=io.AudioOutputCapabilities(pause=True),
            sample_rate=DEVICE_SAMPLE_RATE,
        )
        self._source = source
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._paused = False
        self._resampler: rtc.AudioResampler | None = None
        self._resampler_input_rate: int | None = None
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0
        self._generation = 0
        self._segments: list[_PlaybackSegment] = []

    def start(self) -> None:
        if self._loop is not None:
            raise RuntimeError("paired GStreamer audio output is already started")
        if not self._source.running or not self._source.playback_enabled:
            raise RuntimeError("paired GStreamer playback/AEC branch is not running")
        self._loop = asyncio.get_running_loop()

    def _frames_at_canonical_rate(self, frame: rtc.AudioFrame) -> list[rtc.AudioFrame]:
        if frame.num_channels != DEVICE_CHANNELS:
            raise ValueError("paired GStreamer output requires mono audio")
        if frame.sample_rate == DEVICE_SAMPLE_RATE:
            return [frame]
        if self._resampler_input_rate != frame.sample_rate:
            self._resampler = rtc.AudioResampler(
                input_rate=frame.sample_rate,
                output_rate=DEVICE_SAMPLE_RATE,
                num_channels=DEVICE_CHANNELS,
            )
            self._resampler_input_rate = frame.sample_rate
        assert self._resampler is not None
        return self._resampler.push(frame)

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        if self._closed:
            return
        while self._paused and not self._closed:
            await asyncio.sleep(0.01)
        if self._closed:
            return

        await super().capture_frame(frame)
        for canonical in self._frames_at_canonical_rate(frame):
            playback_started_at: float | None = None
            if self._current_samples == 0:
                self._current_started_at_wall = time.time()
                self._current_started_at_monotonic = time.monotonic()
                playback_started_at = self._current_started_at_wall

            await asyncio.to_thread(
                self._source.push_playback_pcm,
                bytes(canonical.data),
                sample_rate=DEVICE_SAMPLE_RATE,
                num_channels=DEVICE_CHANNELS,
                samples_per_channel=canonical.samples_per_channel,
            )
            self._current_samples += canonical.samples_per_channel
            if playback_started_at is not None:
                self.on_playback_started(created_at=playback_started_at)

    def flush(self) -> None:
        super().flush()
        if self._current_samples <= 0:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        segment = _PlaybackSegment(
            samples=self._current_samples,
            started_at_wall=self._current_started_at_wall,
            started_at_monotonic=self._current_started_at_monotonic,
            generation=self._generation,
        )
        self._segments.append(segment)
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0

        duration = segment.samples / DEVICE_SAMPLE_RATE
        elapsed = max(0.0, time.monotonic() - segment.started_at_monotonic)
        remaining = max(0.01, duration - elapsed + _PLAYBACK_SETTLE_SECONDS)
        loop.call_later(remaining, self._finish_segment, segment)

    def _finish_segment(self, segment: _PlaybackSegment) -> None:
        if (
            segment.completed
            or segment.generation != self._generation
            or self._closed
        ):
            return
        segment.completed = True
        if segment in self._segments:
            self._segments.remove(segment)
        self.on_playback_finished(
            playback_position=segment.samples / DEVICE_SAMPLE_RATE,
            interrupted=False,
        )

    def clear_buffer(self) -> None:
        had_current = self._current_samples > 0
        current_position = 0.0
        if had_current:
            duration = self._current_samples / DEVICE_SAMPLE_RATE
            elapsed = max(0.0, time.monotonic() - self._current_started_at_monotonic)
            current_position = min(duration, elapsed)

        pending = [segment for segment in self._segments if not segment.completed]
        self._generation += 1
        self._segments.clear()
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0
        self._source.flush_playback()

        if had_current:
            super().flush()
            self.on_playback_finished(
                playback_position=current_position,
                interrupted=True,
            )
        for segment in pending:
            segment.completed = True
            duration = segment.samples / DEVICE_SAMPLE_RATE
            elapsed = max(0.0, time.monotonic() - segment.started_at_monotonic)
            self.on_playback_finished(
                playback_position=min(duration, elapsed),
                interrupted=True,
            )

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self.clear_buffer()
        self._closed = True
        self._loop = None


class PairedAudioRuntime:
    """Route GStreamer AEC-cleaned DJI PCM to wake and conversation."""

    def __init__(
        self,
        detector: LiveKitWakeDetector,
        *,
        av_source: GStreamerPairedAVSource,
        pre_roll_seconds: float,
        ring_buffer_seconds: float,
    ) -> None:
        if not 0 <= pre_roll_seconds <= ring_buffer_seconds:
            raise ValueError("pre-roll must fit inside the audio ring buffer")
        self.detector = detector
        self._av_source = av_source
        self._pre_roll_seconds = pre_roll_seconds
        self._ring_buffer_seconds = ring_buffer_seconds

        self._ring: deque[_TimedAudioFrame] = deque()
        self._ring_samples = 0
        self._active_input: SessionAudioInput | None = None
        self._overflow_handler: Callable[[], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.output: GStreamerPairedAudioOutput | None = None
        self._started = False

        self._native_lock = threading.Lock()
        self._native_queue: deque[tuple[bytes, float]] = deque()
        self._native_drain_scheduled = False
        self._native_drop_count = 0
        self._pending_pcm = bytearray()
        self._pending_start_monotonic: float | None = None

    @property
    def native_drop_count(self) -> int:
        return self._native_drop_count

    def set_overflow_handler(self, callback: Callable[[], None]) -> None:
        self._overflow_handler = callback

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("paired audio runtime is already started")
        if not self._av_source.running:
            raise RuntimeError("paired AV source must be running before paired audio")
        if not self._av_source.playback_enabled:
            raise RuntimeError("paired AV source has no full-duplex playback/AEC branch")

        self._loop = asyncio.get_running_loop()
        self.output = GStreamerPairedAudioOutput(self._av_source)
        self.output.start()
        self.detector.enable()
        self._started = True

    def feed_clean_pcm(
        self,
        data: bytes | bytearray | memoryview,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        observed_at_monotonic: float,
    ) -> None:
        """Accept WebRTC-AEC-cleaned PCM from GStreamer's native callback thread."""
        if sample_rate != DEVICE_SAMPLE_RATE:
            raise ValueError(
                f"paired canonical audio must be {DEVICE_SAMPLE_RATE} Hz, got {sample_rate}"
            )
        if num_channels != DEVICE_CHANNELS:
            raise ValueError("paired canonical audio must be mono")
        if samples_per_channel <= 0:
            raise ValueError("paired canonical audio frame size must be positive")
        if observed_at_monotonic < 0:
            raise ValueError("paired canonical audio timestamp must be non-negative")
        payload = bytes(data)
        if len(payload) != samples_per_channel * 2:
            raise ValueError("paired canonical PCM byte length does not match int16 mono")

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        schedule_drain = False
        with self._native_lock:
            if len(self._native_queue) >= _NATIVE_QUEUE_CAPACITY:
                self._native_queue.popleft()
                self._native_drop_count += 1
            self._native_queue.append((payload, observed_at_monotonic))
            if not self._native_drain_scheduled:
                self._native_drain_scheduled = True
                schedule_drain = True
        if schedule_drain:
            loop.call_soon_threadsafe(self._drain_native_queue)

    def _drain_native_queue(self) -> None:
        with self._native_lock:
            items = tuple(self._native_queue)
            self._native_queue.clear()
            self._native_drain_scheduled = False
        for payload, observed_at in items:
            self._ingest_pcm(payload, observed_at)

    def _ingest_pcm(self, payload: bytes, observed_at_monotonic: float) -> None:
        if self._pending_pcm and self._pending_start_monotonic is not None:
            expected = self._pending_start_monotonic + len(self._pending_pcm) / (
                DEVICE_SAMPLE_RATE * 2
            )
            if abs(observed_at_monotonic - expected) > 0.05:
                self._pending_pcm.clear()
                self._pending_start_monotonic = None

        if self._pending_start_monotonic is None:
            self._pending_start_monotonic = observed_at_monotonic
        self._pending_pcm.extend(payload)

        while len(self._pending_pcm) >= _FRAME_BYTES:
            frame_start = self._pending_start_monotonic
            if frame_start is None:
                return
            chunk = bytearray(self._pending_pcm[:_FRAME_BYTES])
            del self._pending_pcm[:_FRAME_BYTES]
            self._pending_start_monotonic = (
                frame_start + _FRAME_SECONDS if self._pending_pcm else None
            )
            frame = rtc.AudioFrame(
                data=chunk,
                sample_rate=DEVICE_SAMPLE_RATE,
                num_channels=DEVICE_CHANNELS,
                samples_per_channel=FRAME_SAMPLES,
            )
            self._route(frame, frame_start)

    def _route(
        self,
        frame: rtc.AudioFrame,
        observed_at_monotonic: float,
    ) -> None:
        self._append_ring(frame, observed_at_monotonic=observed_at_monotonic)
        active_input = self._active_input
        if active_input is not None:
            if (
                not active_input.push_frame(
                    frame,
                    observed_at_monotonic=observed_at_monotonic,
                )
                and self._overflow_handler is not None
            ):
                self._overflow_handler()
        else:
            self.detector.feed(frame)

    def _append_ring(
        self,
        frame: rtc.AudioFrame,
        *,
        observed_at_monotonic: float,
    ) -> None:
        self._ring.append(
            _TimedAudioFrame(
                frame=frame,
                observed_at_monotonic=observed_at_monotonic,
            )
        )
        self._ring_samples += frame.samples_per_channel
        limit = int(self._ring_buffer_seconds * DEVICE_SAMPLE_RATE)
        while (
            self._ring
            and self._ring_samples - self._ring[0].frame.samples_per_channel >= limit
        ):
            self._ring_samples -= self._ring.popleft().frame.samples_per_channel

    def activate_session(self, session_input: SessionAudioInput) -> None:
        if self._active_input is not None:
            raise RuntimeError("a voice session already owns routed microphone audio")
        self.detector.disable(clear_buffer=False)
        self._active_input = session_input

        pre_roll_samples = int(self._pre_roll_seconds * DEVICE_SAMPLE_RATE)
        selected: deque[_TimedAudioFrame] = deque()
        selected_samples = 0
        for timed_frame in reversed(self._ring):
            selected.appendleft(timed_frame)
            selected_samples += timed_frame.frame.samples_per_channel
            if selected_samples >= pre_roll_samples:
                break

        for timed_frame in selected:
            if not session_input.push_frame(
                timed_frame.frame,
                observed_at_monotonic=timed_frame.observed_at_monotonic,
            ):
                self._active_input = None
                raise RuntimeError(
                    "session audio queue overflowed while adding paired pre-roll"
                )

    def deactivate_session(self) -> None:
        active = self._active_input
        self._active_input = None
        if active is not None:
            active.close()

    async def resume_wake(self, *, cooldown_seconds: float) -> None:
        self.deactivate_session()
        self._ring.clear()
        self._ring_samples = 0
        if cooldown_seconds:
            await asyncio.sleep(cooldown_seconds)
        self.detector.enable()

    async def aclose(self) -> None:
        self.deactivate_session()
        self.detector.disable()
        self._started = False
        self._loop = None
        with self._native_lock:
            self._native_queue.clear()
            self._native_drain_scheduled = False
        self._pending_pcm.clear()
        self._pending_start_monotonic = None
        if self.output is not None:
            await self.output.aclose()
            self.output = None
        await self.detector.aclose()
