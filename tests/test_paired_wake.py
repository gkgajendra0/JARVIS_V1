from __future__ import annotations

import asyncio
import threading

import numpy as np
import pytest
from livekit import rtc

from jarvis.voice.paired_wake import PairedWakeDetectorBridge


class FakeWakeDetector:
    def __init__(self) -> None:
        self.enabled = False
        self.frames: list[rtc.AudioFrame] = []
        self.frame_received = asyncio.Event()
        self.closed = False

    def enable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enabled = True

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enabled = False

    def clear_buffer(self) -> None:
        self.frames.clear()

    def feed(self, frame: rtc.AudioFrame) -> None:
        if not self.enabled:
            return
        self.frames.append(frame)
        self.frame_received.set()

    async def wait_for_detection(self):
        raise AssertionError("not used")

    async def aclose(self) -> None:
        self.closed = True
        self.enabled = False


def _frame(value: int, *, sample_rate: int = 48_000, samples: int = 480) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=np.full(samples, value, dtype=np.int16).tobytes(),
        sample_rate=sample_rate,
        num_channels=1,
        samples_per_channel=samples,
    )


@pytest.mark.asyncio
async def test_local_conversation_audio_is_not_used_for_paired_wake() -> None:
    detector = FakeWakeDetector()
    bridge = PairedWakeDetectorBridge(detector)  # type: ignore[arg-type]
    bridge.enable()

    bridge.feed(_frame(111))
    await asyncio.sleep(0)

    assert detector.frames == []


@pytest.mark.asyncio
async def test_paired_pcm_crosses_native_thread_boundary_onto_event_loop() -> None:
    detector = FakeWakeDetector()
    bridge = PairedWakeDetectorBridge(detector)  # type: ignore[arg-type]
    bridge.enable()
    samples = np.full(160, 222, dtype=np.int16)

    thread = threading.Thread(
        target=bridge.feed_external_pcm,
        kwargs={
            "data": samples.tobytes(),
            "sample_rate": 16_000,
            "num_channels": 1,
            "samples_per_channel": 160,
        },
    )
    thread.start()
    thread.join()

    await asyncio.wait_for(detector.frame_received.wait(), timeout=1)

    assert len(detector.frames) == 1
    observed = detector.frames[0]
    assert observed.sample_rate == 16_000
    assert observed.num_channels == 1
    np.testing.assert_array_equal(
        np.frombuffer(observed.data, dtype=np.int16),
        samples,
    )


@pytest.mark.asyncio
async def test_paired_wake_bridge_drops_frames_until_runtime_enables_it() -> None:
    detector = FakeWakeDetector()
    bridge = PairedWakeDetectorBridge(detector)  # type: ignore[arg-type]
    samples = np.full(160, 333, dtype=np.int16)

    bridge.feed_external_pcm(
        samples.tobytes(),
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=160,
    )
    await asyncio.sleep(0)

    assert detector.frames == []

    bridge.enable()
    bridge.feed_external_pcm(
        samples.tobytes(),
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=160,
    )
    await asyncio.wait_for(detector.frame_received.wait(), timeout=1)

    assert len(detector.frames) == 1
