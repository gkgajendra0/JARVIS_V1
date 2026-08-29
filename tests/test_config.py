import pytest

from jarvis.config import JarvisConfig


def test_voice_configuration_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_REALTIME_PROVIDER", " GEMINI ")
    monkeypatch.setenv("JARVIS_REALTIME_MODEL", " model-x ")
    monkeypatch.setenv("JARVIS_REALTIME_VOICE", " voice-y ")
    monkeypatch.setenv("JARVIS_GEMINI_REALTIME_MODEL", " gemini-x ")
    monkeypatch.setenv("JARVIS_GEMINI_REALTIME_VOICE", " Charon ")
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "off")
    monkeypatch.setenv("JARVIS_WAKE_MODEL_PATH", " C:\\models\\jarvis.onnx ")
    monkeypatch.setenv("JARVIS_WAKE_THRESHOLD", "0.72")
    monkeypatch.setenv("JARVIS_AUDIO_PRE_ROLL_SECONDS", "0.8")
    monkeypatch.setenv("JARVIS_VISION_ENABLED", "true")
    monkeypatch.setenv(
        "JARVIS_BLAZEFACE_MODEL_PATH", " C:\\models\\blazeface.tflite "
    )

    config = JarvisConfig.from_environment()

    assert config.realtime_provider == "gemini"
    assert config.realtime_model == "model-x"
    assert config.realtime_voice == "voice-y"
    assert config.gemini_realtime_model == "gemini-x"
    assert config.gemini_realtime_voice == "Charon"
    assert config.show_transcript is False
    assert config.wake_model_path == "C:\\models\\jarvis.onnx"
    assert config.wake_threshold == 0.72
    assert config.audio_pre_roll_seconds == 0.8
    assert config.vision_enabled is True
    assert config.vision_head_model_path == "C:\\models\\blazeface.tflite"


def test_invalid_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_SHOW_TRANSCRIPT"):
        JarvisConfig.from_environment()


def test_invalid_vision_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_VISION_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_VISION_ENABLED"):
        JarvisConfig.from_environment()


def test_invalid_realtime_provider_fails_truthfully() -> None:
    with pytest.raises(ValueError, match="JARVIS_REALTIME_PROVIDER"):
        JarvisConfig(realtime_provider="unknown")


def test_invalid_wake_and_buffer_settings_fail_truthfully() -> None:
    with pytest.raises(ValueError, match="wake_threshold"):
        JarvisConfig(wake_threshold=0)
    with pytest.raises(ValueError, match="pre-roll"):
        JarvisConfig(audio_ring_buffer_seconds=1, audio_pre_roll_seconds=2)
