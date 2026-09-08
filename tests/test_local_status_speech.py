from __future__ import annotations

import wave
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from jarvis.voice.local_status_speech import WindowsLocalStatusSpeech


class FakeOutput:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = defaultdict(list)
        self.frames = []
        self.flushes = 0

    def on(self, event: str, callback):
        self.handlers[event].append(callback)
        return callback

    def off(self, event: str, callback) -> None:
        self.handlers[event].remove(callback)

    async def capture_frame(self, frame) -> None:
        self.frames.append(frame)

    def flush(self) -> None:
        self.flushes += 1
        for callback in tuple(self.handlers["playback_finished"]):
            callback(object())


@pytest.mark.asyncio
async def test_local_status_speech_streams_windows_pcm_through_jarvis_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speaker = WindowsLocalStatusSpeech()
    output = FakeOutput()
    observed_text: list[str] = []

    async def fake_synthesize(path: Path, text: str) -> None:
        observed_text.append(text)
        samples = np.full(24_000 // 5, 200, dtype=np.int16)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24_000)
            wav_file.writeframes(samples.tobytes())

    monkeypatch.setattr(speaker, "_synthesize_to_wave", fake_synthesize)

    await speaker.speak(output, "Gemini quota exhausted")  # type: ignore[arg-type]

    assert observed_text == ["Gemini quota exhausted"]
    assert output.flushes == 1
    assert output.frames
    assert all(frame.sample_rate == 24_000 for frame in output.frames)
    assert all(frame.num_channels == 1 for frame in output.frames)
    total_samples = sum(frame.samples_per_channel for frame in output.frames)
    assert total_samples == 24_000 // 5


@pytest.mark.asyncio
async def test_local_status_speech_rejects_empty_text() -> None:
    speaker = WindowsLocalStatusSpeech()
    with pytest.raises(ValueError, match="must not be empty"):
        await speaker.speak(FakeOutput(), "   ")  # type: ignore[arg-type]
