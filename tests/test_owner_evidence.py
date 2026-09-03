from __future__ import annotations

import numpy as np
import pytest

from jarvis.authority import EvidenceVerdict
from jarvis.identity.owner_evidence import (
    OwnerIdentityObservation,
    OwnerIdentityState,
    OwnerIdentityThresholds,
    OwnerLivenessBindingState,
    TemporalOwnerIdentity,
    bind_owner_liveness,
    max_prototype_cosine,
)
from jarvis.identity.passive_liveness import (
    PassiveLivenessAssessment,
    PassiveLivenessState,
)

_FACE_PROVIDER = "opencv-sface-prototype-set-v1"


def _window() -> TemporalOwnerIdentity:
    return TemporalOwnerIdentity(
        session_id="wts:3",
        visual_track_id=7,
        face_provider_id=_FACE_PROVIDER,
    )


def _observation(index: int, similarity: float) -> OwnerIdentityObservation:
    return OwnerIdentityObservation(
        session_id="wts:3",
        visual_track_id=7,
        provider_id=_FACE_PROVIDER,
        observed_at_monotonic=10.0 + index * 0.10,
        max_prototype_cosine=similarity,
    )


def _liveness(
    state: PassiveLivenessState,
    *,
    observed_at: float = 11.4,
) -> PassiveLivenessAssessment:
    probability = {
        PassiveLivenessState.LIVE: 0.99,
        PassiveLivenessState.UNCERTAIN: 0.75,
        PassiveLivenessState.SPOOF: 0.10,
        PassiveLivenessState.INSUFFICIENT: None,
    }[state]
    return PassiveLivenessAssessment(
        session_id="wts:3",
        visual_track_id=7,
        provider_id="jarvis-minifas-temporal-passive-liveness-v1",
        observed_at_monotonic=observed_at,
        state=state,
        sample_count=15 if probability is not None else 4,
        window_size=15,
        temporal_real_probability=probability,
        reason_codes=("test",),
    )


def test_thresholds_are_deliberately_wide() -> None:
    thresholds = OwnerIdentityThresholds()

    assert thresholds.window_size == 15
    assert thresholds.owner_candidate_min == pytest.approx(0.65)
    assert thresholds.unknown_max == pytest.approx(0.35)


def test_owner_candidate_requires_full_temporal_window() -> None:
    window = _window()

    for index in range(14):
        assessment = window.observe(_observation(index, 0.82))

    assert assessment.state is OwnerIdentityState.INSUFFICIENT
    assessment = window.observe(_observation(14, 0.82))
    assert assessment.state is OwnerIdentityState.OWNER_CANDIDATE
    assert assessment.temporal_similarity == pytest.approx(0.82)


def test_unknown_and_ambiguous_bands_fail_safe() -> None:
    unknown = _window()
    ambiguous = _window()

    for index in range(15):
        unknown_assessment = unknown.observe(_observation(index, 0.20))
        ambiguous_assessment = ambiguous.observe(_observation(index, 0.50))

    assert unknown_assessment.state is OwnerIdentityState.UNKNOWN
    assert ambiguous_assessment.state is OwnerIdentityState.AMBIGUOUS
    assert (
        unknown.to_identity_evidence(unknown_assessment).verdict
        is EvidenceVerdict.NO_MATCH
    )
    assert (
        ambiguous.to_identity_evidence(ambiguous_assessment).verdict
        is EvidenceVerdict.INSUFFICIENT
    )


def test_owner_candidate_evidence_is_typed_and_requires_live_binding_for_t2() -> None:
    window = _window()
    for index in range(15):
        assessment = window.observe(_observation(index, 0.80))

    evidence = window.to_identity_evidence(assessment)

    assert evidence.verdict is EvidenceVerdict.MATCH
    assert evidence.visual_track_id == 7
    assert evidence.session_id == "wts:3"
    assert (
        "temporal_owner_candidate_t2_eligible_with_live_binding"
        in evidence.reason_codes
    )


def test_long_gap_resets_owner_temporal_window() -> None:
    window = _window()
    for index in range(10):
        window.observe(_observation(index, 0.80))

    assessment = window.observe(
        OwnerIdentityObservation(
            session_id="wts:3",
            visual_track_id=7,
            provider_id=_FACE_PROVIDER,
            observed_at_monotonic=20.0,
            max_prototype_cosine=0.80,
        )
    )

    assert assessment.state is OwnerIdentityState.INSUFFICIENT
    assert assessment.sample_count == 1


