from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime


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
