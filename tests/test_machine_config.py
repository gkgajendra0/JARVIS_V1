from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings


def test_machine_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    saved = save_machine_settings(
        {
            "JARVIS_REALTIME_PROVIDER": "gemini",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
        },
        path,
    )

    assert saved == path
    assert load_machine_settings(path) == {
        "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
        "JARVIS_REALTIME_PROVIDER": "gemini",
    }


def test_machine_config_refuses_unapproved_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"OPENAI_API_KEY": "secret"},
            tmp_path / "machine.json",
        )


def test_jarvis_config_uses_machine_profile_then_environment_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_REALTIME_PROVIDER": "gemini",
            "JARVIS_WAKE_MODEL_PATH": "C:\\models\\jarvis.onnx",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
            "JARVIS_AUDIO_OUTPUT_DEVICE": "name:TV|hostapi:Windows WASAPI",
            "JARVIS_VISION_ENABLED": "true",
        },
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    for name in (
        "JARVIS_REALTIME_PROVIDER",
        "JARVIS_WAKE_MODEL_PATH",
        "JARVIS_AUDIO_INPUT_DEVICE",
        "JARVIS_AUDIO_OUTPUT_DEVICE",
        "JARVIS_VISION_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    config = JarvisConfig.from_environment()
    assert config.realtime_provider == "gemini"
    assert config.wake_model_path == "C:\\models\\jarvis.onnx"
    assert config.audio_input_device == "name:Osmo|hostapi:Windows WASAPI"
    assert config.audio_output_device == "name:TV|hostapi:Windows WASAPI"
    assert config.vision_enabled is True

    monkeypatch.setenv("JARVIS_REALTIME_PROVIDER", "openai")
    assert JarvisConfig.from_environment().realtime_provider == "openai"
