"""Production local conversation audio using LiveKit's MediaDevices AEC loop.

This module deliberately keeps acoustic echo cancellation inside LiveKit/WebRTC.
The microphone capture and speaker render use the same ``rtc.MediaDevices``
instance so its AudioProcessingModule receives both capture and reverse-stream
PCM with the same PortAudio delay estimator.

JARVIS requires a 48 kHz physical conversation render endpoint. This is a
fail-closed constraint: LiveKit's current MediaDevices APM framing is 10 ms / 480
samples, and the validated JARVIS full-duplex path uses 48 kHz end to end.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from livekit import rtc
from livekit.agents.voice import io

from jarvis.voice.audio import (
    DEVICE_CHANNELS,
    DEVICE_SAMPLE_RATE,
    FRAME_SAMPLES,
    LocalAudioRuntime,
)

LOGGER = logging.getLogger(__name__)

_PLAYBACK_SETTLE_SECONDS = 0.05


@dataclass(slots=True)
class _PlaybackSegment:
    samples: int
    started_at_wall: float
    started_at_monotonic: float
    generation: int
    completed: bool = False


class MediaDevicesAudioOutput(io.AudioOutput):
    """AgentSession sink backed by LiveKit's official MediaDevices OutputPlayer.

    AgentSession emits PCM into a local LiveKit audio track. MediaDevices'
    OutputPlayer consumes that track and renders it to the selected physical
    device. Because the player is opened from the same MediaDevices instance as
    the AEC-enabled microphone, LiveKit automatically feeds rendered PCM into
    the microphone APM reverse stream.
    """

    def __init__(
        self,
        media_devices: Any,
        *,
        output_device: int | None,
    ) -> None:
        super().__init__(
            label="JARVIS LiveKit MediaDevices speaker",
            capabilities=io.AudioOutputCapabilities(pause=False),
            sample_rate=DEVICE_SAMPLE_RATE,
        )
        self._media_devices = media_devices
        self._output_device = output_device
        self._source: rtc.AudioSource | None = None
        self._track: rtc.LocalAudioTrack | None = None
        self._player: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resampler: rtc.AudioResampler | None = None
        self._resampler_input_rate: int | None = None
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0
        self._generation = 0
        self._segments: list[_PlaybackSegment] = []
        self._closed = False

    async def start(self) -> None:
        if self._player is not None:
            raise RuntimeError("MediaDevices audio output is already started")
        self._loop = asyncio.get_running_loop()
        self._source = rtc.AudioSource(
            DEVICE_SAMPLE_RATE,
            DEVICE_CHANNELS,
            queue_size_ms=1_000,
            loop=self._loop,
        )
        self._track = rtc.LocalAudioTrack.create_audio_track(
            "jarvis-local-speaker-render",
            self._source,
        )
        self._player = self._media_devices.open_output(
            output_device=self._output_device
        )
        await self._player.add_track(self._track)
        await self._player.start()

    def _frames_at_canonical_rate(self, frame: rtc.AudioFrame) -> list[rtc.AudioFrame]:
        if frame.num_channels != DEVICE_CHANNELS:
            raise ValueError("MediaDevices output requires mono audio")
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
        source = self._source
        if source is None:
            raise RuntimeError("MediaDevices audio output is not started")
        await super().capture_frame(frame)
        for canonical in self._frames_at_canonical_rate(frame):
            playback_started_at: float | None = None
            if self._current_samples == 0:
                self._current_started_at_wall = time.time()
                self._current_started_at_monotonic = time.monotonic()
                playback_started_at = self._current_started_at_wall
            await source.capture_frame(canonical)
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
        if segment.completed or segment.generation != self._generation or self._closed:
            return
        segment.completed = True
        if segment in self._segments:
            self._segments.remove(segment)
        self.on_playback_finished(
            playback_position=segment.samples / DEVICE_SAMPLE_RATE,
            interrupted=False,
        )

    def clear_buffer(self) -> None:
        source = self._source
        if source is not None:
            source.clear_queue()

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

    async def aclose(self) -> None:
        if self._closed:
            return
        self.clear_buffer()
        self._closed = True
        player = self._player
        self._player = None
        if player is not None:
            await player.aclose()
        source = self._source
        self._source = None
        if source is not None:
            await source.aclose()
        self._track = None
        self._loop = None


class MediaDevicesConversationRuntime(LocalAudioRuntime):
    """Local wake/conversation runtime using LiveKit MediaDevices end to end."""

    @staticmethod
    def _require_48k_output(output_device: int | None) -> None:
        import sounddevice as sd

        try:
            sd.check_output_settings(
                device=output_device,
                channels=DEVICE_CHANNELS,
                dtype="int16",
                samplerate=DEVICE_SAMPLE_RATE,
            )
        except (sd.PortAudioError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "JARVIS conversation output must accept 48000 Hz for the validated "
                "LiveKit/WebRTC AEC path. Select a native/shared 48 kHz endpoint "
                "instead of a 44.1 kHz Bluetooth A2DP endpoint."
            ) from exc

    async def start(self) -> None:
        if self._router_task is not None:
            raise RuntimeError("local audio runtime is already started")

        self._media_devices = rtc.MediaDevices(
            input_sample_rate=DEVICE_SAMPLE_RATE,
            output_sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            blocksize=FRAME_SAMPLES,
        )
        input_devices = self._attach_host_api_names(
            self._media_devices.list_input_devices()
        )
        output_devices = self._attach_host_api_names(
            self._media_devices.list_output_devices()
        )
        input_device = self._resolve_device(
            input_devices,
            self._input_device_name,
            kind="input",
        )
        output_device = self._resolve_device(
            output_devices,
            self._output_device_name,
            kind="output",
        )
        self._log_resolved_device(input_devices, input_device, kind="input")
        self._log_resolved_device(output_devices, output_device, kind="output")
        self._require_48k_output(output_device)

        # open_input() creates the APM. open_output() below is intentionally
        # opened from this same MediaDevices instance so LiveKit wires the
        # reverse render stream into that APM automatically.
        self._input_capture = self._open_input_capture(input_device)
        self._input_track = rtc.LocalAudioTrack.create_audio_track(
            "jarvis-local-microphone",
            self._input_capture.source,
        )
        self._input_stream = rtc.AudioStream.from_track(
            track=self._input_track,
            sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            frame_size_ms=10,
        )
        output = MediaDevicesAudioOutput(
            self._media_devices,
            output_device=output_device,
        )
        await output.start()
        self.output = output  # type: ignore[assignment]

        self.detector.enable()
        self._router_task = asyncio.create_task(
            self._route_input(),
            name="jarvis-livekit-media-devices-router",
        )
        LOGGER.info(
            "LiveKit MediaDevices full-duplex audio is active at 48000 Hz: "
            "WebRTC AEC + NS + HPF + AGC share the physical speaker render reference"
        )
