from __future__ import annotations

import numpy as np

from jarvis.identity.lr_asd_turn_gate_benchmark import (
    SlidingObservation,
    _active_fraction,
    _phase_for_time,
    _slice_turn,
    _stable_transition_delay_ms,
)
from jarvis.identity.speaker_turn import SpeakerTurnAudio


def _observation(
    end: float,
    score: float | None,
    *,
    inference_ms: float = 50.0,
    phase: str = "G_OWNER_PLUS_PHONE",
) -> SlidingObservation:
    return SlidingObservation(
        window_end_monotonic=end,
        phase=phase,
        state="scored" if score is not None else "insufficient",
        trailing_score=score,
        mean_score=score,
        median_score=score,
        inference_ms=inference_ms if score is not None else None,
        visual_frames=25 if score is not None else 0,
        source_fps=25.0 if score is not None else None,
        reason_codes=(),
    )


def test_slice_turn_preserves_requested_timestamp_interval() -> None:
    samples = np.arange(20, dtype=np.int16)
    turn = SpeakerTurnAudio(
        samples=samples,
        sample_rate=10,
        start_monotonic=10.0,
        end_monotonic=12.0,
    )

    sliced = _slice_turn(turn, start_monotonic=10.5, end_monotonic=11.5)

    assert sliced is not None
    assert sliced.sample_rate == 10
    assert sliced.start_monotonic == 10.5
    assert sliced.end_monotonic == 11.5
    assert sliced.samples.tolist() == list(range(5, 15))


def test_slice_turn_returns_none_outside_source_interval() -> None:
    turn = SpeakerTurnAudio(
        samples=np.arange(20, dtype=np.int16),
        sample_rate=10,
        start_monotonic=10.0,
        end_monotonic=12.0,
    )

    assert _slice_turn(turn, start_monotonic=12.1, end_monotonic=13.0) is None


def test_phase_for_time_uses_transition_boundaries() -> None:
    boundaries = {"b1_end": 4.0, "g_end": 8.0, "b2_end": 12.0}

    assert _phase_for_time(3.99, **boundaries) == "B1_PHONE_ONLY"
    assert _phase_for_time(4.0, **boundaries) == "G_OWNER_PLUS_PHONE"
    assert _phase_for_time(8.0, **boundaries) == "B2_PHONE_ONLY"
    assert _phase_for_time(12.0, **boundaries) == "A_OWNER_ONLY"


def test_stable_transition_delay_includes_first_window_inference() -> None:
    observations = [
        _observation(10.10, 0.20),
        _observation(10.20, 0.80),
        _observation(10.40, 0.90),
    ]

    delay = _stable_transition_delay_ms(
        observations,
        boundary_monotonic=10.0,
        threshold=0.5,
        active=True,
        stable_windows=2,
    )

    assert delay is not None
    assert abs(delay - 250.0) < 1e-6


def test_stable_inactive_transition_ignores_insufficient_windows() -> None:
    observations = [
        _observation(20.10, None),
        _observation(20.20, 0.10, inference_ms=40.0),
        _observation(20.40, 0.20, inference_ms=40.0),
    ]

    delay = _stable_transition_delay_ms(
        observations,
        boundary_monotonic=20.0,
        threshold=0.5,
        active=False,
        stable_windows=2,
    )

    assert delay is not None
    assert abs(delay - 240.0) < 1e-6


def test_active_fraction_uses_only_scored_windows_in_phase() -> None:
    observations = [
        _observation(1.0, 0.9, phase="A_OWNER_ONLY"),
        _observation(1.2, 0.1, phase="A_OWNER_ONLY"),
        _observation(1.4, None, phase="A_OWNER_ONLY"),
        _observation(1.6, 0.9, phase="B1_PHONE_ONLY"),
    ]

    assert _active_fraction(
        observations,
        phase="A_OWNER_ONLY",
        threshold=0.5,
    ) == 0.5
