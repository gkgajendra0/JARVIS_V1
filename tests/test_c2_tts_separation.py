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
    assert captured["model"] == "gemini-3.1-flash-tts-preview"


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


class _LocalFallback:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, output, text: str) -> None:
        del output
        self.spoken.append(text)


@pytest.mark.asyncio
async def test_missing_cloud_tts_credential_falls_back_to_local_lifecycle_speech(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TTS_GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(
        voice_runtime,
        "build_scripted_speech",
        lambda _config: (_ for _ in ()).throw(RuntimeError("tts credential missing")),
    )

    local = _LocalFallback()
    controller = voice_runtime.VoiceRuntimeController(
        JarvisConfig(ai_provider="openai", tts_provider="gemini"),
        SimpleNamespace(output=object()),  # type: ignore[arg-type]
        local_status_speech=local,
    )

    spoken = await controller._speak_lifecycle_message(
        object(),
        "Systems are ready, sir.",
        label="C2 test",
    )

    assert spoken is True
    assert local.spoken == ["Systems are ready, sir."]
