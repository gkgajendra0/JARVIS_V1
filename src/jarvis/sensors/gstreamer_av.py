"""Paired GStreamer camera/audio capture for synchronized perception.

This module owns one GStreamer pipeline for a physically paired Windows AV source.
Video and raw microphone PCM remain available for synchronized perception while an
optional full-duplex playback/AEC branch exposes echo-cancelled microphone PCM for
wake detection and realtime conversation. Raw PCM is never replaced by the cleaned
branch because active-speaker corroboration needs the physical capture timeline.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from jarvis.sensors.models import AVSourceDescriptor
from jarvis.sensors.windows_discovery import discover_windows_av_sources
from jarvis.vision.camera import CapturedFrame

AudioFrameTap = Callable[[bytes, int, int, int, float], None]

AEC_SAMPLE_RATE = 48_000
AEC_CHANNELS = 1


@dataclass(frozen=True, slots=True)
class GStreamerPairedAVConfig:
    width: int = 1280
    height: int = 720
    fps: int = 30
    audio_rate: int = 16_000
    playback_device_id: str | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("paired AV video dimensions/fps must be positive")
        if self.audio_rate <= 0:
            raise ValueError("paired AV audio rate must be positive")
        if self.playback_device_id is not None:
            normalized = str(self.playback_device_id).strip()
            if not normalized:
                raise ValueError("paired AV playback device id must not be empty")
            object.__setattr__(self, "playback_device_id", normalized)


def _mmdevice_id_from_pnp_instance(instance_id: str) -> str:
    prefix = "SWD\\MMDEVAPI\\"
    if not instance_id.upper().startswith(prefix):
        raise ValueError("audio endpoint is not a Windows MMDevice PnP endpoint")
    return instance_id[len(prefix) :]


def _gst_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_pipeline_description(
    source: AVSourceDescriptor,
    config: GStreamerPairedAVConfig,
) -> str:
    """Return one paired capture graph with optional full-duplex WebRTC AEC."""

    audio_device = _mmdevice_id_from_pnp_instance(source.audio_endpoint.stable_id)
    video_name = _gst_quote(source.video_endpoint.display_name)
    audio_name = _gst_quote(audio_device)
    parts = [
        "mfvideosrc",
        f"device-name={video_name}",
        "!",
        (
            "video/x-raw,format=NV12,"
            f"width={config.width},height={config.height},framerate={config.fps}/1"
        ),
        "!",
        "videoconvert",
        "!",
        (
            "video/x-raw,format=BGR,"
            f"width={config.width},height={config.height},framerate={config.fps}/1"
        ),
        "!",
        (
            "appsink name=video_sink emit-signals=true sync=false "
            "max-buffers=2 drop=true wait-on-eos=false"
        ),
    ]

    if config.playback_device_id is not None:
        playback_device = _gst_quote(config.playback_device_id)
        playback_caps = _gst_quote(
            "audio/x-raw,format=S16LE,layout=interleaved,rate=48000,channels=1"
        )
        parts.extend(
            [
                "appsrc",
                "name=playback_src",
                "is-live=true",
                "format=time",
                "do-timestamp=true",
                "block=true",
                "max-time=100000000",
                f"caps={playback_caps}",
                "!",
                "queue",
                "max-size-time=100000000",
                "max-size-bytes=0",
                "max-size-buffers=0",
                "!",
                "webrtcechoprobe",
                "name=echo_probe",
                "!",
                "audioconvert",
                "!",
                "audioresample",
                "!",
                "wasapi2sink",
                f"device={playback_device}",
                "low-latency=true",
            ]
        )

    parts.extend(
        [
            "wasapi2src",
            f"device={audio_name}",
            "low-latency=true",
            "provide-clock=true",
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            (
                "audio/x-raw,format=S16LE,"
                f"rate={AEC_SAMPLE_RATE},channels={AEC_CHANNELS}"
            ),
            "!",
            "tee",
            "name=mic_capture",
            "mic_capture.",
            "!",
            "queue",
            "!",
            "audioresample",
            "!",
            f"audio/x-raw,format=S16LE,rate={config.audio_rate},channels=1",
            "!",
            (
                "appsink name=audio_sink emit-signals=true sync=false "
                "max-buffers=64 drop=true wait-on-eos=false"
            ),
        ]
    )

    if config.playback_device_id is not None:
        parts.extend(
            [
                "mic_capture.",
                "!",
                "queue",
                "!",
                (
                    "webrtcdsp name=aec_dsp probe=echo_probe echo-cancel=true "
                    "noise-suppression=false gain-control=false "
                    "high-pass-filter=false"
                ),
                "!",
                (
                    "appsink name=clean_audio_sink emit-signals=true sync=false "
                    "max-buffers=64 drop=true wait-on-eos=false"
                ),
            ]
        )

    return " ".join(parts)


def _load_gstreamer():
    try:
        import gi
    except ImportError as exc:
        raise RuntimeError(
            "GStreamer Python bindings are unavailable; install the sensor-av extra"
        ) from exc

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    return Gst


class GStreamerPairedAVSource:
    """Capture paired A/V once and optionally own the full-duplex AEC graph."""

    def __init__(
        self,
        source: AVSourceDescriptor,
        config: GStreamerPairedAVConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.config = config or GStreamerPairedAVConfig()
        self._clock = clock
        self._condition = threading.Condition()
        self._tap_lock = threading.RLock()
        self._stop = threading.Event()
        self._pipeline = None
        self._gst = None
        self._bus_thread: threading.Thread | None = None
        self._latest: CapturedFrame | None = None
        self._next_frame_id = 0
        self._read_error: RuntimeError | None = None
        self._audio_tap: AudioFrameTap | None = None
        self._clean_audio_tap: AudioFrameTap | None = None
        self._monotonic_origin: float | None = None
        self._pipeline_clock_name: str | None = None
        self._playback_src = None

    @property
    def running(self) -> bool:
        return self._pipeline is not None and not self._stop.is_set()

    @property
    def pipeline_clock_name(self) -> str | None:
        return self._pipeline_clock_name

    @property
    def playback_enabled(self) -> bool:
        return self.config.playback_device_id is not None

    def set_audio_frame_tap(self, tap: AudioFrameTap | None) -> None:
        """Set the raw physical-microphone tap used by synchronized perception."""
        with self._tap_lock:
            self._audio_tap = tap

    def set_clean_audio_frame_tap(self, tap: AudioFrameTap | None) -> None:
        """Set the WebRTC-AEC-cleaned microphone tap used by conversation audio."""
        with self._tap_lock:
            self._clean_audio_tap = tap

    def start(self) -> None:
        if self._pipeline is not None:
            raise RuntimeError("paired AV source is already started")

        Gst = _load_gstreamer()
        pipeline = Gst.parse_launch(build_pipeline_description(self.source, self.config))
        video_sink = pipeline.get_by_name("video_sink")
        audio_sink = pipeline.get_by_name("audio_sink")
        if video_sink is None or audio_sink is None:
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("paired AV pipeline did not expose both capture appsinks")

        clean_audio_sink = pipeline.get_by_name("clean_audio_sink")
        playback_src = pipeline.get_by_name("playback_src")
        if self.playback_enabled and (
            clean_audio_sink is None or playback_src is None
        ):
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(
                "paired AV full-duplex pipeline did not expose AEC audio endpoints"
            )

        video_sink.connect("new-sample", self._on_video_sample)
        audio_sink.connect("new-sample", self._on_audio_sample)
        if clean_audio_sink is not None:
            clean_audio_sink.connect("new-sample", self._on_clean_audio_sample)

        self._stop.clear()
        self._read_error = None
        self._latest = None
        self._next_frame_id = 0
        self._gst = Gst
        self._pipeline = pipeline
        self._playback_src = playback_src

        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            self.close()
            raise RuntimeError("paired AV pipeline failed to enter PLAYING")
        _, state, _ = pipeline.get_state(5 * Gst.SECOND)
        if state != Gst.State.PLAYING:
            self.close()
            raise RuntimeError("paired AV pipeline did not reach PLAYING")

        pipeline_clock = pipeline.get_clock()
        if pipeline_clock is None:
            self.close()
            raise RuntimeError("paired AV pipeline did not select a clock")
        base_time = pipeline.get_base_time()
        running_now = pipeline_clock.get_time() - base_time
        self._monotonic_origin = self._clock() - running_now / Gst.SECOND
        self._pipeline_clock_name = pipeline_clock.get_name()

        self._bus_thread = threading.Thread(
            target=self._bus_loop,
            name="jarvis-gstreamer-av-bus",
            daemon=True,
        )
        self._bus_thread.start()

    def latest(
        self,
        *,
        after_frame_id: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CapturedFrame | None:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")

        def ready() -> bool:
            frame = self._latest
            return (
                self._read_error is not None
                or self._stop.is_set()
                or (
                    frame is not None
                    and (after_frame_id is None or frame.frame_id > after_frame_id)
                )
            )

        with self._condition:
            if not ready():
                self._condition.wait_for(ready, timeout=timeout_seconds)
            if self._read_error is not None:
                raise self._read_error
            frame = self._latest
            if frame is None:
                return None
            if after_frame_id is not None and frame.frame_id <= after_frame_id:
                return None
            return frame

    def push_playback_pcm(
        self,
        data: bytes | bytearray | memoryview,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        """Push canonical JARVIS PCM into the echo-reference/playback branch."""
        if sample_rate != AEC_SAMPLE_RATE or num_channels != AEC_CHANNELS:
            raise ValueError("paired playback PCM must be 48 kHz mono")
        if samples_per_channel <= 0:
            raise ValueError("paired playback frame size must be positive")
        payload = bytes(data)
        if len(payload) != samples_per_channel * 2:
            raise ValueError("paired playback PCM byte length does not match int16 mono")

        Gst = self._gst
        appsrc = self._playback_src
        if Gst is None or appsrc is None or not self.running:
            raise RuntimeError("paired GStreamer playback is not running")

        buffer = Gst.Buffer.new_allocate(None, len(payload), None)
        buffer.fill(0, payload)
        buffer.duration = Gst.util_uint64_scale(
            samples_per_channel,
            Gst.SECOND,
            sample_rate,
        )
        result = appsrc.emit("push-buffer", buffer)
        if result not in {Gst.FlowReturn.OK, Gst.FlowReturn.FLUSHING}:
            raise RuntimeError(f"paired GStreamer playback push failed: {result}")

    def flush_playback(self) -> None:
        """Discard queued playback on interruption without flushing capture branches."""
        Gst = self._gst
        appsrc = self._playback_src
        if Gst is None or appsrc is None or not self.running:
            return
        pad = appsrc.get_static_pad("src")
        if pad is None:
            return
        pad.push_event(Gst.Event.new_flush_start())
        pad.push_event(Gst.Event.new_flush_stop(False))

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        with self._tap_lock:
            self._audio_tap = None
            self._clean_audio_tap = None

        pipeline = self._pipeline
        Gst = self._gst
        if pipeline is not None and Gst is not None:
            pipeline.set_state(Gst.State.NULL)

        thread = self._bus_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

        self._pipeline = None
        self._gst = None
        self._playback_src = None
        self._bus_thread = None
        self._monotonic_origin = None
        self._pipeline_clock_name = None

    def _timestamp(self, pts: int) -> float | None:
        Gst = self._gst
        origin = self._monotonic_origin
        if Gst is None or origin is None or pts == Gst.CLOCK_TIME_NONE:
            return None
        return origin + pts / Gst.SECOND

    def _on_video_sample(self, sink):
        Gst = self._gst
        if Gst is None:
            return 0
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        observed_at = self._timestamp(buffer.pts)
        if observed_at is None:
            return Gst.FlowReturn.OK

        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            self._fail(RuntimeError("paired AV video buffer mapping failed"))
            return Gst.FlowReturn.ERROR
        try:
            payload = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)

        expected = self.config.width * self.config.height * 3
        if len(payload) < expected:
            self._fail(RuntimeError("paired AV video buffer was smaller than BGR frame"))
            return Gst.FlowReturn.ERROR
        image = np.frombuffer(payload[:expected], dtype=np.uint8).reshape(
            self.config.height,
            self.config.width,
            3,
        )
        frame = CapturedFrame(
            frame_id=self._next_frame_id,
            captured_at=observed_at,
            image=np.ascontiguousarray(image),
        )
        self._next_frame_id += 1
        with self._condition:
            self._latest = frame
            self._condition.notify_all()
        return Gst.FlowReturn.OK

    def _pull_audio_sample(
        self,
        sink,
        *,
        expected_rate: int,
        tap: AudioFrameTap | None,
        label: str,
    ):
        Gst = self._gst
        if Gst is None:
            return 0
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        observed_at = self._timestamp(buffer.pts)
        if observed_at is None:
            return Gst.FlowReturn.OK

        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            self._fail(RuntimeError(f"paired AV {label} buffer mapping failed"))
            return Gst.FlowReturn.ERROR
        try:
            payload = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)
        if not payload or len(payload) % 2:
            self._fail(RuntimeError(f"paired AV {label} buffer was not int16 PCM"))
            return Gst.FlowReturn.ERROR

        if tap is not None:
            try:
                tap(
                    payload,
                    expected_rate,
                    1,
                    len(payload) // 2,
                    observed_at,
                )
            except Exception as exc:  # noqa: BLE001 - native callback boundary
                self._fail(RuntimeError(f"paired AV {label} tap failed: {exc}"))
                return Gst.FlowReturn.ERROR
        return Gst.FlowReturn.OK

    def _on_audio_sample(self, sink):
        with self._tap_lock:
            tap = self._audio_tap
        return self._pull_audio_sample(
            sink,
            expected_rate=self.config.audio_rate,
            tap=tap,
            label="raw audio",
        )

    def _on_clean_audio_sample(self, sink):
        with self._tap_lock:
            tap = self._clean_audio_tap
        return self._pull_audio_sample(
            sink,
            expected_rate=AEC_SAMPLE_RATE,
            tap=tap,
            label="AEC-clean audio",
        )

    def _bus_loop(self) -> None:
        Gst = self._gst
        pipeline = self._pipeline
        if Gst is None or pipeline is None:
            return
        bus = pipeline.get_bus()
        mask = Gst.MessageType.ERROR | Gst.MessageType.EOS
        while not self._stop.is_set():
            message = bus.timed_pop_filtered(100 * Gst.MSECOND, mask)
            if message is None:
                continue
            if message.type == Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                detail = f" ({debug})" if debug else ""
                self._fail(RuntimeError(f"paired AV pipeline error: {error}{detail}"))
                return
            if message.type == Gst.MessageType.EOS:
                self._fail(RuntimeError("paired AV pipeline reached unexpected EOS"))
                return

    def _fail(self, error: RuntimeError) -> None:
        with self._condition:
            if self._read_error is None:
                self._read_error = error
            self._condition.notify_all()
        self._stop.set()


def _select_source(
    sources: tuple[AVSourceDescriptor, ...], source_id: str | None
) -> AVSourceDescriptor:
    if source_id is not None:
        matches = [source for source in sources if source.source_id == source_id]
        if len(matches) != 1:
            raise RuntimeError(f"AV source not found: {source_id}")
        return matches[0]
    if len(sources) != 1:
        raise RuntimeError("exactly one AV source is required unless --source-id is supplied")
    return sources[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id")
    parser.add_argument("--duration", type=float, default=10.0)
    args = parser.parse_args()
    if args.duration <= 0:
        raise ValueError("duration must be positive")

    source = _select_source(discover_windows_av_sources(), args.source_id)
    capture = GStreamerPairedAVSource(source)
    audio_times: list[float] = []
    video_times: list[float] = []

    def on_audio(
        data: bytes,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        observed_at: float,
    ) -> None:
        del data, sample_rate, num_channels, samples_per_channel
        audio_times.append(observed_at)

    capture.set_audio_frame_tap(on_audio)
    capture.start()
    clock_name = capture.pipeline_clock_name
    deadline = time.monotonic() + args.duration
    last_frame_id: int | None = None
    try:
        while time.monotonic() < deadline:
            frame = capture.latest(
                after_frame_id=last_frame_id,
                timeout_seconds=0.25,
            )
            if frame is None:
                continue
            last_frame_id = frame.frame_id
            video_times.append(frame.captured_at)
    finally:
        capture.close()

    video_monotonic = all(later >= earlier for earlier, later in pairwise(video_times))
    audio_monotonic = all(later >= earlier for earlier, later in pairwise(audio_times))
    result = {
        "source_id": source.source_id,
        "display_name": source.display_name,
        "pipeline_clock": clock_name,
        "video_frames": len(video_times),
        "audio_buffers": len(audio_times),
        "video_monotonic": video_monotonic,
        "audio_monotonic": audio_monotonic,
        "python_appsink_ready": bool(
            video_times and audio_times and video_monotonic and audio_monotonic
        ),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["python_appsink_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
