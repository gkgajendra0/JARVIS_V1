from __future__ import annotations

import asyncio

import numpy as np
import pytest

from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.paired_audio import PairedAudioRuntime


class FakeDetector:
    def __init__(self) -> None:
        self.enabled = False
        self.frames = []
        self.closed = False

    def enable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enabled = True

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enabled = False

    def feed(self, frame) -> None:
        if self.enabled:
            self.frames.append(frame)

    async def aclose(self) -> None:
        self.closed = True
        self.enabled = False


class FakePairedAVSource:
    def __init__(self) -> None:
        self.running = True
        self.playback_enabled = True
        self.playback: list[tuple[bytes, int, int, int]] = []
        self.flush_count = 0

    def push_playback_pcm(
        self,
        data: bytes,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        self.playback.append(
            (bytes(data), sample_rate, num_channels, samples_per_channel)
        )

    def flush_playback(self) -> None:
        self.flush_count += 1


def pcm(value: int, samples: int = 480) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


def make_runtime(
    detector: FakeDetector,
    *,
    pre_roll_seconds: float,
    ring_buffer_seconds: float,
) -> PairedAudioRuntime:
    return PairedAudioRuntime(
        detector,  # type: ignore[arg-type]
        av_source=FakePairedAVSource(),  # type: ignore[arg-type]
        pre_roll_seconds=pre_roll_seconds,
        ring_buffer_seconds=ring_buffer_seconds,
    )


@pytest.mark.asyncio
async def test_clean_paired_pcm_routes_to_wake_without_local_input() -> None:
    detector = FakeDetector()
    runtime = make_runtime(
        detector,
        pre_roll_seconds=0.02,
        ring_buffer_seconds=0.05,
    )
    runtime._loop = asyncio.get_running_loop()
    detector.enable()

    await asyncio.to_thread(
        runtime.feed_clean_pcm,
        pcm(7),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
        observed_at_monotonic=10.0,
    )
    await asyncio.sleep(0.01)

    assert len(detector.frames) == 1
    assert detector.frames[0].sample_rate == 48_000
    assert detector.frames[0].samples_per_channel == 480
    assert np.frombuffer(detector.frames[0].data, dtype=np.int16)[0] == 7


@pytest.mark.asyncio
async def test_clean_paired_pcm_switches_from_wake_to_active_session() -> None:
    detector = FakeDetector()
    runtime = make_runtime(
        detector,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=0.05,
    )
    runtime._loop = asyncio.get_running_loop()
    detector.enable()
    session_input = SessionAudioInput(capacity_frames=5)
    runtime.activate_session(session_input)

    await asyncio.to_thread(
        runtime.feed_clean_pcm,
        pcm(11),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
        observed_at_monotonic=20.0,
    )
    frame = await asyncio.wait_for(session_input.__anext__(), timeout=1)

    assert detector.frames == []
    assert np.frombuffer(frame.data, dtype=np.int16)[0] == 11


@pytest.mark.asyncio
async def test_clean_paired_pcm_preserves_pre_roll_timestamp_for_observed_input() -> (
    None
):
    detector = FakeDetector()
    runtime = make_runtime(
        detector,
        pre_roll_seconds=0.01,
        ring_buffer_seconds=0.05,
    )
    runtime._loop = asyncio.get_running_loop()
    detector.enable()

    await asyncio.to_thread(
        runtime.feed_clean_pcm,
        pcm(13),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
        observed_at_monotonic=30.0,
    )
    await asyncio.sleep(0.01)

    observed: list[float] = []

    class ObservedInput(SessionAudioInput):
        def push_frame(self, frame, *, observed_at_monotonic=None):
            assert observed_at_monotonic is not None
            observed.append(observed_at_monotonic)
            return super().push_frame(
                frame,
                observed_at_monotonic=observed_at_monotonic,
            )

    runtime.activate_session(ObservedInput(capacity_frames=5))

    assert observed == [pytest.approx(30.0)]


def test_clean_paired_pcm_rejects_noncanonical_capture_format() -> None:
    runtime = make_runtime(
        FakeDetector(),
        pre_roll_seconds=0.0,
        ring_buffer_seconds=0.05,
    )

    with pytest.raises(ValueError, match="48000 Hz"):
        runtime.feed_clean_pcm(
            pcm(1, samples=160),
            sample_rate=16_000,
            num_channels=1,
            samples_per_channel=160,
            observed_at_monotonic=1.0,
        )


@pytest.mark.asyncio
async def test_runtime_start_requires_running_full_duplex_source() -> None:
    detector = FakeDetector()
    source = FakePairedAVSource()
    source.running = False
    runtime = PairedAudioRuntime(
        detector,  # type: ignore[arg-type]
        av_source=source,  # type: ignore[arg-type]
        pre_roll_seconds=0.0,
        ring_buffer_seconds=0.05,
    )

    with pytest.raises(RuntimeError, match="must be running"):
        await runtime.start()

    source.running = True
    source.playback_enabled = False
    with pytest.raises(RuntimeError, match="playback/AEC"):
        await runtime.start()
