from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.identity.speech_region import (
    _candidate_from_end_event,
    _candidates_from_probability_observations,
    _consolidate_candidates,
    _ProbabilityObservation,
    _select_latest_candidate,
)


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


def test_probability_fallback_builds_one_bounded_speech_region() -> None:
    sample_rate = 1_000
    turn = SpeakerTurnAudio(
        samples=np.arange(3_000, dtype=np.int16),
        sample_rate=sample_rate,
        start_monotonic=50.0,
        end_monotonic=53.0,
    )
    observations = [
        _ProbabilityObservation(timestamp=0.32, probability=0.04),
        _ProbabilityObservation(timestamp=0.64, probability=0.81),
        _ProbabilityObservation(timestamp=0.672, probability=0.87),
        _ProbabilityObservation(timestamp=0.704, probability=0.12),
        _ProbabilityObservation(timestamp=0.736, probability=0.76),
        _ProbabilityObservation(timestamp=0.768, probability=0.79),
        _ProbabilityObservation(timestamp=1.20, probability=0.03),
    ]

    candidates = _candidates_from_probability_observations(
        turn,
        observations,
        activation_threshold=0.5,
        min_speech_duration=0.08,
        min_silence_duration=0.18,
        prefix_padding_duration=0.12,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.start_monotonic == pytest.approx(50.488)
    assert candidate.end_monotonic == pytest.approx(50.768)
    assert candidate.duration_seconds == pytest.approx(0.28)


def test_probability_fallback_rejects_subthreshold_observations() -> None:
    turn = SpeakerTurnAudio(
        samples=np.ones(2_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=10.0,
        end_monotonic=12.0,
    )
    observations = [
        _ProbabilityObservation(timestamp=0.32, probability=0.20),
        _ProbabilityObservation(timestamp=0.64, probability=0.49),
        _ProbabilityObservation(timestamp=0.96, probability=0.30),
    ]

    candidates = _candidates_from_probability_observations(
        turn,
        observations,
        activation_threshold=0.5,
        min_speech_duration=0.08,
        min_silence_duration=0.18,
        prefix_padding_duration=0.12,
    )

    assert candidates == []


def test_consolidation_merges_fragmented_natural_utterance_with_real_gaps() -> None:
    turn = SpeakerTurnAudio(
        samples=np.arange(6_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=100.0,
        end_monotonic=106.0,
    )
    candidates = [
        SpeakerTurnAudio(
            samples=np.ones(500, dtype=np.int16),
            sample_rate=1_000,
            start_monotonic=101.0,
            end_monotonic=101.5,
        ),
        SpeakerTurnAudio(
            samples=np.ones(650, dtype=np.int16),
            sample_rate=1_000,
            start_monotonic=101.9,
            end_monotonic=102.55,
        ),
        SpeakerTurnAudio(
            samples=np.ones(900, dtype=np.int16),
            sample_rate=1_000,
            start_monotonic=103.1,
            end_monotonic=104.0,
        ),
    ]

    consolidated = _consolidate_candidates(
        turn,
        candidates,
        max_gap_seconds=0.8,
    )

    assert len(consolidated) == 1
    merged = consolidated[0]
    assert merged.start_monotonic == pytest.approx(101.0)
    assert merged.end_monotonic == pytest.approx(104.0)
    assert merged.duration_seconds == pytest.approx(3.0)
    np.testing.assert_array_equal(merged.samples, turn.samples[1_000:4_000])


def test_consolidation_does_not_bind_old_unrelated_speech_to_current_utterance() -> (
    None
):
    turn = SpeakerTurnAudio(
        samples=np.ones(8_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=20.0,
        end_monotonic=28.0,
    )
    old = SpeakerTurnAudio(
        samples=np.ones(2_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=20.5,
        end_monotonic=22.5,
    )
    current = SpeakerTurnAudio(
        samples=np.ones(2_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=24.0,
        end_monotonic=26.0,
    )

    consolidated = _consolidate_candidates(
        turn,
        [old, current],
        max_gap_seconds=0.8,
    )

    assert len(consolidated) == 2
    first, second = consolidated
    assert first.start_monotonic == pytest.approx(20.5)
    assert first.end_monotonic == pytest.approx(22.5)
    assert second.start_monotonic == pytest.approx(24.0)
    assert second.end_monotonic == pytest.approx(26.0)
    assert _select_latest_candidate(consolidated) is second


def test_latest_candidate_wins_over_older_longer_region() -> None:
    older = SpeakerTurnAudio(
        samples=np.ones(2_000, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=10.0,
        end_monotonic=12.0,
    )
    latest = SpeakerTurnAudio(
        samples=np.ones(500, dtype=np.int16),
        sample_rate=1_000,
        start_monotonic=13.0,
        end_monotonic=13.5,
    )

    selected = _select_latest_candidate([older, latest])

    assert selected is latest
