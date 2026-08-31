from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import pytest
from livekit import rtc

from jarvis.voice.audio import (
    LocalAudioOutput,
    LocalAudioRuntime,
    SessionAudioInput,
)


def frame(value: int, samples: int = 480) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=np.full(samples, value, dtype=np.int16).tobytes(),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=samples,
    )


class FakeDetector:
    def __init__(self) -> None:
        self.enabled = True

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enabled = False


class FakeMediaDevices:
    def __init__(self) -> None:
        self.input_options = None

    def open_input(self, **options):
        self.input_options = options
        return object()


class FakeApm:
    def __init__(self) -> None:
        self.reverse_frames: list[rtc.AudioFrame] = []

    def process_reverse_stream(self, audio_frame: rtc.AudioFrame) -> None:
        self.reverse_frames.append(audio_frame)


@pytest.mark.asyncio
async def test_session_audio_input_is_bounded_and_closes() -> None:
    audio_input = SessionAudioInput(capacity_frames=1)
    first = frame(1)

    assert audio_input.push_frame(first) is True
    assert audio_input.push_frame(frame(2)) is False
    assert await audio_input.__anext__() is first

    audio_input.close()
    with pytest.raises(StopAsyncIteration):
        await audio_input.__anext__()


@pytest.mark.asyncio
async def test_activation_sends_pre_roll_in_order_without_reopening_device() -> None:
    runtime = LocalAudioRuntime(
        FakeDetector(),  # type: ignore[arg-type]
        input_device_name=None,
        output_device_name=None,
        pre_roll_seconds=0.02,
        ring_buffer_seconds=0.05,
    )
    runtime._append_ring(frame(1))
    runtime._append_ring(frame(2))
    runtime._append_ring(frame(3))
    session_input = SessionAudioInput(capacity_frames=5)

    runtime.activate_session(session_input)

    first = await session_input.__anext__()
    second = await session_input.__anext__()
    assert np.frombuffer(first.data, dtype=np.int16)[0] == 2
    assert np.frombuffer(second.data, dtype=np.int16)[0] == 3
    assert runtime.detector.enabled is False


def test_input_capture_has_bounded_provider_startup_cushion() -> None:
    runtime = LocalAudioRuntime(
        FakeDetector(),  # type: ignore[arg-type]
        input_device_name=None,
        output_device_name=None,
        pre_roll_seconds=0.02,
        ring_buffer_seconds=0.05,
    )
    media_devices = FakeMediaDevices()
    runtime._media_devices = media_devices

    runtime._open_input_capture(57)

    assert media_devices.input_options == {
        "input_device": 57,
        "queue_capacity": 500,
        "enable_aec": True,
        "noise_suppression": True,
        "high_pass_filter": True,
        "auto_gain_control": True,
    }


def test_device_name_resolution_rejects_missing_and_ambiguous_devices() -> None:
    devices = [
        {
            "index": 6,
            "name": "Voicemeeter Out B1",
            "hostapi": 0,
            "hostapi_name": "MME",
        },
        {
            "index": 57,
            "name": "Voicemeeter Out B1",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        },
        {
            "index": 58,
            "name": "Voicemeeter Out A5",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        },
    ]

    assert LocalAudioRuntime._resolve_device(devices, "index:57", kind="input") == 57
    assert LocalAudioRuntime._resolve_device(devices, "Out A5", kind="input") == 58
    with pytest.raises(RuntimeError, match="not found"):
        LocalAudioRuntime._resolve_device(devices, "Tribit", kind="input")
    with pytest.raises(RuntimeError, match="index not found"):
        LocalAudioRuntime._resolve_device(devices, "index:45", kind="input")
    with pytest.raises(RuntimeError, match="index is invalid"):
        LocalAudioRuntime._resolve_device(devices, "index:B1", kind="input")
    with pytest.raises(RuntimeError, match=r"index:6.*index:57"):
        LocalAudioRuntime._resolve_device(devices, "Voicemeeter Out B1", kind="input")


