from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.overlap import OverlapState, interpret_sortformer_probabilities


def test_empty_probabilities_are_insufficient() -> None:
    result = interpret_sortformer_probabilities(np.empty((0, 4), dtype=np.float32))

    assert result.state is OverlapState.INSUFFICIENT
    assert result.reason_codes == ("no_diarization_frames",)


def test_stable_one_speaker_is_single_speaker() -> None:
    probabilities = np.asarray(
        [
            [0.92, 0.03, 0.02, 0.01],
            [0.94, 0.02, 0.02, 0.01],
            [0.91, 0.04, 0.02, 0.01],
            [0.95, 0.02, 0.01, 0.01],
            [0.90, 0.05, 0.02, 0.01],
        ],
        dtype=np.float32,
    )

    result = interpret_sortformer_probabilities(probabilities)

    assert result.state is OverlapState.SINGLE_SPEAKER
    assert result.overlap_frames == 0
    assert result.stable_speaker_runs == ((0, 5),)


def test_concurrent_speakers_are_overlap() -> None:
    probabilities = np.asarray(
        [
            [0.91, 0.05, 0.01, 0.01],
            [0.93, 0.78, 0.01, 0.01],
            [0.92, 0.81, 0.01, 0.01],
            [0.90, 0.79, 0.01, 0.01],
            [0.88, 0.06, 0.01, 0.01],
        ],
        dtype=np.float32,
    )

    result = interpret_sortformer_probabilities(probabilities)

    assert result.state is OverlapState.OVERLAP_DETECTED
    assert result.overlap_frames == 3
    assert result.longest_overlap_run == 3
    assert result.active_speaker_peak == 2


def test_stable_sequential_speakers_are_speaker_change() -> None:
    probabilities = np.asarray(
        [
            [0.91, 0.04, 0.01, 0.01],
            [0.93, 0.03, 0.01, 0.01],
            [0.92, 0.04, 0.01, 0.01],
            [0.03, 0.93, 0.01, 0.01],
            [0.04, 0.91, 0.01, 0.01],
            [0.03, 0.94, 0.01, 0.01],
        ],
        dtype=np.float32,
    )

    result = interpret_sortformer_probabilities(probabilities)

    assert result.state is OverlapState.SPEAKER_CHANGE
    assert result.stable_speaker_runs == ((0, 3), (1, 3))


def test_unstable_activity_is_ambiguous() -> None:
    probabilities = np.asarray(
        [
            [0.91, 0.02, 0.01, 0.01],
            [0.03, 0.92, 0.01, 0.01],
            [0.90, 0.03, 0.01, 0.01],
            [0.04, 0.91, 0.01, 0.01],
        ],
        dtype=np.float32,
    )

    result = interpret_sortformer_probabilities(probabilities)

    assert result.state is OverlapState.AMBIGUOUS
    assert result.reason_codes == ("activity_without_stable_single_speaker_run",)


def test_invalid_probability_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="shape"):
        interpret_sortformer_probabilities(np.ones((5,), dtype=np.float32))


def test_nonfinite_probabilities_are_rejected() -> None:
    probabilities = np.ones((4, 4), dtype=np.float32)
    probabilities[2, 1] = np.nan

    with pytest.raises(ValueError, match="non-finite"):
        interpret_sortformer_probabilities(probabilities)
