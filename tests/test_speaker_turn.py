from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture


def _frame(value: int, samples: int = 10) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


def test_turn_capture_keeps_bounded_preroll_and_user_speech() -> None:
    capture = InMemorySpeakerTurnCapture(
        pre_roll_seconds=0.02,
        max_turn_seconds=1.0,
    )
    for value in (1, 2, 3):
        capture.push_frame(
            _frame(value),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=10,
        )

    capture.start_turn()
    for value in (4, 5, 6):
        capture.push_frame(
            _frame(value),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=10,
        )

    turn = capture.finish_turn()

    assert turn is not None
    assert turn.sample_rate == 1_000
    assert turn.duration_seconds == pytest.approx(0.05)
    chunks = turn.samples.reshape(-1, 10)
    assert [int(chunk[0]) for chunk in chunks] == [2, 3, 4, 5, 6]


def test_turn_capture_timestamps_include_retained_preroll() -> None:
    capture = InMemorySpeakerTurnCapture(
        pre_roll_seconds=0.02,
        max_turn_seconds=1.0,
    )
    for index, value in enumerate((1, 2, 3)):
        capture.push_frame(
            _frame(value),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=10,
            observed_at_monotonic=10.0 + index * 0.01,
        )

    capture.start_turn()
    capture.push_frame(
        _frame(4),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=10,
        observed_at_monotonic=10.03,
    )

    turn = capture.finish_turn()

    assert turn is not None
    assert turn.start_monotonic == pytest.approx(10.01)
    assert turn.end_monotonic == pytest.approx(10.04)
    assert turn.samples.size == 30


def test_turn_capture_caps_audio_without_persisting_after_finish() -> None:
    capture = InMemorySpeakerTurnCapture(
        pre_roll_seconds=0.0,
        max_turn_seconds=0.025,
    )
    capture.start_turn()
    for value in (1, 2, 3, 4):
        capture.push_frame(
            _frame(value),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=10,
        )

    turn = capture.finish_turn()

    assert turn is not None
    assert turn.samples.size == 25
    assert capture.finish_turn() is None


def test_turn_capture_resets_if_sample_rate_changes() -> None:
    capture = InMemorySpeakerTurnCapture(pre_roll_seconds=0.01)
    capture.push_frame(
        _frame(1),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=10,
    )
    capture.push_frame(
        _frame(2),
        sample_rate=2_000,
        num_channels=1,
        samples_per_channel=10,
    )
    capture.start_turn()
    capture.push_frame(
        _frame(3),
        sample_rate=2_000,
        num_channels=1,
        samples_per_channel=10,
    )

    turn = capture.finish_turn()

    assert turn is not None
    assert turn.sample_rate == 2_000
    assert np.all(turn.samples[:10] == 2)
    assert np.all(turn.samples[10:] == 3)
