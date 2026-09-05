from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings


def test_machine_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    saved = save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "gemini",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
        },
        path,
    )

    assert saved == path
    assert load_machine_settings(path) == {
        "JARVIS_AI_PROVIDER": "gemini",
        "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
    }


def test_machine_config_refuses_unapproved_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"OPENAI_API_KEY": "secret"},
            tmp_path / "machine.json",
        )


def test_jarvis_config_uses_machine_profile_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "gemini",
            "JARVIS_WAKE_MODEL_PATH": "C:\\models\\jarvis.onnx",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
            "JARVIS_AUDIO_OUTPUT_DEVICE": "name:TV|hostapi:Windows WASAPI",
            "JARVIS_VISION_ENABLED": "true",
        },
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "openai")
    monkeypatch.setenv(
        "JARVIS_AUDIO_OUTPUT_DEVICE",
        "name:Stale Bluetooth|hostapi:Windows WASAPI",
    )

    config = JarvisConfig.from_environment()
    assert config.ai_provider == "gemini"
    assert config.wake_model_path == "C:\\models\\jarvis.onnx"
    assert config.audio_input_device == "name:Osmo|hostapi:Windows WASAPI"
    assert config.audio_output_device == "name:TV|hostapi:Windows WASAPI"
    assert config.vision_enabled is True


def test_legacy_realtime_provider_machine_setting_migrates_without_breaking_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings({"JARVIS_REALTIME_PROVIDER": "gemini"}, path)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_AI_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_REALTIME_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)

    assert JarvisConfig.from_environment().ai_provider == "gemini"


def test_explicit_diagnostic_mode_allows_environment_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {"JARVIS_AI_PROVIDER": "gemini"},
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "openai")

    assert JarvisConfig.from_environment().ai_provider == "openai"


def test_environment_is_used_when_machine_setting_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings({}, path)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "gemini")

    assert JarvisConfig.from_environment().ai_provider == "gemini"
