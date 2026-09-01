"""Canonical JARVIS audio runtime backed by paired GStreamer PCM.

The paired sensor source owns the physical microphone once. This runtime accepts
that PCM from GStreamer's callback, applies WebRTC APM, and routes the processed
frames to local wake detection or the active realtime conversation. No PortAudio
input device is opened here; the only PortAudio device owned by this runtime is
the configured output speaker.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from livekit import rtc

from jarvis.voice.audio import (
    DEVICE_CHANNELS,
    DEVICE_SAMPLE_RATE,
    FRAME_SAMPLES,
    LocalAudioOutput,
    LocalAudioRuntime,
    SessionAudioInput,
)
from jarvis.voice.wakeword import LiveKitWakeDetector

_NATIVE_QUEUE_CAPACITY = 500
_FRAME_SECONDS = FRAME_SAMPLES / DEVICE_SAMPLE_RATE
_FRAME_BYTES = FRAME_SAMPLES * 2


@dataclass(frozen=True, slots=True)
class _TimedAudioFrame:
    frame: rtc.AudioFrame
    observed_at_monotonic: float


class _ExternalAecDelayEstimator:
    """Combine physical render delay with capture-to-APM processing delay."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._output_delay_seconds = 0.0

    def set_output_delay(self, seconds: float) -> None:
        if not math.isfinite(seconds):
            return
        with self._lock:
            self._output_delay_seconds = max(0.0, seconds)

    def stream_delay_ms(self, observed_at_monotonic: float) -> int:
        with self._lock:
            output_delay = self._output_delay_seconds
        capture_to_process = max(0.0, self._clock() - observed_at_monotonic)
        total_seconds = min(1.0, output_delay + capture_to_process)
        return max(0, round(total_seconds * 1000))


class PairedAudioRuntime:
    """Route one GStreamer-owned DJI microphone to wake and conversation."""

    def __init__(
        self,
        detector: LiveKitWakeDetector,
        *,
        output_device_name: str | None,
        pre_roll_seconds: float,
        ring_buffer_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        apm_factory: Callable[..., Any] = rtc.AudioProcessingModule,
    ) -> None:
        if not 0 <= pre_roll_seconds <= ring_buffer_seconds:
            raise ValueError("pre-roll must fit inside the audio ring buffer")
        self.detector = detector
        self._output_device_name = output_device_name
        self._pre_roll_seconds = pre_roll_seconds
        self._ring_buffer_seconds = ring_buffer_seconds
        self._clock = clock
        self._apm_factory = apm_factory

        self._ring: deque[_TimedAudioFrame] = deque()
        self._ring_samples = 0
        self._active_input: SessionAudioInput | None = None
        self._overflow_handler: Callable[[], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._apm: Any = None
        self._delay_estimator = _ExternalAecDelayEstimator(clock=clock)
        self.output: LocalAudioOutput | None = None
        self._started = False

        self._native_lock = threading.Lock()
        self._native_queue: deque[tuple[bytes, float]] = deque()
        self._native_drain_scheduled = False
        self._native_drop_count = 0
        self._pending_pcm = bytearray()
        self._pending_start_monotonic: float | None = None
        self._apm_error_count = 0

    @property
    def native_drop_count(self) -> int:
        return self._native_drop_count

    @property
    def apm_error_count(self) -> int:
        return self._apm_error_count

    def set_overflow_handler(self, callback: Callable[[], None]) -> None:
        self._overflow_handler = callback

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("paired audio runtime is already started")
        self._loop = asyncio.get_running_loop()

        media_devices = rtc.MediaDevices(
            input_sample_rate=DEVICE_SAMPLE_RATE,
            output_sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            blocksize=FRAME_SAMPLES,
        )
        output_devices = LocalAudioRuntime._attach_host_api_names(
            media_devices.list_output_devices()
        )
        output_device = LocalAudioRuntime._resolve_device(
            output_devices,
            self._output_device_name,
            kind="output",
        )
        LocalAudioRuntime._log_resolved_device(
            output_devices,
            output_device,
            kind="output",
        )
        output_sample_rate = LocalAudioRuntime._select_output_sample_rate(output_device)

        self._apm = self._apm_factory(
            echo_cancellation=True,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=True,
        )
        self.output = LocalAudioOutput(
            output_device=output_device,
            apm=self._apm,
            delay_estimator=self._delay_estimator,
            output_sample_rate=output_sample_rate,
        )
        self.output.start()
        self.detector.enable()
        self._started = True

    def feed_external_pcm(
        self,
        data: bytes | bytearray | memoryview,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        observed_at_monotonic: float,
    ) -> None:
        """Accept paired PCM from GStreamer's native callback thread."""
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
            self._process_and_route(frame, frame_start)

    def _process_and_route(
        self,
        frame: rtc.AudioFrame,
        observed_at_monotonic: float,
    ) -> None:
        apm = self._apm
        if apm is None:
            return
        try:
            apm.set_stream_delay_ms(
                self._delay_estimator.stream_delay_ms(observed_at_monotonic)
            )
            apm.process_stream(frame)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._apm_error_count += 1
            return

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
        self._apm = None
        await self.detector.aclose()
