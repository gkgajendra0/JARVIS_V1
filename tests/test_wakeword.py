from __future__ import annotations

import asyncio

import numpy as np
import pytest
from livekit import rtc

from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor


class FakePredictor:
    def __init__(self, score: float) -> None:
        self.score = score
        self.windows: list[np.ndarray] = []

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]:
        self.windows.append(audio_chunk)
        return {"jarvis": self.score}


def frame(samples: int = 1_280) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=np.ones(samples, dtype=np.int16).tobytes(),
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=samples,
    )


@pytest.mark.asyncio
async def test_detector_scores_two_second_windows_and_disables_after_wake() -> None:
    predictor = FakePredictor(0.9)
    detector = LiveKitWakeDetector(
        predictor,
        threshold=0.68,
        debounce_seconds=2,
    )
    detector.enable()

    for _ in range(25):
        detector.feed(frame())

    detection = await asyncio.wait_for(detector.wait_for_detection(), timeout=1)

    assert detection.name == "jarvis"
    assert detection.confidence == 0.9
    assert predictor.windows[0].shape == (32_000,)
    assert detector.enabled is False
    await detector.aclose()


@pytest.mark.asyncio
async def test_detector_ignores_audio_while_disabled() -> None:
    predictor = FakePredictor(0.9)
    detector = LiveKitWakeDetector(
        predictor,
        threshold=0.68,
        debounce_seconds=2,
    )

    for _ in range(30):
        detector.feed(frame())
    await asyncio.sleep(0)

    assert predictor.windows == []
    await detector.aclose()


def test_missing_wake_model_fails_truthfully(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Wake-word model not found"):
        load_livekit_predictor(tmp_path / "missing.onnx")
