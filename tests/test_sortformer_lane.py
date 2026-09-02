from __future__ import annotations

import numpy as np

from jarvis.identity.sortformer_lane import LanePhase, analyze_owner_lane_sequence


def _phases() -> dict[str, LanePhase]:
    return {
        "A1_OWNER_ONLY": LanePhase("A1_OWNER_ONLY", 0.0, 2.0),
        "B1_PHONE_ONLY": LanePhase("B1_PHONE_ONLY", 2.0, 4.0),
        "G_OWNER_PLUS_PHONE": LanePhase("G_OWNER_PLUS_PHONE", 4.0, 6.0),
        "B2_PHONE_ONLY": LanePhase("B2_PHONE_ONLY", 6.0, 8.0),
        "A2_OWNER_ONLY": LanePhase("A2_OWNER_ONLY", 8.0, 10.0),
    }


def test_owner_and_phone_lanes_remain_stable_across_sequence() -> None:
    probabilities = np.full((100, 4), 0.02, dtype=np.float32)
    probabilities[0:20, 0] = 0.90
    probabilities[20:40, 1] = 0.92
    probabilities[40:60, 0] = 0.91
    probabilities[40:60, 1] = 0.86
    probabilities[60:80, 1] = 0.93
    probabilities[80:100, 0] = 0.89
    frame_centers = (np.arange(100, dtype=np.float64) + 0.5) * 0.1
    availability = frame_centers + 0.8

    result = analyze_owner_lane_sequence(
        probabilities,
        availability,
        seconds_per_frame=0.1,
        phases=_phases(),
        threshold=0.5,
        inactive_consecutive_frames=3,
    )

    assert result.owner_lane == 0
    assert result.phone_lane == 1
    assert result.owner_phone_lanes_distinct is True
    assert result.owner_lane_reacquired is True
    assert result.phone_lane_stable is True
    assert result.overlap_concurrent_fraction == 1.0
    assert result.functional_pass is True
    assert result.owner_first_onset_available_ms is not None
    assert result.owner_reacquire_available_ms is not None
    assert result.owner_overlap_offset_available_ms is not None


def test_functional_pass_fails_when_phone_reuses_owner_lane() -> None:
    probabilities = np.full((100, 4), 0.02, dtype=np.float32)
    probabilities[:, 0] = 0.90
    frame_centers = (np.arange(100, dtype=np.float64) + 0.5) * 0.1
    availability = frame_centers + 0.8

    result = analyze_owner_lane_sequence(
        probabilities,
        availability,
        seconds_per_frame=0.1,
        phases=_phases(),
    )

    assert result.owner_lane == result.phone_lane
    assert result.owner_phone_lanes_distinct is False
    assert result.functional_pass is False
