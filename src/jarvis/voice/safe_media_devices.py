"""Race-safe LiveKit MediaDevices microphone ingress for JARVIS.

LiveKit MediaDevices currently checks an asyncio queue's capacity on the
PortAudio callback thread and schedules put_nowait() onto the event loop. A
stalled event loop can therefore receive many individually "safe" scheduled
puts that overflow once they execute. JARVIS keeps the same LiveKit APM/output
contract but owns the bounded cross-thread ingress so capacity is enforced at
the point of insertion.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from livekit import rtc

LOGGER = logging.getLogger(__name__)


class BoundedAudioIngress:
    """Bound cross-thread PCM backlog without ever leaking QueueFull callbacks."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        capacity_frames: int,
    ) -> None:
        if capacity_frames <= 0:
            raise ValueError("audio ingress capacity must be positive")
        self._loop = loop
        self._capacity = int(capacity_frames)
        self._queue: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue(
            maxsize=self._capacity
        )
        self._pending: deque[rtc.AudioFrame] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()
        self._drain_scheduled = False
        self._dropped_frames = 0
        self._drop_warning_emitted = False

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    def submit_from_audio_thread(self, frame: rtc.AudioFrame) -> bool:
        """Retain freshest audio and schedule at most one event-loop drain."""

        schedule_drain = False
        with self._lock:
            if len(self._pending) >= self._capacity:
                self._pending.popleft()
                self._dropped_frames += 1
            self._pending.append(frame)
            if not self._drain_scheduled:
                self._drain_scheduled = True
                schedule_drain = True

        if not schedule_drain:
            return True

        try:
            self._loop.call_soon_threadsafe(self._drain_pending)
        except RuntimeError:
            with self._lock:
                self._drain_scheduled = False
                self._pending.clear()
            return False
        return True

    def _record_queue_drop(self) -> None:
        with self._lock:
            self._dropped_frames += 1

    def _drain_pending(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._drain_scheduled = False
                    dropped = self._dropped_frames
                    break
                frame = self._pending.popleft()

            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                else:
                    self._record_queue_drop()
            self._queue.put_nowait(frame)

        if dropped and not self._drop_warning_emitted:
            self._drop_warning_emitted = True
            LOGGER.warning(
                "Live microphone ingress shed stale PCM under event-loop "
                "backpressure; conversation remains live | dropped_frames=%s",
                dropped,
            )

    async def get(self) -> rtc.AudioFrame:
        return await self._queue.get()


class _CaptureDelayEstimator:
    """Thread-safe render delay shared by capture APM and output player."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._output_delay_sec = 0.0

    def set_output_delay(self, delay_sec: float) -> None:
        with self._lock:
            self._output_delay_sec = float(delay_sec)

    def get_output_delay(self) -> float:
        with self._lock:
            return self._output_delay_sec


@dataclass(slots=True)
class SafeInputCapture:
    source: rtc.AudioSource
    input_stream: Any
    task: asyncio.Task[None]
    apm: Any
    delay_estimator: _CaptureDelayEstimator | None
    ingress: BoundedAudioIngress

    async def aclose(self) -> None:
        try:
            self.input_stream.stop()
            self.input_stream.close()
        except Exception:  # noqa: BLE001 - best-effort native stream cleanup
            LOGGER.debug("Safe microphone input cleanup failed", exc_info=True)
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class SafeMediaDevices(rtc.MediaDevices):
    """MediaDevices with race-safe capture ingress and unchanged AEC sharing."""

    def open_input(
        self,
        *,
        enable_aec: bool = True,
        noise_suppression: bool = True,
        high_pass_filter: bool = True,
        auto_gain_control: bool = True,
        input_device: int | None = None,
        queue_capacity: int = 50,
        input_channel_index: int | None = None,
    ) -> SafeInputCapture:
        del input_channel_index
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")

        import sounddevice as sd

        loop = self._loop
        source = rtc.AudioSource(self._in_sr, self._channels, loop=loop)

        apm = None
        if enable_aec or noise_suppression or high_pass_filter or auto_gain_control:
            apm = rtc.AudioProcessingModule(
                echo_cancellation=enable_aec,
                noise_suppression=noise_suppression,
                high_pass_filter=high_pass_filter,
                auto_gain_control=auto_gain_control,
            )

        delay_estimator = _CaptureDelayEstimator() if apm is not None else None

        # Preserve MediaDevices' canonical AEC contract: inherited open_output()
        # reads these exact members and feeds rendered PCM into the same APM.
        self._delay_estimator = delay_estimator
        self._apm = apm

        ingress = BoundedAudioIngress(
            loop,
            capacity_frames=queue_capacity,
        )

        frame_samples = int(self._blocksize)
        callback_errors = {"delay": 0, "process": 0}

        def input_callback(
            indata: np.ndarray,
            frame_count: int,
            time_info: Any,
            status: Any,
        ) -> None:
            del status
            if apm is not None:
                try:
                    input_delay_sec = float(
                        time_info.currentTime - time_info.inputBufferAdcTime
                    )
                    output_delay_sec = (
                        float(delay_estimator.get_output_delay())
                        if delay_estimator is not None
                        else 0.0
                    )
                    total_delay_ms = int(
                        max((input_delay_sec + output_delay_sec) * 1000.0, 0.0)
                    )
                    apm.set_stream_delay_ms(total_delay_ms)
                except Exception:  # noqa: BLE001 - realtime callback must survive
                    callback_errors["delay"] += 1

            num_frames = frame_count // frame_samples
            for index in range(num_frames):
                start = index * frame_samples
                end = start + frame_samples
                if end > frame_count:
                    break
                chunk = indata[start:end, 0]
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    samples_per_channel=frame_samples,
                    sample_rate=self._in_sr,
                    num_channels=self._channels,
                )
                if apm is not None:
                    try:
                        apm.process_stream(frame)
                    except Exception:  # noqa: BLE001 - realtime callback must survive
                        callback_errors["process"] += 1
                ingress.submit_from_audio_thread(frame)

        input_stream = sd.InputStream(
            callback=input_callback,
            dtype="int16",
            channels=self._channels,
            device=input_device,
            samplerate=self._in_sr,
            blocksize=self._blocksize,
        )
        input_stream.start()

        async def pump() -> None:
            capture_errors = 0
            while True:
                frame = await ingress.get()
                try:
                    await source.capture_frame(frame)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - keep physical mic pump alive
                    capture_errors += 1
                    if capture_errors == 1:
                        LOGGER.warning(
                            "LiveKit AudioSource rejected a microphone frame; "
                            "capture pump remains active"
                        )

        task = asyncio.create_task(
            pump(),
            name="jarvis-safe-media-devices-input-pump",
        )
        return SafeInputCapture(
            source=source,
            input_stream=input_stream,
            task=task,
            apm=apm,
            delay_estimator=delay_estimator,
            ingress=ingress,
        )
