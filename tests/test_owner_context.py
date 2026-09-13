from __future__ import annotations

from jarvis.identity.owner_context import OwnerContextObserver, OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerIdentityThresholds,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import (
    PassiveLivenessState,
    PassiveLivenessThresholds,
)


def _assessment(
    state: OwnerLivenessBindingState,
    *,
    observed_at: float = 10.0,
) -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id="wts:1",
        visual_track_id=7,
        state=state,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=observed_at,
        reason_codes=("test",),
    )


def test_owner_context_requires_fresh_live_owner_candidate() -> None:
    context = OwnerContextState()
    context.publish(_assessment(OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE))

    assert context.has_fresh_live_owner_candidate(now_monotonic=11.0)
    assert not context.has_fresh_live_owner_candidate(now_monotonic=12.01)


def test_owner_context_rejects_non_live_states_and_invalidation() -> None:
    context = OwnerContextState()
    context.publish(_assessment(OwnerLivenessBindingState.AMBIGUOUS_SUBJECT))
    assert not context.has_fresh_live_owner_candidate(now_monotonic=10.1)

    context.publish(_assessment(OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE))
    context.invalidate("session_locked")

    snapshot = context.snapshot()
    assert snapshot.assessment is None
    assert snapshot.invalidation_reason == "session_locked"
    assert not context.has_fresh_live_owner_candidate(now_monotonic=10.1)


def test_owner_context_accepts_explicit_tracking_only_temporal_windows() -> None:
    identity_thresholds = OwnerIdentityThresholds(window_size=5)
    liveness_thresholds = PassiveLivenessThresholds(window_size=5)

    observer = OwnerContextObserver(
        owner_template=object(),  # type: ignore[arg-type]
        face_detector=object(),
        face_recognizer=object(),
        pad_provider=object(),  # type: ignore[arg-type]
        session_provider=object(),  # type: ignore[arg-type]
        identity_thresholds=identity_thresholds,
        liveness_thresholds=liveness_thresholds,
    )

    assert observer.identity_thresholds is identity_thresholds
    assert observer.liveness_thresholds is liveness_thresholds
    assert OwnerIdentityThresholds().window_size == 15
    assert PassiveLivenessThresholds().window_size == 15
