from __future__ import annotations

import numpy as np
from livekit import rtc

from jarvis.voice.observed_audio import ObservedSessionAudioInput


def _frame(value: int) -> rtc.AudioFrame:
    samples = 480
    return rtc.AudioFrame(
        data=np.full(samples, value, dtype=np.int16).tobytes(),
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=samples,
    )


def test_observer_sees_only_frames_accepted_by_session_queue() -> None:
    observed: list[int] = []

    def observer(frame: rtc.AudioFrame) -> None:
        observed.append(int(np.frombuffer(frame.data, dtype=np.int16)[0]))

    audio_input = ObservedSessionAudioInput(observer, capacity_frames=1)

    assert audio_input.push_frame(_frame(1)) is True
    assert audio_input.push_frame(_frame(2)) is False
    assert observed == [1]
