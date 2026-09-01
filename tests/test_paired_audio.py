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


class FakeApm:
    def __init__(self) -> None:
        self.delays: list[int] = []
        self.processed = []

    def set_stream_delay_ms(self, delay_ms: int) -> None:
        self.delays.append(delay_ms)

    def process_stream(self, frame) -> None:
        self.processed.append(frame)


def pcm(value: int, samples: int = 480) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


@pytest.mark.asyncio
async def test_paired_pcm_routes_to_wake_without_local_input() -> None:
    detector = FakeDetector()
    apm = FakeApm()
    runtime = PairedAudioRuntime(
        detector,  # type: ignore[arg-type]
        output_device_name=None,
        pre_roll_seconds=0.02,
        ring_buffer_seconds=0.05,
        clock=lambda: 10.02,
        apm_factory=lambda **_: apm,
    )
    runtime._loop = asyncio.get_running_loop()
    runtime._apm = apm
    detector.enable()

    await asyncio.to_thread(
        runtime.feed_external_pcm,
        pcm(7),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
        observed_at_monotonic=10.0,
    )
    await asyncio.sleep(0.01)

    assert len(apm.processed) == 1
    assert len(detector.frames) == 1
    assert detector.frames[0].sample_rate == 48_000
    assert detector.frames[0].samples_per_channel == 480
    assert apm.delays and apm.delays[0] >= 0


@pytest.mark.asyncio
async def test_paired_pcm_switches_from_wake_to_active_session() -> None:
    detector = FakeDetector()
    apm = FakeApm()
    runtime = PairedAudioRuntime(
        detector,  # type: ignore[arg-type]
        output_device_name=None,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=0.05,
        clock=lambda: 20.01,
        apm_factory=lambda **_: apm,
    )
    runtime._loop = asyncio.get_running_loop()
    runtime._apm = apm
    detector.enable()
    session_input = SessionAudioInput(capacity_frames=5)
    runtime.activate_session(session_input)

    await asyncio.to_thread(
        runtime.feed_external_pcm,
        pcm(11),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
        observed_at_monotonic=20.0,
    )
    frame = await asyncio.wait_for(session_input.__anext__(), timeout=1)

    assert detector.frames == []
    assert np.frombuffer(frame.data, dtype=np.int16)[0] == 11
    assert len(apm.processed) == 1


@pytest.mark.asyncio
async def test_paired_pcm_preserves_pre_roll_timestamp_for_observed_input() -> None:
    detector = FakeDetector()
    apm = FakeApm()
    runtime = PairedAudioRuntime(
        detector,  # type: ignore[arg-type]
        output_device_name=None,
        pre_roll_seconds=0.01,
        ring_buffer_seconds=0.05,
        clock=lambda: 30.01,
        apm_factory=lambda **_: apm,
    )
    runtime._loop = asyncio.get_running_loop()
    runtime._apm = apm
    detector.enable()

    await asyncio.to_thread(
        runtime.feed_external_pcm,
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


def test_paired_pcm_rejects_noncanonical_capture_format() -> None:
    runtime = PairedAudioRuntime(
        FakeDetector(),  # type: ignore[arg-type]
        output_device_name=None,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=0.05,
    )

    with pytest.raises(ValueError, match="48000 Hz"):
        runtime.feed_external_pcm(
            pcm(1, samples=160),
            sample_rate=16_000,
            num_channels=1,
            samples_per_channel=160,
            observed_at_monotonic=1.0,
        )
