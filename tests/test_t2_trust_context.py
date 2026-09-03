from __future__ import annotations

from dataclasses import replace

from jarvis.authority import (
    ApprovalRequirement,
    AuthoritySession,
    RiskClass,
    TrustTier,
    WindowsSessionUnavailable,
)
from jarvis.authority.policy import hard_floor_for
from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState
from jarvis.identity.trust_context import OwnerTrustContextProvider


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeWindowsSessionProvider:
    def __init__(self, session: AuthoritySession) -> None:
        self.session = session

    def current_session(self) -> AuthoritySession:
        return self.session


class UnavailableWindowsSessionProvider:
    def current_session(self) -> AuthoritySession:
        raise WindowsSessionUnavailable("test unavailable")


def _session(*, active_unlocked: bool = True) -> AuthoritySession:
    return AuthoritySession(
        session_id="wts:3",
        windows_session_id=3,
        windows_user_sid_hash=None,
        active_unlocked=active_unlocked,
        generation=0,
        created_at_monotonic=100.0,
    )


def _live_owner(
    *,
    session_id: str = "wts:3",
    observed_at: float = 100.0,
) -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id=session_id,
        visual_track_id=7,
        state=OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=observed_at,
        reason_codes=("live_owner_candidate_t2_eligible",),
    )


def _provider(
    state: OwnerContextState,
    clock: FakeClock,
    windows: object,
) -> OwnerTrustContextProvider:
    return OwnerTrustContextProvider(
        state,
        windows_session_provider=windows,  # type: ignore[arg-type]
        clock=clock,
    )


def test_fresh_live_owner_in_unlocked_matching_session_grants_t2() -> None:
    clock = FakeClock(100.5)
    state = OwnerContextState()
    assessment = _live_owner()
    state.publish(assessment)

    snapshot = _provider(
        state,
        clock,
        FakeWindowsSessionProvider(_session()),
    ).snapshot()

    assert assessment.face_evidence_grants_t2 is True
    assert snapshot.t2_active is True
    assert snapshot.context.trust_tier is TrustTier.CORROBORATED_OWNER
    assert snapshot.context.windows_session_valid is True
    assert snapshot.context.actor_unambiguous is False
    assert snapshot.visual_track_id == 7


def test_stale_owner_evidence_falls_back_to_unverified() -> None:
    clock = FakeClock(103.0)
    state = OwnerContextState()
    state.publish(_live_owner())

    snapshot = _provider(
        state,
        clock,
        FakeWindowsSessionProvider(_session()),
    ).snapshot()

    assert snapshot.t2_active is False
    assert snapshot.context.trust_tier is TrustTier.UNVERIFIED
    assert snapshot.reason_codes == ("t2_live_owner_evidence_stale_or_insufficient",)


def test_windows_session_mismatch_fails_closed() -> None:
    clock = FakeClock(100.5)
    state = OwnerContextState()
    state.publish(_live_owner(session_id="wts:9"))

    snapshot = _provider(
        state,
        clock,
        FakeWindowsSessionProvider(_session()),
    ).snapshot()

    assert snapshot.t2_active is False
    assert snapshot.context.trust_tier is TrustTier.UNVERIFIED
    assert snapshot.reason_codes == ("t2_owner_windows_session_mismatch",)


def test_locked_windows_session_invalidates_t2() -> None:
    clock = FakeClock(100.5)
    state = OwnerContextState()
    state.publish(_live_owner())

    snapshot = _provider(
        state,
        clock,
        FakeWindowsSessionProvider(_session(active_unlocked=False)),
    ).snapshot()

    assert snapshot.t2_active is False
    assert snapshot.context.trust_tier is TrustTier.UNVERIFIED
    assert snapshot.context.windows_session_valid is False
    assert snapshot.reason_codes == ("t2_windows_session_locked",)


def test_unavailable_windows_session_fails_closed() -> None:
    clock = FakeClock(100.5)
    state = OwnerContextState()
    state.publish(_live_owner())

    snapshot = _provider(
        state,
        clock,
        UnavailableWindowsSessionProvider(),
    ).snapshot()

    assert snapshot.t2_active is False
    assert snapshot.context.trust_tier is TrustTier.UNVERIFIED
    assert snapshot.context.windows_session_valid is False
    assert snapshot.reason_codes == ("t2_windows_session_unavailable",)


def test_non_live_binding_never_grants_t2() -> None:
    assessment = replace(
        _live_owner(),
        state=OwnerLivenessBindingState.ACTIVE_CHALLENGE_ELIGIBLE,
        liveness_state=PassiveLivenessState.UNCERTAIN,
    )
    assert assessment.face_evidence_grants_t2 is False


def test_persistent_t2_floor_requires_actor_binding() -> None:
    floor = hard_floor_for(RiskClass.PERSISTENT_OR_EXTERNAL)
    assert floor.required_trust is TrustTier.CORROBORATED_OWNER
    assert floor.approval_requirement is ApprovalRequirement.DIRECT_INTENT
    assert floor.require_actor_unambiguous is True


def test_critical_floor_remains_t3_strong() -> None:
    floor = hard_floor_for(RiskClass.CRITICAL)
    assert floor.required_trust is TrustTier.VERIFIED_OWNER
    assert floor.approval_requirement is ApprovalRequirement.STRONG
