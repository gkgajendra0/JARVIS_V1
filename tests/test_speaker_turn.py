from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture


def _frame(value: int, samples: int = 10) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


def test_recent_capture_keeps_exact_bounded_window() -> None:
    capture = InMemorySpeakerTurnCapture(max_turn_seconds=0.025)
    for index, value in enumerate((1, 2, 3, 4)):
        capture.push_frame(
            _frame(value),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=10,
            observed_at_monotonic=10.0 + index * 0.01,
        )

    turn = capture.snapshot_recent_audio(clear=False)

    assert turn is not None
    assert turn.sample_rate == 1_000
    assert turn.samples.size == 25
    assert turn.duration_seconds == pytest.approx(0.025)
    np.testing.assert_array_equal(turn.samples[:5], np.full(5, 2, dtype=np.int16))
    np.testing.assert_array_equal(turn.samples[5:15], np.full(10, 3, dtype=np.int16))
    np.testing.assert_array_equal(turn.samples[15:], np.full(10, 4, dtype=np.int16))
    assert turn.start_monotonic == pytest.approx(10.015)
    assert turn.end_monotonic == pytest.approx(10.04)


def test_recent_capture_snapshot_clears_only_buffered_audio() -> None:
    capture = InMemorySpeakerTurnCapture(max_turn_seconds=1.0)
    capture.push_frame(
        _frame(1),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=10,
        observed_at_monotonic=20.0,
    )

    first = capture.snapshot_recent_audio()
    empty = capture.snapshot_recent_audio()
    capture.push_frame(
        _frame(2),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=10,
        observed_at_monotonic=20.01,
    )
    second = capture.snapshot_recent_audio()

    assert first is not None
    assert empty is None
    assert second is not None
    assert np.all(first.samples == 1)
    assert np.all(second.samples == 2)


def test_recent_capture_resets_if_sample_rate_changes() -> None:
    capture = InMemorySpeakerTurnCapture(max_turn_seconds=1.0)
    capture.push_frame(
        _frame(1),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=10,
        observed_at_monotonic=30.0,
    )
    capture.push_frame(
        _frame(2),
        sample_rate=2_000,
        num_channels=1,
        samples_per_channel=10,
        observed_at_monotonic=30.01,
    )

    turn = capture.snapshot_recent_audio()

    assert turn is not None
    assert turn.sample_rate == 2_000
    assert turn.samples.size == 10
    assert np.all(turn.samples == 2)


def test_recent_capture_rejects_non_mono_audio() -> None:
    capture = InMemorySpeakerTurnCapture()

    with pytest.raises(ValueError, match="requires mono PCM"):
        capture.push_frame(
            _frame(1),
            sample_rate=1_000,
            num_channels=2,
            samples_per_channel=10,
        )
