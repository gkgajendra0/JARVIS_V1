from __future__ import annotations

from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState


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
