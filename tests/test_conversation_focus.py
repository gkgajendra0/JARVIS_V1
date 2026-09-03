from __future__ import annotations

import numpy as np
from livekit import rtc

from jarvis.voice.conversation_focus import process_canonical_pcm


class _IdentityProcessor:
    def __init__(self) -> None:
        self.closed = False
        self.frames = 0

    def _process(self, frame: rtc.AudioFrame) -> rtc.AudioFrame:
        self.frames += 1
        return frame

    def _close(self) -> None:
        self.closed = True


def test_conversation_focus_preserves_canonical_shape_and_closes() -> None:
    processor = _IdentityProcessor()
    samples = np.arange(1_001, dtype=np.int16)

    run = process_canonical_pcm(
        samples,
        sample_rate=48_000,
        processor=processor,
    )

    assert np.array_equal(run.samples, samples)
    assert processor.frames == 3
    assert processor.closed is True
    assert run.audio_seconds == samples.size / 48_000
    assert run.processing_seconds >= 0.0
    assert run.realtime_factor >= 0.0
    assert len(run.frame_latencies_ms) == 3


def test_conversation_focus_rejects_invalid_pcm() -> None:
    processor = _IdentityProcessor()
    try:
        process_canonical_pcm(
            np.asarray([], dtype=np.int16),
            sample_rate=48_000,
            processor=processor,
        )
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("empty conversation-focus PCM should fail")
