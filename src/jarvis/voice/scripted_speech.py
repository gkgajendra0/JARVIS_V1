"""Provider-adapted scripted speech for deterministic JARVIS system prompts."""

from __future__ import annotations

import asyncio
from typing import Protocol

from livekit.agents import tts
from livekit.plugins import google, openai

from jarvis.config import JarvisConfig
from jarvis.voice.audio import LocalAudioOutput


class ScriptedSpeech(Protocol):
    """Speak deterministic text without relying on realtime-model generation."""

    async def speak(self, output: LocalAudioOutput, text: str) -> None: ...

    async def aclose(self) -> None: ...


class LiveKitScriptedSpeech:
    """Synthesize a fixed script and play it through the existing local output."""

    def __init__(
        self, engine: tts.TTS, *, playback_timeout_seconds: float = 20.0
    ) -> None:
        if playback_timeout_seconds <= 0:
            raise ValueError("playback timeout must be positive")
        self._engine = engine
        self._playback_timeout_seconds = playback_timeout_seconds

    async def speak(self, output: LocalAudioOutput, text: str) -> None:
        script = text.strip()
        if not script:
            raise ValueError("scripted speech text must not be empty")

        playback_finished = asyncio.get_running_loop().create_future()

        def on_playback_finished(event: object) -> None:
            del event
            if not playback_finished.done():
                playback_finished.set_result(None)

        output.on("playback_finished", on_playback_finished)
        try:
            async with self._engine.synthesize(script) as stream:
                async for event in stream:
                    await output.capture_frame(event.frame)
            output.flush()
            await asyncio.wait_for(
                playback_finished,
                timeout=self._playback_timeout_seconds,
            )
        finally:
            output.off("playback_finished", on_playback_finished)

    async def aclose(self) -> None:
        await self._engine.aclose()


def build_scripted_speech(config: JarvisConfig) -> LiveKitScriptedSpeech:
    """Select a scripted TTS adapter without coupling supervisor policy to a provider."""
    instructions = (
        "Speak like JARVIS: calm, concise, professional, and authoritative. "
        "Do not add, remove, or paraphrase words from the supplied script."
    )
    if config.realtime_provider == "gemini":
        engine = google.beta.GeminiTTS(
            model="gemini-3.1-flash-tts-preview",
            voice_name=config.gemini_realtime_voice,
            instructions=instructions,
        )
    else:
        engine = openai.TTS(
            model="gpt-4o-mini-tts",
            voice=config.realtime_voice,
            instructions=instructions,
        )
    return LiveKitScriptedSpeech(engine)
