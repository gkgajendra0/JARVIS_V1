from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice import runtime as voice_runtime
from jarvis.voice import scripted_speech


def test_scripted_speech_uses_tts_provider_not_brain_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_gemini_tts(**kwargs):
        captured.update(kwargs)
        return object()

    def fail_openai_tts(**kwargs):
        del kwargs
        raise AssertionError("brain provider must not select scripted TTS")

    monkeypatch.setenv("OPENAI_API_KEY", "paid-brain-openai")
    monkeypatch.setenv("JARVIS_TTS_GOOGLE_API_KEY", "free-tier-tts-google")
    monkeypatch.setattr(scripted_speech.google.beta, "GeminiTTS", fake_gemini_tts)
    monkeypatch.setattr(scripted_speech.openai, "TTS", fail_openai_tts)

    speech = scripted_speech.build_scripted_speech(
        JarvisConfig(
            ai_provider="openai",
            tts_provider="gemini",
            gemini_realtime_voice="Charon",
        )
    )

    assert isinstance(speech, scripted_speech.LiveKitScriptedSpeech)
    assert captured["api_key"] == "free-tier-tts-google"
    assert captured["voice_name"] == "Charon"
    assert captured["model"] == "gemini-3.8-flash-tts"


def test_scripted_speech_can_use_flash_lite_without_changing_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_gemini_tts(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("JARVIS_TTS_GOOGLE_API_KEY", "tts-key")
    monkeypatch.setattr(scripted_speech.google.beta, "GeminiTTS", fake_gemini_tts)

    scripted_speech.build_scripted_speech(
        JarvisConfig(
            tts_provider="gemini",
            gemini_tts_model="gemini-3.8-flash-lite-tts",
            gemini_realtime_voice="Charon",
        )
    )

    assert captured["model"] == "gemini-3.8-flash-lite-tts"
    assert captured["voice_name"] == "Charon"


def test_scripted_speech_can_select_openai_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_openai_tts(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("GOOGLE_API_KEY", "brain-google")
    monkeypatch.setenv("JARVIS_TTS_OPENAI_API_KEY", "tts-only-openai")
    monkeypatch.setattr(scripted_speech.openai, "TTS", fake_openai_tts)

    speech = scripted_speech.build_scripted_speech(
        JarvisConfig(
            ai_provider="gemini",
            tts_provider="openai",
            realtime_voice="marin",
        )
    )

    assert isinstance(speech, scripted_speech.LiveKitScriptedSpeech)
    assert captured["api_key"] == "tts-only-openai"
    assert captured["voice"] == "marin"
    assert captured["model"] == "gpt-4o-mini-tts"


def test_normal_lifecycle_runtime_does_not_require_scripted_tts_builder() -> None:
    controller = voice_runtime.VoiceRuntimeController(
        JarvisConfig(ai_provider="gemini", tts_provider="gemini"),
        SimpleNamespace(output=object()),  # type: ignore[arg-type]
    )

    assert controller._scripted_speech is None
    assert controller._owns_scripted_speech is False
    assert hasattr(controller, "_speak_ephemeral_realtime_message")