def test_explicit_clear_discards_owner_temporal_window() -> None:
    window = _window()
    for index in range(15):
        assessment = window.observe(_observation(index, 0.82))

    assert assessment.state is OwnerIdentityState.OWNER_CANDIDATE

    window.clear()

    cleared = window.assessment
    assert cleared.state is OwnerIdentityState.INSUFFICIENT
    assert cleared.sample_count == 0
    assert cleared.temporal_similarity is None


def test_owner_observation_binding_mismatch_is_rejected() -> None:
    window = _window()

    with pytest.raises(ValueError, match="session mismatch"):
        window.observe(
            OwnerIdentityObservation(
                session_id="wts:4",
                visual_track_id=7,
                provider_id=_FACE_PROVIDER,
                observed_at_monotonic=10.0,
                max_prototype_cosine=0.80,
            )
        )

    with pytest.raises(ValueError, match="visual track mismatch"):
        window.observe(
            OwnerIdentityObservation(
                session_id="wts:3",
                visual_track_id=8,
                provider_id=_FACE_PROVIDER,
                observed_at_monotonic=10.0,
                max_prototype_cosine=0.80,
            )
        )


def test_max_prototype_cosine_uses_best_normalized_prototype() -> None:
    prototypes = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    feature = np.asarray([0.9, 0.1, 0.0], dtype=np.float32)

    score = max_prototype_cosine(prototypes, feature)

    assert score == pytest.approx(0.9938837, rel=1e-5)


def test_live_owner_candidate_binding_is_bounded_t2_eligible() -> None:
    window = _window()
    for index in range(15):
        identity = window.observe(_observation(index, 0.82))

    combined = bind_owner_liveness(identity, _liveness(PassiveLivenessState.LIVE))

    assert combined.state is OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE
    assert combined.face_evidence_grants_t2
    assert not combined.requires_active_challenge


def test_uncertain_liveness_only_challenges_owner_candidate() -> None:
    owner_window = _window()
    ambiguous_window = _window()
    for index in range(15):
        owner = owner_window.observe(_observation(index, 0.82))
        ambiguous = ambiguous_window.observe(_observation(index, 0.50))

    owner_combined = bind_owner_liveness(
        owner,
        _liveness(PassiveLivenessState.UNCERTAIN),
    )
    ambiguous_combined = bind_owner_liveness(
        ambiguous,
        _liveness(PassiveLivenessState.UNCERTAIN),
    )

    assert owner_combined.state is OwnerLivenessBindingState.ACTIVE_CHALLENGE_ELIGIBLE
    assert owner_combined.requires_active_challenge
    assert ambiguous_combined.state is OwnerLivenessBindingState.AMBIGUOUS_SUBJECT
    assert not ambiguous_combined.requires_active_challenge


def test_spoofed_owner_presentation_fails_closed() -> None:
    window = _window()
    for index in range(15):
        identity = window.observe(_observation(index, 0.82))

    combined = bind_owner_liveness(identity, _liveness(PassiveLivenessState.SPOOF))

    assert combined.state is OwnerLivenessBindingState.SPOOFED_OWNER_PRESENTATION
    assert not combined.face_evidence_grants_t2
    assert not combined.requires_active_challenge


def test_cross_track_or_stale_binding_is_rejected_or_insufficient() -> None:
    window = _window()
    for index in range(15):
        identity = window.observe(_observation(index, 0.82))

    wrong_track = _liveness(PassiveLivenessState.LIVE)
    wrong_track = PassiveLivenessAssessment(
        session_id=wrong_track.session_id,
        visual_track_id=8,
        provider_id=wrong_track.provider_id,
        observed_at_monotonic=wrong_track.observed_at_monotonic,
        state=wrong_track.state,
        sample_count=wrong_track.sample_count,
        window_size=wrong_track.window_size,
        temporal_real_probability=wrong_track.temporal_real_probability,
        reason_codes=wrong_track.reason_codes,
    )
    with pytest.raises(ValueError, match="visual track mismatch"):
        bind_owner_liveness(identity, wrong_track)

    stale = bind_owner_liveness(
        identity,
        _liveness(PassiveLivenessState.LIVE, observed_at=20.0),
    )
    assert stale.state is OwnerLivenessBindingState.INSUFFICIENT
    assert not stale.face_evidence_grants_t2
