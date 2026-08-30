from __future__ import annotations

import pytest

from jarvis.authority import EvidenceVerdict
from jarvis.identity.passive_liveness import (
    PassiveLivenessObservation,
    PassiveLivenessState,
    PassiveLivenessThresholds,
    TemporalPassiveLiveness,
)


def _window() -> TemporalPassiveLiveness:
    return TemporalPassiveLiveness(
        session_id="wts:3",
        visual_track_id=7,
        pad_provider_id="minifasnet-v1se-v2-ensemble-v1",
    )


def _observation(index: int, probability: float) -> PassiveLivenessObservation:
    return PassiveLivenessObservation(
        session_id="wts:3",
        visual_track_id=7,
        provider_id="minifasnet-v1se-v2-ensemble-v1",
        observed_at_monotonic=10.0 + index * 0.10,
        real_probability=probability,
    )


def test_thresholds_preserve_conservative_gap() -> None:
    thresholds = PassiveLivenessThresholds()

    assert thresholds.window_size == 15
    assert thresholds.live_min == pytest.approx(0.95)
    assert thresholds.spoof_max == pytest.approx(0.50)


def test_window_is_insufficient_until_full() -> None:
    window = _window()

    for index in range(14):
        assessment = window.observe(_observation(index, 0.999))

    assert assessment.state is PassiveLivenessState.INSUFFICIENT
    assert assessment.sample_count == 14
    assert assessment.temporal_real_probability is None


def test_live_window_creates_passed_face_liveness_evidence() -> None:
    window = _window()

    for index in range(15):
        assessment = window.observe(_observation(index, 0.99))

    assert assessment.state is PassiveLivenessState.LIVE
    assert assessment.temporal_real_probability == pytest.approx(0.99)
    assert not assessment.requires_active_challenge

    evidence = window.to_identity_evidence(assessment)
    assert evidence.verdict is EvidenceVerdict.PASSED
    assert evidence.visual_track_id == 7
    assert evidence.session_id == "wts:3"
    assert evidence.expires_at_monotonic - evidence.observed_at_monotonic == pytest.approx(
        2.0
    )


def test_spoof_window_creates_failed_face_liveness_evidence() -> None:
    window = _window()

    for index in range(15):
        assessment = window.observe(_observation(index, 0.20))

    assert assessment.state is PassiveLivenessState.SPOOF
    assert not assessment.requires_active_challenge
    assert window.to_identity_evidence(assessment).verdict is EvidenceVerdict.FAILED


def test_uncertain_window_requires_active_challenge() -> None:
    window = _window()

    for index in range(15):
        assessment = window.observe(_observation(index, 0.75))

    assert assessment.state is PassiveLivenessState.UNCERTAIN
    assert assessment.requires_active_challenge
    assert window.to_identity_evidence(assessment).verdict is EvidenceVerdict.INSUFFICIENT


def test_long_gap_resets_temporal_window() -> None:
    window = _window()
    for index in range(10):
        window.observe(_observation(index, 0.99))

    after_gap = PassiveLivenessObservation(
        session_id="wts:3",
        visual_track_id=7,
        provider_id="minifasnet-v1se-v2-ensemble-v1",
        observed_at_monotonic=20.0,
        real_probability=0.99,
    )
    assessment = window.observe(after_gap)

    assert assessment.state is PassiveLivenessState.INSUFFICIENT
    assert assessment.sample_count == 1


def test_cross_track_observation_is_rejected() -> None:
    window = _window()
    observation = PassiveLivenessObservation(
        session_id="wts:3",
        visual_track_id=8,
        provider_id="minifasnet-v1se-v2-ensemble-v1",
        observed_at_monotonic=10.0,
        real_probability=0.99,
    )

    with pytest.raises(ValueError, match="visual track mismatch"):
        window.observe(observation)


def test_cross_session_observation_is_rejected() -> None:
    window = _window()
    observation = PassiveLivenessObservation(
        session_id="wts:4",
        visual_track_id=7,
        provider_id="minifasnet-v1se-v2-ensemble-v1",
        observed_at_monotonic=10.0,
        real_probability=0.99,
    )

    with pytest.raises(ValueError, match="session mismatch"):
        window.observe(observation)


def test_wrong_pad_provider_is_rejected() -> None:
    window = _window()
    observation = PassiveLivenessObservation(
        session_id="wts:3",
        visual_track_id=7,
        provider_id="other-pad-provider",
        observed_at_monotonic=10.0,
        real_probability=0.99,
    )

    with pytest.raises(ValueError, match="PAD provider mismatch"):
        window.observe(observation)