def test_stable_device_selector_disambiguates_host_api() -> None:
    devices = [
        {
            "index": 6,
            "name": "Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)",
            "hostapi": 0,
            "hostapi_name": "MME",
        },
        {
            "index": 57,
            "name": "Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        },
    ]

    selector = "name:Voicemeeter Out B1|hostapi:Windows WASAPI"

    assert LocalAudioRuntime._resolve_device(devices, selector, kind="input") == 57


def test_stable_device_selector_survives_portaudio_index_drift() -> None:
    selector = "name:Speakers (Tribit XSound Plus 2)|hostapi:Windows WASAPI"
    before = [
        {
            "index": 54,
            "name": "Speakers (Tribit XSound Plus 2)",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        }
    ]
    after = [
        {
            "index": 73,
            "name": "Speakers (Tribit XSound Plus 2)",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        }
    ]

    assert LocalAudioRuntime._resolve_device(before, selector, kind="output") == 54
    assert LocalAudioRuntime._resolve_device(after, selector, kind="output") == 73


def test_stable_device_selector_fails_closed_on_missing_host_api() -> None:
    devices = [
        {
            "index": 20,
            "name": "Speakers (Tribit XSound Plus 2)",
            "hostapi": 0,
            "hostapi_name": "MME",
        }
    ]

    selector = "name:Speakers (Tribit XSound Plus 2)|hostapi:Windows WASAPI"

    with pytest.raises(RuntimeError, match="not found for stable selector"):
        LocalAudioRuntime._resolve_device(devices, selector, kind="output")


def test_stable_device_selector_requires_name_and_host_api() -> None:
    devices = [
        {
            "index": 54,
            "name": "Speakers (Tribit XSound Plus 2)",
            "hostapi": 2,
            "hostapi_name": "Windows WASAPI",
        }
    ]

    with pytest.raises(RuntimeError, match="require both"):
        LocalAudioRuntime._resolve_device(
            devices,
            "name:Speakers (Tribit XSound Plus 2)",
            kind="output",
        )


def test_output_rate_prefers_canonical_when_endpoint_supports_it(monkeypatch) -> None:
    import sounddevice as sd

    checked: list[int] = []

    def fake_check_output_settings(**options) -> None:
        checked.append(int(options["samplerate"]))

    monkeypatch.setattr(sd, "check_output_settings", fake_check_output_settings)

    assert LocalAudioRuntime._select_output_sample_rate(54) == 48_000
    assert checked == [48_000]


def test_output_rate_falls_back_to_native_endpoint_rate(monkeypatch) -> None:
    import sounddevice as sd

    checked: list[int] = []

    def fake_check_output_settings(**options) -> None:
        rate = int(options["samplerate"])
        checked.append(rate)
        if rate == 48_000:
            raise ValueError("invalid sample rate")

    monkeypatch.setattr(sd, "check_output_settings", fake_check_output_settings)
    monkeypatch.setattr(
        sd,
        "query_devices",
        lambda device: {"index": device, "default_samplerate": 44_100.0},
    )

    assert LocalAudioRuntime._select_output_sample_rate(54) == 44_100
    assert checked == [48_000, 44_100]


@dataclass
class TimeInfo:
    currentTime: float = 0.0
    outputBufferDacTime: float = 0.01


@pytest.mark.asyncio
async def test_local_output_reports_physical_completion_and_interruption() -> None:
    output = LocalAudioOutput(output_device=None)
    finished = []
    output.on("playback_finished", finished.append)
    output._loop = asyncio.get_running_loop()

    await output.capture_frame(frame(1))
    output.flush()
    outdata = np.zeros((480, 1), dtype=np.int16)
    output._playback_callback(outdata, 480, TimeInfo(), None)
    await asyncio.sleep(0)

    assert finished[0].interrupted is False
    assert finished[0].playback_position == pytest.approx(0.01)

    await output.capture_frame(frame(2))
    output.flush()
    output.clear_buffer()

    assert finished[1].interrupted is True
    assert finished[1].playback_position == 0
    await output.aclose()


@pytest.mark.asyncio
async def test_local_output_resamples_physical_playback_but_keeps_aec_canonical() -> (
    None
):
    apm = FakeApm()
    output = LocalAudioOutput(
        output_device=None,
        apm=apm,
        output_sample_rate=44_100,
    )
    finished = []
    output.on("playback_finished", finished.append)
    output._loop = asyncio.get_running_loop()

    await output.capture_frame(frame(1000))
    output.flush()
    outdata = np.zeros((441, 1), dtype=np.int16)
    output._playback_callback(outdata, 441, TimeInfo(), None)
    output._playback_callback(outdata, 441, TimeInfo(), None)
    await asyncio.sleep(0)

    assert output.physical_sample_rate == 44_100
    assert finished[0].interrupted is False
    assert finished[0].playback_position == pytest.approx(0.01, abs=0.002)
    assert apm.reverse_frames
    assert all(audio_frame.sample_rate == 48_000 for audio_frame in apm.reverse_frames)
    assert all(
        audio_frame.samples_per_channel == 480 for audio_frame in apm.reverse_frames
    )
    await output.aclose()
