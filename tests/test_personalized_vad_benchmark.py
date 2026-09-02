from __future__ import annotations

import numpy as np

from jarvis.identity.personalized_vad_benchmark import (
    _active_fraction_after,
    _summarize_phase,
    _transition_ms,
)
from jarvis.identity.sortformer_lane import LanePhase


def test_personalized_vad_phase_summary_uses_phase_window() -> None:
    probabilities = np.asarray([0.1] * 100 + [0.9] * 100, dtype=np.float32)
    phase = LanePhase("OWNER", 1.0, 2.0)

    stats = _summarize_phase(
        probabilities,
        frame_seconds=0.01,
        phase=phase,
        threshold=0.5,
    )

    assert stats.frame_count == 100
    assert stats.active_fraction == 1.0
    assert stats.mean > 0.89


def test_transition_ms_finds_sustained_owner_onset() -> None:
    probabilities = np.asarray([0.1] * 50 + [0.8] * 50, dtype=np.float32)

    onset = _transition_ms(
        probabilities,
        frame_seconds=0.01,
        boundary_seconds=0.0,
        phase_end_seconds=1.0,
        threshold=0.5,
        consecutive_frames=3,
        above=True,
    )

    assert onset == 505.0


def test_transition_ms_finds_sustained_owner_offset() -> None:
    probabilities = np.asarray([0.9] * 20 + [0.1] * 80, dtype=np.float32)

    offset = _transition_ms(
        probabilities,
        frame_seconds=0.01,
        boundary_seconds=0.0,
        phase_end_seconds=1.0,
        threshold=0.5,
        consecutive_frames=8,
        above=False,
    )

    assert offset == 205.0


def test_active_fraction_after_ignores_transition_tail() -> None:
    probabilities = np.asarray([0.9] * 50 + [0.1] * 50, dtype=np.float32)
    phase = LanePhase("PHONE", 0.0, 1.0)

    fraction = _active_fraction_after(
        probabilities,
        frame_seconds=0.01,
        phase=phase,
        threshold=0.5,
        offset_seconds=0.5,
    )

    assert fraction == 0.0
