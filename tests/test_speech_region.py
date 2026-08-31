from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.identity.speech_region import _candidate_from_end_event


def test_end_event_trims_endpointing_silence_and_preserves_monotonic_time() -> None:
    sample_rate = 1_000
    turn = SpeakerTurnAudio(
        samples=np.arange(5_000, dtype=np.int16),
        sample_rate=sample_rate,
        start_monotonic=100.0,
        end_monotonic=105.0,
    )
    event = SimpleNamespace(
        timestamp=3.0,
        silence_duration=0.2,
        frames=(SimpleNamespace(samples_per_channel=2_000),),
    )

    candidate = _candidate_from_end_event(turn, event)

    assert candidate is not None
    assert candidate.duration_seconds == pytest.approx(1.8)
    assert candidate.start_monotonic == pytest.approx(101.0)
    assert candidate.end_monotonic == pytest.approx(102.8)
    np.testing.assert_array_equal(candidate.samples, turn.samples[1_000:2_800])


def test_end_event_never_extends_speech_past_captured_turn() -> None:
    sample_rate = 1_000
    turn = SpeakerTurnAudio(
        samples=np.ones(1_500, dtype=np.int16),
        sample_rate=sample_rate,
        start_monotonic=10.0,
        end_monotonic=11.5,
    )
    event = SimpleNamespace(
        timestamp=1.8,
        silence_duration=0.2,
        frames=(SimpleNamespace(samples_per_channel=1_000),),
    )

    candidate = _candidate_from_end_event(turn, event)

    assert candidate is not None
    assert candidate.end_monotonic == pytest.approx(11.5)
    assert candidate.samples.size == 700
