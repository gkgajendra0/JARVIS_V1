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
            ai_provider="gemini",
            wake_model_path=str(wake),
            audio_input_device="name:Osmo|hostapi:Windows WASAPI",
            audio_output_device="name:TV|hostapi:Windows WASAPI",
        )
    )

    assert all(check.ok for check in checks)
    assert {check.label for check in checks} >= {
        "Wake model",
        "Cloud AI credentials",
        "Conversation microphone",
        "Conversation speaker",
    }


def test_preflight_allows_audio_only_speaker_shadow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wake = tmp_path / "jarvis.onnx"
    wake.write_bytes(b"model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(preflight, "_audio_checks", lambda _config: [])

    checks = preflight.run_startup_preflight(
        JarvisConfig(
            ai_provider="gemini",
            wake_model_path=str(wake),
            audio_input_device="name:Osmo|hostapi:Windows WASAPI",
            audio_output_device="name:TV|hostapi:Windows WASAPI",
            vision_enabled=False,
            speaker_shadow_enabled=True,
            active_speaker_shadow_enabled=False,
        )
    )

    assert all(check.ok for check in checks)
    speaker = next(check for check in checks if check.label == "Speaker shadow mode")
    assert "does not require vision" in speaker.detail


def test_preflight_still_requires_vision_for_active_speaker_shadow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wake = tmp_path / "jarvis.onnx"
    wake.write_bytes(b"model")
    lr_asd = tmp_path / "lr-asd.pth"
    lr_asd.write_bytes(b"model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(preflight, "_audio_checks", lambda _config: [])

    checks = preflight.run_startup_preflight(
        JarvisConfig(
            ai_provider="gemini",
            wake_model_path=str(wake),
            audio_input_device="name:Osmo|hostapi:Windows WASAPI",
            audio_output_device="name:TV|hostapi:Windows WASAPI",
            vision_enabled=False,
            speaker_shadow_enabled=True,
            active_speaker_shadow_enabled=True,
            active_speaker_model_path=str(lr_asd),
        )
    )

    active = next(
        check for check in checks if check.label == "Active-speaker dependency"
    )
    assert active.ok is False
    assert "requires vision" in active.detail


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
        ai_provider="openai",
        wake_model_path=None,
        audio_input_device="name:Osmo|hostapi:Windows WASAPI",
        audio_output_device="name:TV|hostapi:Windows WASAPI",
    )

    with pytest.raises(StartupPreflightError, match="preflight failure"):
        preflight.require_startup_preflight(config)

    output = capsys.readouterr().out
    assert "Wake model" in output
    assert "Cloud AI credentials" in output
    assert "Conversation speaker" in output
