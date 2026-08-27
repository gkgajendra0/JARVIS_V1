import pytest

from jarvis.config import JarvisConfig


def test_voice_configuration_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_REALTIME_MODEL", " model-x ")
    monkeypatch.setenv("JARVIS_REALTIME_VOICE", " voice-y ")
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "off")

    config = JarvisConfig.from_environment()

    assert config.realtime_model == "model-x"
    assert config.realtime_voice == "voice-y"
    assert config.show_transcript is False


def test_invalid_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_SHOW_TRANSCRIPT"):
        JarvisConfig.from_environment()
