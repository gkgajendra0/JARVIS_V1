from __future__ import annotations

import asyncio

import numpy as np
import pytest
from livekit import rtc
from livekit.agents import vad

from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.barge_in import BargeInGate


_STOP = object()


class FakeVADStream:
    def __init__(self) -> None:
        self.frames: list[rtc.AudioFrame] = []
        self.flush_count = 0
        self.closed = False
        self.events: asyncio.Queue[object] = asyncio.Queue()

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        self.frames.append(frame)

    def flush(self) -> None:
        self.flush_count += 1

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is _STOP:
            raise StopAsyncIteration
        return event

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.events.put_nowait(_STOP)


class FakeVAD:
    def __init__(self) -> None:
        self.stream_instance = FakeVADStream()

    def stream(self) -> FakeVADStream:
        return self.stream_instance


def frame(value: int) -> rtc.AudioFrame:
    samples = np.full(480, value, dtype=np.int16)
    return rtc.AudioFrame(
        data=samples.tobytes(),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=480,
    )


def start_event() -> vad.VADEvent:
    return vad.VADEvent(
        type=vad.VADEventType.START_OF_SPEECH,
        samples_index=10_560,
        timestamp=0.22,
        speech_duration=0.22,
        silence_duration=0.0,
    )


def end_event() -> vad.VADEvent:
    return vad.VADEvent(
        type=vad.VADEventType.END_OF_SPEECH,
        samples_index=24_000,
        timestamp=0.50,
        speech_duration=0.30,
        silence_duration=0.20,
    )


@pytest.mark.asyncio
async def test_assistant_playback_withholds_unconfirmed_clean_audio() -> None:
    fake_vad = FakeVAD()
    gate = BargeInGate(vad_model=fake_vad, buffer_seconds=0.05)
    target = SessionAudioInput(capacity_frames=10)
    gate.set_target(target)
    gate.set_agent_speaking(True)

    assert gate.push_frame(frame(11), observed_at_monotonic=10.0)

    assert target._queue.qsize() == 0
    assert gate.buffered_frames == 1
    assert len(fake_vad.stream_instance.frames) == 1

    await gate.aclose()
    target.close()


@pytest.mark.asyncio
async def test_confirmed_speech_releases_prefix_and_live_frames() -> None:
    fake_vad = FakeVAD()
    gate = BargeInGate(vad_model=fake_vad, buffer_seconds=0.05)
    target = SessionAudioInput(capacity_frames=10)
    gate.set_target(target)
    gate.set_agent_speaking(True)

    first = frame(21)
    second = frame(22)
    assert gate.push_frame(first, observed_at_monotonic=20.0)
    assert target._queue.qsize() == 0

    fake_vad.stream_instance.events.put_nowait(start_event())
    await asyncio.sleep(0)

    assert gate.gate_open is True
    assert gate.buffered_frames == 0
    assert target._queue.qsize() == 1

    assert gate.push_frame(second, observed_at_monotonic=20.01)
    assert target._queue.qsize() == 2

    released_first = await target.__anext__()
    released_second = await target.__anext__()
    assert np.frombuffer(released_first.data, dtype=np.int16)[0] == 21
    assert np.frombuffer(released_second.data, dtype=np.int16)[0] == 22

    await gate.aclose()
    target.close()


@pytest.mark.asyncio
async def test_playback_end_discards_unconfirmed_echo_and_restores_normal_flow() -> None:
    fake_vad = FakeVAD()
    gate = BargeInGate(vad_model=fake_vad, buffer_seconds=0.05)
    target = SessionAudioInput(capacity_frames=10)
    gate.set_target(target)
    gate.set_agent_speaking(True)

    assert gate.push_frame(frame(31), observed_at_monotonic=30.0)
    assert target._queue.qsize() == 0

    gate.set_agent_speaking(False)
    assert gate.buffered_frames == 0
    assert fake_vad.stream_instance.flush_count >= 1

    assert gate.push_frame(frame(32), observed_at_monotonic=30.01)
    assert target._queue.qsize() == 1
    released = await target.__anext__()
    assert np.frombuffer(released.data, dtype=np.int16)[0] == 32

    await gate.aclose()
    target.close()


@pytest.mark.asyncio
async def test_open_gate_stays_open_until_user_speech_ends() -> None:
    fake_vad = FakeVAD()
    gate = BargeInGate(vad_model=fake_vad, buffer_seconds=0.05)
    target = SessionAudioInput(capacity_frames=10)
    gate.set_target(target)
    gate.set_agent_speaking(True)

    assert gate.push_frame(frame(41), observed_at_monotonic=40.0)
    fake_vad.stream_instance.events.put_nowait(start_event())
    await asyncio.sleep(0)
    assert gate.gate_open is True

    gate.set_agent_speaking(False)
    assert gate.gate_open is True
    assert gate.push_frame(frame(42), observed_at_monotonic=40.01)

    fake_vad.stream_instance.events.put_nowait(end_event())
    await asyncio.sleep(0)
    assert gate.gate_open is False

    await gate.aclose()
    target.close()
