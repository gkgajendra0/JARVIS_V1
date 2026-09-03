from __future__ import annotations

import os

import numpy as np
import pytest

from jarvis.voice.krisp_cloud_isolation import (
    KrispCloudIsolationUnavailable,
    _as_pcm16_mono,
    _require_cloud_environment,
)


def test_as_pcm16_mono_preserves_int16() -> None:
    samples = np.asarray([-32768, -1, 0, 1, 32767], dtype=np.int16)
    converted = _as_pcm16_mono(samples)
    assert converted.dtype == np.int16
    assert converted.flags.c_contiguous
    assert np.array_equal(converted, samples)


def test_as_pcm16_mono_clips_float_input() -> None:
    samples = np.asarray([-2.0, -1.0, 0.0, 0.5, 1.0, 2.0], dtype=np.float32)
    converted = _as_pcm16_mono(samples)
    assert converted.tolist() == [-32767, -32767, 0, 16384, 32767, 32767]


def test_require_cloud_environment_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(KrispCloudIsolationUnavailable) as exc_info:
        _require_cloud_environment()
    message = str(exc_info.value)
    assert "LIVEKIT_URL" in message
    assert "LIVEKIT_API_KEY" in message
    assert "LIVEKIT_API_SECRET" in message


def test_require_cloud_environment_returns_values(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": "key",
        "LIVEKIT_API_SECRET": "secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert _require_cloud_environment() == (
        values["LIVEKIT_URL"],
        values["LIVEKIT_API_KEY"],
        values["LIVEKIT_API_SECRET"],
    )
    for name in values:
        os.environ.pop(name, None)
