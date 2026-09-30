from __future__ import annotations

from datetime import UTC, datetime
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
    now = datetime(2026, 8, 30, hour, tzinfo=UTC)

    greeting = select_startup_greeting(now, chooser=lambda options: options[0])

    assert greeting == expected


def test_startup_greeting_chooser_receives_multiple_variants() -> None:
    seen: list[str] = []

    def choose_last(options):
        seen.extend(options)
        return options[-1]

    greeting = select_startup_greeting(
        datetime(2026, 8, 30, 8, tzinfo=UTC),
        chooser=choose_last,
    )

    assert len(seen) >= 5
    assert greeting == seen[-1]

class FakeRealtimeLifecycleSpeech:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error

    async def speak(self, output, *, instructions: str, label: str) -> None:
        self.calls.append(
            {
                "output": output,
                "instructions": instructions,
                "label": label,
            }
        )
        if self.error is not None:
            raise self.error


@pytest.mark.asyncio
async def test_runtime_speaks_selected_startup_greeting_through_realtime_voice() -> None:
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        startup_greeting_factory=lambda: "Systems are ready, sir.",
    )
    realtime = FakeRealtimeLifecycleSpeech()
    runtime._speak_ephemeral_realtime_message = realtime.speak  # type: ignore[method-assign]

    await runtime._speak_startup_greeting()

    assert len(realtime.calls) == 1
    call = realtime.calls[0]
    assert call["output"] is audio.output
    assert call["label"] == "startup greeting"
    assert "Systems are ready, sir." in str(call["instructions"])
    assert "Vary the wording naturally" in str(call["instructions"])


@pytest.mark.asyncio
async def test_runtime_can_disable_startup_greeting() -> None:
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(startup_greeting_enabled=False),
        audio,  # type: ignore[arg-type]
        startup_greeting_factory=lambda: "This should not play.",
    )
    realtime = FakeRealtimeLifecycleSpeech()
    runtime._speak_ephemeral_realtime_message = realtime.speak  # type: ignore[method-assign]

    await runtime._speak_startup_greeting()

    assert realtime.calls == []


@pytest.mark.asyncio
async def test_startup_realtime_voice_failure_does_not_use_local_fallback() -> None:
    audio = SimpleNamespace(output=object())
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        startup_greeting_factory=lambda: "Good morning, sir.",
    )
    realtime = FakeRealtimeLifecycleSpeech(error=RuntimeError("realtime unavailable"))
    runtime._speak_ephemeral_realtime_message = realtime.speak  # type: ignore[method-assign]

    await runtime._speak_startup_greeting()

    assert len(realtime.calls) == 1
