from __future__ import annotations

from types import SimpleNamespace

import pytest
from livekit.agents.types import APIConnectOptions

from jarvis.voice.scripted_speech import LiveKitScriptedSpeech


class FakeStream:
    def __init__(self) -> None:
        self._sent = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return SimpleNamespace(frame=object())


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def synthesize(self, text: str, **kwargs):
        self.calls.append((text, kwargs))
        return FakeStream()

    async def aclose(self) -> None:
        self.closed = True


class FakeOutput:
    def __init__(self) -> None:
        self._callbacks: dict[str, object] = {}
        self.frames: list[object] = []

    def on(self, event: str, callback) -> None:
        self._callbacks[event] = callback

    def off(self, event: str, callback) -> None:
        assert self._callbacks.get(event) is callback
        self._callbacks.pop(event, None)

    async def capture_frame(self, frame: object) -> None:
        self.frames.append(frame)

    def flush(self) -> None:
        callback = self._callbacks["playback_finished"]
        callback(object())


@pytest.mark.asyncio
async def test_scripted_speech_can_disable_nested_provider_retries() -> None:
    engine = FakeEngine()
    output = FakeOutput()
    speech = LiveKitScriptedSpeech(engine)  # type: ignore[arg-type]

    await speech.speak(
        output,  # type: ignore[arg-type]
        "Background work completed.",
        max_provider_retries=0,
    )

    assert len(engine.calls) == 1
    text, kwargs = engine.calls[0]
    assert text == "Background work completed."
    conn_options = kwargs["conn_options"]
    assert isinstance(conn_options, APIConnectOptions)
    assert conn_options.max_retry == 0
    assert len(output.frames) == 1


@pytest.mark.asyncio
async def test_normal_scripted_speech_keeps_livekit_default_retry_behavior() -> None:
    engine = FakeEngine()
    output = FakeOutput()
    speech = LiveKitScriptedSpeech(engine)  # type: ignore[arg-type]

    await speech.speak(
        output,  # type: ignore[arg-type]
        "Startup greeting.",
    )

    assert engine.calls == [("Startup greeting.", {})]
