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
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
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


@dataclass(frozen=True, slots=True)
class PlaybackQualitySnapshot:
    """Completed playback evidence exposed to provider-resilience observers."""

    sequence: int
    duration_seconds: float
    peak_abs: int
    rms_dbfs: float
    interrupted: bool


@dataclass(slots=True)
class _PlaybackSegment:
    sequence: int
    samples: int
    started_at_wall: float
    started_at_monotonic: float
    generation: int
    peak_abs: int
    rms_dbfs: float
    player_buffer_peak_bytes: int
    player_stream_active_seen: bool
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
        self._current_segment_sequence = 0
        self._next_segment_sequence = 1
        self._current_peak_abs = 0
        self._current_sum_squares = 0.0
        self._current_energy_samples = 0
        self._current_player_buffer_peak_bytes = 0
        self._current_player_stream_active_seen = False
        self._generation = 0
        self._segments: list[_PlaybackSegment] = []
        self._last_completed_quality: PlaybackQualitySnapshot | None = None
        self._closed = False

    @property
    def last_completed_quality(self) -> PlaybackQualitySnapshot | None:
        """Return the most recently completed output segment's energy evidence."""

        return self._last_completed_quality

    @staticmethod
    def _source_queued_duration(source: rtc.AudioSource | None) -> float:
        if source is None:
            return 0.0
        try:
            return float(source.queued_duration)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return -1.0

    @staticmethod
    def _frame_energy(frame: rtc.AudioFrame) -> tuple[int, float, int]:
        samples = np.frombuffer(frame.data, dtype=np.int16)
        if samples.size == 0:
            return 0, 0.0, 0
        peak_abs = int(np.max(np.abs(samples.astype(np.int32))))
        values = samples.astype(np.float64)
        sum_squares = float(np.dot(values, values))
        return peak_abs, sum_squares, int(samples.size)

    @staticmethod
    def _player_state(player: Any) -> tuple[int, bool | None, bool | None]:
        if player is None:
            return -1, None, None
        try:
            buffer_value = getattr(player, "_buffer", None)
            buffered_bytes = len(buffer_value) if buffer_value is not None else -1
        except (AttributeError, RuntimeError, TypeError, ValueError):
            buffered_bytes = -1

        stream = getattr(player, "_stream", None)
        if stream is None:
            return buffered_bytes, None, None
        try:
            active = bool(stream.active)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            active = None
        try:
            stopped = bool(stream.stopped)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            stopped = None
        return buffered_bytes, active, stopped

    @staticmethod
    def _rms_dbfs(sum_squares: float, sample_count: int) -> float:
        if sum_squares <= 0.0 or sample_count <= 0:
            return float("-inf")
        rms = math.sqrt(sum_squares / sample_count)
        return 20.0 * math.log10(rms / 32768.0)

    def _observe_player_state(self) -> tuple[int, bool | None, bool | None]:
        buffered_bytes, active, stopped = self._player_state(self._player)
        if buffered_bytes >= 0:
            self._current_player_buffer_peak_bytes = max(
                self._current_player_buffer_peak_bytes,
                buffered_bytes,
            )
        if active is True:
            self._current_player_stream_active_seen = True
        return buffered_bytes, active, stopped

    def _reset_current_diagnostics(self) -> None:
        self._current_peak_abs = 0
        self._current_sum_squares = 0.0
        self._current_energy_samples = 0
        self._current_player_buffer_peak_bytes = 0
        self._current_player_stream_active_seen = False

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
                self._current_segment_sequence = self._next_segment_sequence
                self._next_segment_sequence += 1
                self._reset_current_diagnostics()
                playback_started_at = self._current_started_at_wall

            peak_abs, sum_squares, sample_count = self._frame_energy(canonical)
            self._current_peak_abs = max(self._current_peak_abs, peak_abs)
            self._current_sum_squares += sum_squares
            self._current_energy_samples += sample_count

            await source.capture_frame(canonical)
            self._current_samples += canonical.samples_per_channel
            player_buffered, player_active, player_stopped = self._observe_player_state()
            if playback_started_at is not None:
                LOGGER.info(
                    "Playback diagnostic | segment=%s event=started generation=%s "
                    "queued=%.3fs pcm_peak=%s player_buffer=%sB "
                    "stream_active=%s stream_stopped=%s",
                    self._current_segment_sequence,
                    self._generation,
                    self._source_queued_duration(source),
                    self._current_peak_abs,
                    player_buffered,
                    player_active,
                    player_stopped,
                )
                self.on_playback_started(created_at=playback_started_at)

    def flush(self) -> None:
        super().flush()
        if self._current_samples <= 0:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        player_buffered, player_active, player_stopped = self._observe_player_state()
        rms_dbfs = self._rms_dbfs(
            self._current_sum_squares,
            self._current_energy_samples,
        )
        segment = _PlaybackSegment(
            sequence=self._current_segment_sequence,
            samples=self._current_samples,
            started_at_wall=self._current_started_at_wall,
            started_at_monotonic=self._current_started_at_monotonic,
            generation=self._generation,
            peak_abs=self._current_peak_abs,
            rms_dbfs=rms_dbfs,
            player_buffer_peak_bytes=self._current_player_buffer_peak_bytes,
            player_stream_active_seen=self._current_player_stream_active_seen,
        )
        self._segments.append(segment)
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0
        self._current_segment_sequence = 0
        self._reset_current_diagnostics()

        duration = segment.samples / DEVICE_SAMPLE_RATE
        elapsed = max(0.0, time.monotonic() - segment.started_at_monotonic)
        remaining = max(0.01, duration - elapsed + _PLAYBACK_SETTLE_SECONDS)
        LOGGER.info(
            "Playback diagnostic | segment=%s event=flush generation=%s "
            "duration=%.3fs elapsed=%.3fs queued=%.3fs finish_timer=%.3fs "
            "pcm_peak=%s rms_dbfs=%.1f player_buffer_now=%sB "
            "player_buffer_peak=%sB stream_active_seen=%s "
            "stream_active_now=%s stream_stopped_now=%s",
            segment.sequence,
            segment.generation,
            duration,
            elapsed,
            self._source_queued_duration(self._source),
            remaining,
            segment.peak_abs,
            segment.rms_dbfs,
            player_buffered,
            segment.player_buffer_peak_bytes,
            segment.player_stream_active_seen,
            player_active,
            player_stopped,
        )
        loop.call_later(remaining, self._finish_segment, segment)

    def _finish_segment(self, segment: _PlaybackSegment) -> None:
        if segment.completed or segment.generation != self._generation or self._closed:
            return
        segment.completed = True
        if segment in self._segments:
            self._segments.remove(segment)
        playback_position = segment.samples / DEVICE_SAMPLE_RATE
        self._last_completed_quality = PlaybackQualitySnapshot(
            sequence=segment.sequence,
            duration_seconds=playback_position,
            peak_abs=segment.peak_abs,
            rms_dbfs=segment.rms_dbfs,
            interrupted=False,
        )
        player_buffered, player_active, player_stopped = self._player_state(self._player)
        LOGGER.info(
            "Playback diagnostic | segment=%s event=finished generation=%s "
            "position=%.3fs interrupted=False queued=%.3fs "
            "pcm_peak=%s rms_dbfs=%.1f player_buffer_now=%sB "
            "player_buffer_peak=%sB stream_active_seen=%s "
            "stream_active_now=%s stream_stopped_now=%s",
            segment.sequence,
            segment.generation,
            playback_position,
            self._source_queued_duration(self._source),
            segment.peak_abs,
            segment.rms_dbfs,
            player_buffered,
            segment.player_buffer_peak_bytes,
            segment.player_stream_active_seen,
            player_active,
            player_stopped,
        )
        self.on_playback_finished(
            playback_position=playback_position,
            interrupted=False,
        )

    def clear_buffer(self) -> None:
        source = self._source
        queued_before_clear = self._source_queued_duration(source)
        pending = [segment for segment in self._segments if not segment.completed]
        player_buffered, player_active, player_stopped = self._player_state(self._player)
        LOGGER.info(
            "Playback diagnostic | event=clear_buffer generation=%s current_segment=%s "
            "current_samples=%s pending_segments=%s queued_before=%.3fs "
            "player_buffer=%sB stream_active=%s stream_stopped=%s",
            self._generation,
            self._current_segment_sequence or "none",
            self._current_samples,
            len(pending),
            queued_before_clear,
            player_buffered,
            player_active,
            player_stopped,
        )
        if source is not None:
            source.clear_queue()

        had_current = self._current_samples > 0
        current_sequence = self._current_segment_sequence
        current_samples = self._current_samples
        current_peak_abs = self._current_peak_abs
        current_rms_dbfs = self._rms_dbfs(
            self._current_sum_squares,
            self._current_energy_samples,
        )
        current_position = 0.0
        if had_current:
            duration = current_samples / DEVICE_SAMPLE_RATE
            elapsed = max(0.0, time.monotonic() - self._current_started_at_monotonic)
            current_position = min(duration, elapsed)

        self._generation += 1
        self._segments.clear()
        self._current_samples = 0
        self._current_started_at_wall = 0.0
        self._current_started_at_monotonic = 0.0
        self._current_segment_sequence = 0
        self._reset_current_diagnostics()

        if had_current:
            super().flush()
            self._last_completed_quality = PlaybackQualitySnapshot(
                sequence=current_sequence,
                duration_seconds=current_position,
                peak_abs=current_peak_abs,
                rms_dbfs=current_rms_dbfs,
                interrupted=True,
            )
            LOGGER.info(
                "Playback diagnostic | segment=%s event=finished position=%.3fs "
                "interrupted=True reason=clear_buffer queued_after=%.3fs",
                current_sequence,
                current_position,
                self._source_queued_duration(source),
            )
            self.on_playback_finished(
                playback_position=current_position,
                interrupted=True,
            )
        for segment in pending:
            segment.completed = True
            duration = segment.samples / DEVICE_SAMPLE_RATE
            elapsed = max(0.0, time.monotonic() - segment.started_at_monotonic)
            playback_position = min(duration, elapsed)
            self._last_completed_quality = PlaybackQualitySnapshot(
                sequence=segment.sequence,
                duration_seconds=playback_position,
                peak_abs=segment.peak_abs,
                rms_dbfs=segment.rms_dbfs,
                interrupted=True,
            )
            LOGGER.info(
                "Playback diagnostic | segment=%s event=finished position=%.3fs "
                "interrupted=True reason=clear_buffer queued_after=%.3fs",
                segment.sequence,
                playback_position,
                self._source_queued_duration(source),
            )
            self.on_playback_finished(
                playback_position=playback_position,
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