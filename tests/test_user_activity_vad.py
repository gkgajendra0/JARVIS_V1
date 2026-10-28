"""Exercise the installed SDK speech-duration filter with deterministic scores."""

import asyncio
from types import SimpleNamespace

import pytest
from livekit import rtc
from livekit.agents import vad

from jarvis.config import JarvisConfig
from jarvis.voice.livekit_session import create_voice_session


@pytest.mark.asyncio
@pytest.mark.parametrize("speech_windows,expected_starts", [(3, 0), (12, 1)])
async def test_short_false_burst_is_rejected_but_sustained_speech_is_detected(
    monkeypatch, speech_windows, expected_starts
):
    scores = iter([0.99] * speech_windows + [0.0] * 16)

    class Native:
        def predict(self, audio):
            return next(scores, 0.0)

        def reset(self):
            pass

    monkeypatch.setattr("livekit.agents.inference.vad._NativeVAD", Native)
    monkeypatch.setattr(
        "jarvis.voice.livekit_session._create_realtime_model", lambda _: object()
    )
    captured = {}

    def session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(on=lambda *_: None)

    monkeypatch.setattr("jarvis.voice.livekit_session.AgentSession", session)
    create_voice_session(JarvisConfig())
    stream = captured["vad"].stream()
    try:
        for _ in range(speech_windows + 16):
            stream.push_frame(rtc.AudioFrame.create(16000, 1, 512))
        stream.end_input()

        async def collect():
            return [event async for event in stream]

        events = await asyncio.wait_for(collect(), 3)
        starts = [e for e in events if e.type is vad.VADEventType.START_OF_SPEECH]
        assert len(starts) == expected_starts
        if starts:
            assert starts[0].frames  # the prefix/audio is retained for recognition
    finally:
        await stream.aclose()
