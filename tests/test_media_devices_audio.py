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
from jarvis.voice.safe_media_devices import SafeMediaDevices


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


class _FakeAudioSource:
    def __init__(self) -> None:
        self.frames: list[rtc.AudioFrame] = []
        self.queued_duration = 0.0
        self.clear_calls = 0

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        self.frames.append(frame)
        self.queued_duration += frame.duration

    def clear_queue(self) -> None:
        self.frames.clear()
        self.queued_duration = 0.0
        self.clear_calls += 1


def _pcm_frame(duration_ms: int, *, value: int = 1_000) -> rtc.AudioFrame:
    samples = 48_000 * duration_ms // 1_000
    pcm = np.full(samples, value, dtype=np.int16)
    return rtc.AudioFrame(
        data=pcm.tobytes(),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=samples,
    )


def _prebuffer_test_output() -> tuple[
    MediaDevicesAudioOutput,
    _FakeAudioSource,
    _FakeOutputPlayer,
    object,
]:
    output = MediaDevicesAudioOutput(object(), output_device=None)
    source = _FakeAudioSource()
    player = _FakeOutputPlayer()
    track = object()
    output._source = source  # type: ignore[assignment]
    output._player = player
    output._track = track  # type: ignore[assignment]
    output._loop = asyncio.get_running_loop()
    return output, source, player, track


@pytest.mark.asyncio
async def test_media_devices_output_primes_300ms_before_realtime_playout() -> None:
    output, source, player, track = _prebuffer_test_output()
    frame = _pcm_frame(100)

    await output.capture_frame(frame)
    await output.capture_frame(frame)

    assert source.frames == []
    assert player.added == []
    assert output._playback_started is False

    await output.capture_frame(frame)

    assert player.added == [track]
    assert len(source.frames) == 3
    assert source.queued_duration == pytest.approx(0.3)
    assert output._playback_started is True

    output.clear_buffer()


@pytest.mark.asyncio
async def test_media_devices_output_flush_releases_short_primed_segment() -> None:
    output, source, player, track = _prebuffer_test_output()

    await output.capture_frame(_pcm_frame(100))
    assert source.frames == []
    assert player.added == []

    output.flush()
    flush_task = output._flush_task
    assert flush_task is not None
    await flush_task

    assert player.added == [track]
    assert len(source.frames) == 1
    assert source.queued_duration == pytest.approx(0.1)
    assert len(output._segments) == 1

    output.clear_buffer()


@pytest.mark.asyncio
async def test_media_devices_output_interrupt_before_prebuffer_plays_no_stale_audio() -> None:
    output, source, player, _ = _prebuffer_test_output()

    await output.capture_frame(_pcm_frame(100))
    output.clear_buffer()

    assert player.added == []
    assert source.frames == []
    assert output._prebuffer_frames == []
    assert output._prebuffer_samples == 0
    assert output.last_completed_quality is not None
    assert output.last_completed_quality.interrupted is True
    assert output.last_completed_quality.duration_seconds == 0.0


def test_safe_media_devices_keeps_upstream_output_player() -> None:
    assert SafeMediaDevices.open_output is rtc.MediaDevices.open_output

