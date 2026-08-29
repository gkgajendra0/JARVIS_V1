"""Single-owner local audio routing for wake and realtime conversation."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from livekit import rtc
from livekit.agents.voice import io

from jarvis.voice.wakeword import LiveKitWakeDetector

DEVICE_SAMPLE_RATE = 48_000
DEVICE_CHANNELS = 1
FRAME_SIZE_MS = 10
FRAME_SAMPLES = DEVICE_SAMPLE_RATE * FRAME_SIZE_MS // 1000
_INPUT_CLOSED = object()


class SessionAudioInput(io.AudioInput):
    """Bounded queue that connects local PCM to one AgentSession."""

    def __init__(self, *, capacity_frames: int = 1_000) -> None:
        super().__init__(label="JARVIS local microphone")
        if capacity_frames <= 0:
            raise ValueError("audio input capacity must be positive")
        self._queue: asyncio.Queue[rtc.AudioFrame | object] = asyncio.Queue(
            maxsize=capacity_frames
        )
        self._closed = False

    def push_frame(self, frame: rtc.AudioFrame) -> bool:
        if self._closed or self._queue.full():
            return False
        self._queue.put_nowait(frame)
        return True

    async def __anext__(self) -> rtc.AudioFrame:
        item = await self._queue.get()
        if item is _INPUT_CLOSED:
            raise StopAsyncIteration
        return cast(rtc.AudioFrame, item)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(_INPUT_CLOSED)


@dataclass(slots=True)
class _OutputSegment:
    start_sample: int
    end_sample: int
    started_at: float


class LocalAudioOutput(io.AudioOutput):
    """LiveKit output sink with physical-playout and interruption accounting."""

    def __init__(
        self,
        *,
        output_device: int | None,
        apm: Any = None,
        delay_estimator: Any = None,
        sample_rate: int = DEVICE_SAMPLE_RATE,
    ) -> None:
        super().__init__(
            label="JARVIS local speaker",
            capabilities=io.AudioOutputCapabilities(pause=True),
            sample_rate=sample_rate,
        )
        self._output_device = output_device
        self._apm = apm
        self._delay_estimator = delay_estimator
        self._target_rate = sample_rate
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._segments: deque[_OutputSegment] = deque()
        self._current_start: int | None = None
        self._current_started_at = 0.0
        self._enqueued_samples = 0
        self._played_samples = 0
        self._paused = False
        self._closed = False
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resampler: rtc.AudioResampler | None = None
        self._resampler_input_rate: int | None = None
        self._timing_error_count = 0
        self._apm_error_count = 0

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("local audio output is already started")
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self._stream = sd.OutputStream(
            callback=self._playback_callback,
            dtype="int16",
            channels=DEVICE_CHANNELS,
            device=self._output_device,
            samplerate=self._target_rate,
            blocksize=FRAME_SAMPLES,
        )
        self._stream.start()

    def _playback_callback(
        self,
        outdata: np.ndarray,
        frame_count: int,
        time_info: Any,
        status: Any,
    ) -> None:
        del status
        bytes_needed = frame_count * 2
        actual_samples = 0
        with self._lock:
            if self._paused or not self._buffer:
                outdata.fill(0)
            else:
                available = min(len(self._buffer), bytes_needed)
                actual_samples = available // 2
                outdata[:actual_samples, 0] = np.frombuffer(
                    self._buffer[:available], dtype=np.int16
                )
                outdata[actual_samples:, 0] = 0
                del self._buffer[:available]
                self._played_samples += actual_samples

        try:
            output_delay = float(time_info.outputBufferDacTime - time_info.currentTime)
            if self._delay_estimator is not None:
                self._delay_estimator.set_output_delay(output_delay)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._timing_error_count += 1

        if self._apm is not None:
            for start in range(0, frame_count, FRAME_SAMPLES):
                chunk = outdata[start : start + FRAME_SAMPLES, 0]
                if len(chunk) != FRAME_SAMPLES:
                    break
                try:
                    self._apm.process_reverse_stream(
                        rtc.AudioFrame(
                            data=chunk.tobytes(),
                            sample_rate=self._target_rate,
                            num_channels=1,
                            samples_per_channel=FRAME_SAMPLES,
                        )
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    self._apm_error_count += 1

        if actual_samples and self._loop is not None:
            self._loop.call_soon_threadsafe(self._finish_played_segments)

    def _frames_at_target_rate(self, frame: rtc.AudioFrame) -> list[rtc.AudioFrame]:
        if frame.sample_rate == self._target_rate:
            return [frame]
        if self._resampler_input_rate != frame.sample_rate:
            self._resampler = rtc.AudioResampler(
                input_rate=frame.sample_rate,
                output_rate=self._target_rate,
                num_channels=1,
            )
            self._resampler_input_rate = frame.sample_rate
        assert self._resampler is not None
        return self._resampler.push(frame)

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        if self._closed:
            return
        if frame.num_channels != 1:
            raise ValueError("local output requires mono audio")
        await super().capture_frame(frame)
        target_frames = self._frames_at_target_rate(frame)
        playback_started_at: float | None = None
        with self._lock:
            if self._current_start is None:
                self._current_start = self._enqueued_samples
                self._current_started_at = time.time()
                playback_started_at = self._current_started_at
            for target in target_frames:
                self._buffer.extend(bytes(target.data))
                self._enqueued_samples += target.samples_per_channel
        if playback_started_at is not None:
            self.on_playback_started(created_at=playback_started_at)

    @property
    def timing_error_count(self) -> int:
        return self._timing_error_count

    @property
    def apm_error_count(self) -> int:
        return self._apm_error_count

    def flush(self) -> None:
        super().flush()
        with self._lock:
            if self._current_start is None:
                return
            self._segments.append(
                _OutputSegment(
                    start_sample=self._current_start,
                    end_sample=self._enqueued_samples,
                    started_at=self._current_started_at,
                )
            )
            self._current_start = None
        self._finish_played_segments()

    def _finish_played_segments(self) -> None:
        completed: list[_OutputSegment] = []
        with self._lock:
            while (
                self._segments and self._segments[0].end_sample <= self._played_samples
            ):
                completed.append(self._segments.popleft())
        for segment in completed:
            duration = (segment.end_sample - segment.start_sample) / self._target_rate
            self.on_playback_finished(
                playback_position=duration,
                interrupted=False,
            )

    def clear_buffer(self) -> None:
        interrupted: list[tuple[_OutputSegment, float]] = []
        with self._lock:
            if self._current_start is not None:
                super().flush()
                self._segments.append(
                    _OutputSegment(
                        start_sample=self._current_start,
                        end_sample=self._enqueued_samples,
                        started_at=self._current_started_at,
                    )
                )
                self._current_start = None
            self._buffer.clear()
            for segment in self._segments:
                played = max(
                    0,
                    min(self._played_samples, segment.end_sample)
                    - segment.start_sample,
                )
                interrupted.append((segment, played / self._target_rate))
            self._segments.clear()
            self._enqueued_samples = self._played_samples
        for _, position in interrupted:
            self.on_playback_finished(
                playback_position=position,
                interrupted=True,
            )

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.clear_buffer()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class LocalAudioRuntime:
    """Own one input/output pair and route processed audio by lifecycle state."""

    def __init__(
        self,
        detector: LiveKitWakeDetector,
        *,
        input_device_name: str | None,
        output_device_name: str | None,
        pre_roll_seconds: float,
        ring_buffer_seconds: float,
    ) -> None:
        if not 0 <= pre_roll_seconds <= ring_buffer_seconds:
            raise ValueError("pre-roll must fit inside the audio ring buffer")
        self.detector = detector
        self._input_device_name = input_device_name
        self._output_device_name = output_device_name
        self._pre_roll_seconds = pre_roll_seconds
        self._ring_buffer_seconds = ring_buffer_seconds
        self._ring: deque[rtc.AudioFrame] = deque()
        self._ring_samples = 0
        self._active_input: SessionAudioInput | None = None
        self._overflow_handler: Callable[[], None] | None = None
        self._media_devices: Any = None
        self._input_capture: Any = None
        self._input_track: Any = None
        self._input_stream: rtc.AudioStream | None = None
        self._router_task: asyncio.Task[None] | None = None
        self.output: LocalAudioOutput | None = None

    @staticmethod
    def _resolve_device(
        devices: list[dict[str, Any]],
        requested: str | None,
        *,
        kind: str,
    ) -> int | None:
        if requested is None:
            return None
        needle = requested.strip().casefold()
        if needle.startswith("index:"):
            index_text = needle.removeprefix("index:").strip()
            try:
                requested_index = int(index_text)
            except ValueError as exc:
                raise RuntimeError(
                    f"Configured {kind} device index is invalid: {requested}"
                ) from exc
            matches = [
                device for device in devices if int(device["index"]) == requested_index
            ]
            if not matches:
                raise RuntimeError(
                    f"Configured {kind} device index not found: {requested_index}"
                )
            return requested_index

        exact = [
            device for device in devices if str(device["name"]).casefold() == needle
        ]
        matches = exact or [
            device for device in devices if needle in str(device["name"]).casefold()
        ]
        if not matches:
            raise RuntimeError(f"Configured {kind} device not found: {requested}")
        if len(matches) > 1:
            choices = ", ".join(
                f"index:{device['index']} {device['name']} "
                f"(hostapi {device.get('hostapi', 'unknown')})"
                for device in matches
            )
            raise RuntimeError(
                f"Configured {kind} device is ambiguous; select an explicit "
                f"index:<number>: {choices}"
            )
        return int(matches[0]["index"])

    def set_overflow_handler(self, callback: Callable[[], None]) -> None:
        self._overflow_handler = callback

    async def start(self) -> None:
        if self._router_task is not None:
            raise RuntimeError("local audio runtime is already started")
        self._media_devices = rtc.MediaDevices(
            input_sample_rate=DEVICE_SAMPLE_RATE,
            output_sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            blocksize=FRAME_SAMPLES,
        )
        input_device = self._resolve_device(
            self._media_devices.list_input_devices(),
            self._input_device_name,
            kind="input",
        )
        output_device = self._resolve_device(
            self._media_devices.list_output_devices(),
            self._output_device_name,
            kind="output",
        )
        self._input_capture = self._media_devices.open_input(
            input_device=input_device,
            enable_aec=True,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=True,
        )
        self._input_track = rtc.LocalAudioTrack.create_audio_track(
            "jarvis-local-microphone",
            self._input_capture.source,
        )
        self._input_stream = rtc.AudioStream.from_track(
            track=self._input_track,
            sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            frame_size_ms=FRAME_SIZE_MS,
        )
        self.output = LocalAudioOutput(
            output_device=output_device,
            apm=self._input_capture.apm,
            delay_estimator=self._input_capture.delay_estimator,
        )
        self.output.start()
        self.detector.enable()
        self._router_task = asyncio.create_task(
            self._route_input(), name="jarvis-local-audio-router"
        )

    async def _route_input(self) -> None:
        assert self._input_stream is not None
        async for event in self._input_stream:
            frame = event.frame
            copied = rtc.AudioFrame(
                data=bytes(frame.data),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel,
            )
            self._append_ring(copied)
            if self._active_input is not None:
                if (
                    not self._active_input.push_frame(copied)
                    and self._overflow_handler is not None
                ):
                    self._overflow_handler()
            else:
                self.detector.feed(copied)

    def _append_ring(self, frame: rtc.AudioFrame) -> None:
        self._ring.append(frame)
        self._ring_samples += frame.samples_per_channel
        limit = int(self._ring_buffer_seconds * DEVICE_SAMPLE_RATE)
        while (
            self._ring
            and self._ring_samples - self._ring[0].samples_per_channel >= limit
        ):
            self._ring_samples -= self._ring.popleft().samples_per_channel

    def activate_session(self, session_input: SessionAudioInput) -> None:
        if self._active_input is not None:
            raise RuntimeError("a voice session already owns routed microphone audio")
        self.detector.disable(clear_buffer=False)
        self._active_input = session_input
        pre_roll_samples = int(self._pre_roll_seconds * DEVICE_SAMPLE_RATE)
        selected: deque[rtc.AudioFrame] = deque()
        selected_samples = 0
        for frame in reversed(self._ring):
            selected.appendleft(frame)
            selected_samples += frame.samples_per_channel
            if selected_samples >= pre_roll_samples:
                break
        for frame in selected:
            if not session_input.push_frame(frame):
                self._active_input = None
                raise RuntimeError(
                    "session audio queue overflowed while adding pre-roll"
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
        if self._router_task is not None:
            self._router_task.cancel()
            await asyncio.gather(self._router_task, return_exceptions=True)
            self._router_task = None
        if self.output is not None:
            await self.output.aclose()
            self.output = None
        if self._input_stream is not None:
            await self._input_stream.aclose()
            self._input_stream = None
        if self._input_capture is not None:
            await self._input_capture.aclose()
            await self._input_capture.source.aclose()
            self._input_capture = None
        await self.detector.aclose()
