"""Shadow GStreamer timing probe for one discovered Windows AV source.

The probe never feeds JARVIS runtime consumers and never promotes AVSyncStatus.
It verifies that paired audio/video can run in one pipeline clock domain and
reports timestamp continuity for later active-speaker calibration.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from itertools import pairwise

from jarvis.sensors.models import AVSourceDescriptor
from jarvis.sensors.windows_discovery import discover_windows_av_sources

_IDENTITY_RE = re.compile(
    r"GstIdentity:(?P<name>[av]probe).*?last-message = .*?"
    r"pts: (?P<pts>[^,]+), duration: (?P<duration>[^,]+),"
)
_CLOCK_RE = re.compile(r"New clock: (?P<clock>\S+)")
_TIME_RE = re.compile(
    r"^(?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"\.(?P<fraction>\d+)$"
)


@dataclass(frozen=True, slots=True)
class TimedBuffer:
    pts_seconds: float
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class StreamTimingStats:
    buffers: int
    first_pts_ms: float | None
    last_pts_ms: float | None
    span_ms: float | None
    median_period_ms: float | None
    max_positive_gap_ms: float | None
    max_timestamp_error_ms: float | None
    monotonic: bool


@dataclass(frozen=True, slots=True)
class ProbeResult:
    source_id: str
    display_name: str
    requested_duration_seconds: float
    pipeline_clock: str | None
    audio_clock_selected: bool
    video: StreamTimingStats
    audio: StreamTimingStats
    errors: tuple[str, ...]
    structural_sync_ready: bool
    note: str = (
        "Structural same-clock readiness only; physical A/V capture offset "
        "remains an active-speaker calibration concern."
    )


def _parse_gst_time(value: str) -> float | None:
    text = value.strip()
    if text == "none":
        return None
    match = _TIME_RE.match(text)
    if match is None:
        return None
    fraction = match.group("fraction")
    return (
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + int(match.group("seconds"))
        + int(fraction) / (10 ** len(fraction))
    )


def parse_identity_line(line: str) -> tuple[str, TimedBuffer] | None:
    match = _IDENTITY_RE.search(line)
    if match is None:
        return None
    pts = _parse_gst_time(match.group("pts"))
    if pts is None:
        return None
    return (
        match.group("name"),
        TimedBuffer(
            pts_seconds=pts,
            duration_seconds=_parse_gst_time(match.group("duration")),
        ),
    )


def summarize_timing(buffers: list[TimedBuffer]) -> StreamTimingStats:
    if not buffers:
        return StreamTimingStats(0, None, None, None, None, None, None, False)

    pts = [buffer.pts_seconds for buffer in buffers]
    periods = [later - earlier for earlier, later in pairwise(pts)]
    monotonic = all(period >= 0 for period in periods)
    duration_values = [
        buffer.duration_seconds
        for buffer in buffers[:-1]
        if buffer.duration_seconds is not None
    ]

    timestamp_errors: list[float] = []
    positive_gaps: list[float] = []
    for previous, current in pairwise(buffers):
        if previous.duration_seconds is None:
            continue
        error = current.pts_seconds - (previous.pts_seconds + previous.duration_seconds)
        timestamp_errors.append(abs(error))
        positive_gaps.append(max(0.0, error))

    median_period = statistics.median(periods) if periods else None
    if median_period is None and duration_values:
        median_period = statistics.median(duration_values)

    return StreamTimingStats(
        buffers=len(buffers),
        first_pts_ms=round(pts[0] * 1000, 3),
        last_pts_ms=round(pts[-1] * 1000, 3),
        span_ms=round((pts[-1] - pts[0]) * 1000, 3),
        median_period_ms=(
            None if median_period is None else round(median_period * 1000, 3)
        ),
        max_positive_gap_ms=(
            None if not positive_gaps else round(max(positive_gaps) * 1000, 3)
        ),
        max_timestamp_error_ms=(
            None if not timestamp_errors else round(max(timestamp_errors) * 1000, 3)
        ),
        monotonic=monotonic,
    )


def _mmdevice_id_from_pnp_instance(instance_id: str) -> str:
    prefix = "SWD\\MMDEVAPI\\"
    if not instance_id.upper().startswith(prefix):
        raise ValueError("audio endpoint is not a Windows MMDevice PnP endpoint")
    return instance_id[len(prefix) :]


def _select_source(
    sources: tuple[AVSourceDescriptor, ...],
    source_id: str | None,
) -> AVSourceDescriptor:
    if source_id is not None:
        matches = [source for source in sources if source.source_id == source_id]
        if len(matches) != 1:
            raise RuntimeError(f"AV source not found: {source_id}")
        return matches[0]
    if len(sources) != 1:
        raise RuntimeError(
            "exactly one AV source is required unless --source-id is supplied"
        )
    return sources[0]


def _build_command(source: AVSourceDescriptor) -> list[str]:
    gst_launch = shutil.which("gst-launch-1.0")
    if gst_launch is None:
        raise RuntimeError("gst-launch-1.0 is not available on PATH")

    audio_device = _mmdevice_id_from_pnp_instance(source.audio_endpoint.stable_id)
    return [
        gst_launch,
        "-m",
        "-v",
        "mfvideosrc",
        f"device-name={source.video_endpoint.display_name}",
        "!",
        "video/x-raw,format=NV12,width=1280,height=720,framerate=30/1",
        "!",
        "queue",
        "!",
        "identity",
        "name=vprobe",
        "silent=false",
        "!",
        "fakesink",
        "sync=true",
        "wasapi2src",
        f"device={audio_device}",
        "low-latency=true",
        "provide-clock=true",
        "!",
        "audio/x-raw,format=S16LE,rate=48000,channels=2",
        "!",
        "queue",
        "!",
        "identity",
        "name=aprobe",
        "silent=false",
        "!",
        "fakesink",
        "sync=true",
    ]


def run_probe(
    source: AVSourceDescriptor,
    *,
    duration_seconds: float = 15.0,
) -> ProbeResult:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    process = subprocess.Popen(
        _build_command(source),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
            else 0
        ),
    )
    if process.stdout is None:
        process.kill()
        raise RuntimeError("failed to capture GStreamer probe output")

    video: list[TimedBuffer] = []
    audio: list[TimedBuffer] = []
    errors: list[str] = []
    pipeline_clock: str | None = None
    started = time.monotonic()

    try:
        while time.monotonic() - started < duration_seconds:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            clock_match = _CLOCK_RE.search(line)
            if clock_match is not None:
                pipeline_clock = clock_match.group("clock")

            parsed = parse_identity_line(line)
            if parsed is not None:
                name, buffer = parsed
                (video if name == "vprobe" else audio).append(buffer)

            if "ERROR" in line or "Failed to start" in line:
                errors.append(line.strip())
    finally:
        if process.poll() is None:
            try:
                if hasattr(signal, "CTRL_BREAK_EVENT"):
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=3)

    video_stats = summarize_timing(video)
    audio_stats = summarize_timing(audio)
    audio_clock_selected = pipeline_clock == "GstAudioSrcClock"
    structural_sync_ready = (
        audio_clock_selected
        and not errors
        and video_stats.buffers > 0
        and audio_stats.buffers > 0
        and video_stats.monotonic
        and audio_stats.monotonic
    )
    return ProbeResult(
        source_id=source.source_id,
        display_name=source.display_name,
        requested_duration_seconds=duration_seconds,
        pipeline_clock=pipeline_clock,
        audio_clock_selected=audio_clock_selected,
        video=video_stats,
        audio=audio_stats,
        errors=tuple(errors),
        structural_sync_ready=structural_sync_ready,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id")
    parser.add_argument("--duration", type=float, default=15.0)
    args = parser.parse_args()

    source = _select_source(discover_windows_av_sources(), args.source_id)
    result = run_probe(source, duration_seconds=args.duration)
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.structural_sync_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
