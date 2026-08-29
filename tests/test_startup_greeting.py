from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice.runtime import VoiceRuntimeController
from jarvis.voice.startup_greeting import select_startup_greeting


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (8, "Good morning, sir. JARVIS is online."),
        (13, "Good afternoon, sir. JARVIS is online."),
        (19, "Good evening, sir. JARVIS is online."),
        (1, "JARVIS online, sir. Systems are ready."),
        (23, "JARVIS online, sir. Systems are ready."),
    ],
)
def test_startup_greeting_uses_time_appropriate_pool(hour: int, expected: str) -> None:
    now = datetime(2026, 8, 30, hour, tzinfo=timezone.utc)

    greeting = select_startup_greeting(now, chooser=lambda options: options[0])

    assert greeting == expected


def test_startup_greeting_chooser_receives_multiple_variants() -> None:
    seen: list[str] = []

    def choose_last(options):
        seen.extend(options)
        return options[-1]

    greeting = select_startup_greeting(
        datetime(2026, 8, 30, 8, tzinfo=timezone.utc),
        chooser=choose_last,
    )

    assert len(seen) >= 5
    assert greeting == seen[-1]


class FakeScriptedSpeech:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.spoken: list[str] = []
        self.error = error

    async def speak(self, output, text: str) -> None:
        del output
        self.spoken.append(text)
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_speaks_selected_startup_greeting() -> None:
    speech = FakeScriptedSpeech()
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=speech,
        startup_greeting_factory=lambda: "Systems are ready, sir.",
    )

    await runtime._speak_startup_greeting()

    assert speech.spoken == ["Systems are ready, sir."]


@pytest.mark.asyncio
async def test_runtime_can_disable_startup_greeting() -> None:
    speech = FakeScriptedSpeech()
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(startup_greeting_enabled=False),
        audio,  # type: ignore[arg-type]
        scripted_speech=speech,
        startup_greeting_factory=lambda: "This should not play.",
    )

    await runtime._speak_startup_greeting()

    assert speech.spoken == []


@pytest.mark.asyncio
async def test_startup_greeting_failure_does_not_block_runtime_startup() -> None:
    speech = FakeScriptedSpeech(error=RuntimeError("tts unavailable"))
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=speech,
        startup_greeting_factory=lambda: "Good morning, sir.",
    )

    await runtime._speak_startup_greeting()

    assert speech.spoken == ["Good morning, sir."]
