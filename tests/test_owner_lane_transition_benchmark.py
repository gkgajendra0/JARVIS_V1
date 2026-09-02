from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.owner_lane_transition_benchmark import (
    _acoustic_inactive_ms,
    _active_fraction_after,
)
from jarvis.identity.sortformer_lane import LanePhase


def test_acoustic_inactive_ms_finds_first_stable_below_threshold_run() -> None:
    probabilities = np.zeros((12, 2), dtype=np.float32)
    probabilities[:, 1] = np.asarray(
        [0.9, 0.9, 0.9, 0.9, 0.8, 0.7, 0.6, 0.4, 0.3, 0.2, 0.1, 0.1],
        dtype=np.float32,
    )

    value = _acoustic_inactive_ms(
        probabilities,
        lane=1,
        seconds_per_frame=0.08,
        boundary_seconds=0.40,
        threshold=0.5,
        consecutive_frames=3,
    )

    assert value == pytest.approx(200.0)


def test_acoustic_inactive_ms_returns_none_when_lane_never_settles() -> None:
    probabilities = np.zeros((8, 2), dtype=np.float32)
    probabilities[:, 1] = 0.8

    assert (
        _acoustic_inactive_ms(
            probabilities,
            lane=1,
            seconds_per_frame=0.08,
            boundary_seconds=0.16,
            threshold=0.5,
            consecutive_frames=3,
        )
        is None
    )


def test_active_fraction_after_ignores_early_transition_tail() -> None:
    probabilities = np.zeros((10, 2), dtype=np.float32)
    probabilities[:, 1] = np.asarray(
        [0.9, 0.9, 0.9, 0.9, 0.9, 0.8, 0.2, 0.2, 0.2, 0.2],
        dtype=np.float32,
    )
    phase = LanePhase("B2_PHONE_ONLY", 0.0, 0.8)

    whole = _active_fraction_after(
        probabilities,
        lane=1,
        seconds_per_frame=0.08,
        phase=phase,
        threshold=0.5,
        start_offset_seconds=0.0,
    )
    after_half = _active_fraction_after(
        probabilities,
        lane=1,
        seconds_per_frame=0.08,
        phase=phase,
        threshold=0.5,
        start_offset_seconds=0.48,
    )

    assert whole == pytest.approx(0.6)
    assert after_half == pytest.approx(0.0)
