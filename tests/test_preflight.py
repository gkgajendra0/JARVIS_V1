from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import preflight
from jarvis.config import JarvisConfig
from jarvis.preflight import PreflightCheck, StartupPreflightError


def test_preflight_reports_all_core_checks_without_opening_devices(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wake = tmp_path / "jarvis.onnx"
    wake.write_bytes(b"model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        preflight,
        "_audio_checks",
        lambda _config: [
            PreflightCheck("Conversation microphone", True, "Pocket3 @ 48000 Hz"),
            PreflightCheck("Conversation speaker", True, "TV @ 48000 Hz"),
        ],
    )

    checks = preflight.run_startup_preflight(
        JarvisConfig(
            realtime_provider="gemini",
            wake_model_path=str(wake),
            audio_input_device="name:Osmo|hostapi:Windows WASAPI",
            audio_output_device="name:TV|hostapi:Windows WASAPI",
        )
    )

    assert all(check.ok for check in checks)
    assert {check.label for check in checks} >= {
        "Wake model",
        "Realtime credentials",
        "Conversation microphone",
        "Conversation speaker",
    }


def test_require_preflight_fails_once_after_aggregating_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        preflight,
        "_audio_checks",
        lambda _config: [PreflightCheck("Conversation speaker", False, "not found")],
    )
    config = JarvisConfig(
        realtime_provider="openai",
        wake_model_path=None,
        audio_input_device="name:Osmo|hostapi:Windows WASAPI",
        audio_output_device="name:TV|hostapi:Windows WASAPI",
    )

    with pytest.raises(StartupPreflightError, match="preflight failure"):
        preflight.require_startup_preflight(config)

    output = capsys.readouterr().out
    assert "Wake model" in output
    assert "Realtime credentials" in output
    assert "Conversation speaker" in output
