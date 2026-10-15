from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from livekit import rtc

from jarvis.voice.media_devices_audio import (
    MediaDevicesAudioOutput,
    MediaDevicesConversationRuntime,
)


def test_production_output_requires_48khz(monkeypatch) -> None:
    checked: list[tuple[int | None, int]] = []

    def check_output_settings(**options) -> None:
        checked.append((options["device"], int(options["samplerate"])))

    fake_sounddevice = SimpleNamespace(
        PortAudioError=RuntimeError,
        check_output_settings=check_output_settings,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    MediaDevicesConversationRuntime._require_48k_output(49)

    assert checked == [(49, 48_000)]


def test_production_output_rejects_non_48khz_endpoint(monkeypatch) -> None:
    def check_output_settings(**options) -> None:
        del options
        raise ValueError("invalid sample rate")

    fake_sounddevice = SimpleNamespace(
        PortAudioError=RuntimeError,
        check_output_settings=check_output_settings,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    with pytest.raises(RuntimeError, match="48000 Hz"):
        MediaDevicesConversationRuntime._require_48k_output(54)


def test_playback_diagnostic_measures_nonzero_pcm() -> None:
    samples = np.array([0, 1_000, -2_000, 500], dtype=np.int16)
    frame = rtc.AudioFrame(
        data=samples.tobytes(),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=samples.size,
    )

    peak_abs, sum_squares, sample_count = MediaDevicesAudioOutput._frame_energy(frame)

    assert peak_abs == 2_000
    assert sum_squares == pytest.approx(5_250_000.0)
    assert sample_count == 4
    assert MediaDevicesAudioOutput._rms_dbfs(sum_squares, sample_count) > -40.0


def test_playback_diagnostic_reads_livekit_player_state() -> None:
    player = SimpleNamespace(
        _buffer=bytearray(960),
        _stream=SimpleNamespace(active=True, stopped=False),
    )

    assert MediaDevicesAudioOutput._player_state(player) == (960, True, False)


class _FakeOutputPlayer:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.removed: list[object] = []

    async def add_track(self, track: object) -> None:
        self.added.append(track)

    async def remove_track(self, track: object) -> None:
        self.removed.append(track)


@pytest.mark.asyncio
async def test_media_devices_output_detaches_silent_track_between_playback() -> None:
    player = _FakeOutputPlayer()
    output = MediaDevicesAudioOutput(object(), output_device=None)
    track = object()
    output._player = player
    output._track = track  # type: ignore[assignment]
    output._loop = asyncio.get_running_loop()

    await output._ensure_track_attached()
    assert player.added == [track]
    assert output._track_attached is True

    output._schedule_detach_if_idle()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert player.removed == [track]
    assert output._track_attached is False

    await output._ensure_track_attached()
    assert player.added == [track, track]
    assert output._track_attached is True


class _BlockingRemovePlayer(_FakeOutputPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.remove_started = asyncio.Event()
        self.allow_remove = asyncio.Event()

    async def remove_track(self, track: object) -> None:
        self.remove_started.set()
        await self.allow_remove.wait()
        await super().remove_track(track)


@pytest.mark.asyncio
async def test_media_devices_output_does_not_cancel_inflight_track_detach() -> None:
    player = _BlockingRemovePlayer()
    output = MediaDevicesAudioOutput(object(), output_device=None)
    track = object()
    output._player = player
    output._track = track  # type: ignore[assignment]
    output._loop = asyncio.get_running_loop()

    await output._ensure_track_attached()
    output._schedule_detach_if_idle()
    await asyncio.wait_for(player.remove_started.wait(), timeout=1.0)

    reattach = asyncio.create_task(output._ensure_track_attached())
    await asyncio.sleep(0)
    assert reattach.done() is False

    player.allow_remove.set()
    await asyncio.wait_for(reattach, timeout=1.0)

    assert player.removed == [track]
    assert player.added == [track, track]
    assert output._track_attached is True
