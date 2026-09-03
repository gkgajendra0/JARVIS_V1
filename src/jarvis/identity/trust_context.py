from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.authority import (
    AttentionState,
    InteractionContext,
    TrustTier,
    WindowsSessionProvider,
    WindowsSessionUnavailable,
    WindowsWtsSessionProvider,
)
from jarvis.identity.owner_context import OwnerContextState

_DEFAULT_OWNER_EVIDENCE_TTL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class OwnerTrustContextSnapshot:
    """Derived authority context; never contains raw biometric material or scores."""

    context: InteractionContext
    t2_active: bool
    visual_track_id: int | None
    observed_at_monotonic: float | None
    reason_codes: tuple[str, ...]


class OwnerTrustContextProvider:
    """Bridge accepted live OWNER evidence into bounded T2 authority context.

    T2 means a fresh enrolled OWNER face and passive liveness are bound to the same
    visible track in the current unlocked Windows session. It deliberately does not
    assert who spoke a particular command, so actor_unambiguous remains False until a
    separate actor-binding path is accepted. T3 is never granted here.
    """

    def __init__(
        self,
        owner_context: OwnerContextState,
        *,
        windows_session_provider: WindowsSessionProvider | None = None,
        clock: Callable[[], float] = time.monotonic,
        owner_evidence_ttl_seconds: float = _DEFAULT_OWNER_EVIDENCE_TTL_SECONDS,
    ) -> None:
        if owner_evidence_ttl_seconds <= 0:
            raise ValueError("OWNER trust-context evidence TTL must be positive")
        self._owner_context = owner_context
        self._windows_session_provider = (
            windows_session_provider or WindowsWtsSessionProvider(clock=clock)
        )
        self._clock = clock
        self._owner_evidence_ttl_seconds = owner_evidence_ttl_seconds

    def snapshot(self) -> OwnerTrustContextSnapshot:
        owner_snapshot = self._owner_context.snapshot()
        assessment = owner_snapshot.assessment
        fallback_session_id = assessment.session_id if assessment is not None else "wts:unavailable"

        try:
            windows_session = self._windows_session_provider.current_session()
        except WindowsSessionUnavailable:
            return self._unverified(
                session_id=fallback_session_id,
                windows_session_valid=False,
                visual_track_id=(
                    assessment.visual_track_id if assessment is not None else None
                ),
                observed_at_monotonic=(
                    assessment.observed_at_monotonic if assessment is not None else None
                ),
                reason="t2_windows_session_unavailable",
            )

        if not windows_session.active_unlocked:
            return self._unverified(
                session_id=windows_session.session_id,
                windows_session_valid=False,
                visual_track_id=(
                    assessment.visual_track_id if assessment is not None else None
                ),
                observed_at_monotonic=(
                    assessment.observed_at_monotonic if assessment is not None else None
                ),
                reason="t2_windows_session_locked",
            )

        if assessment is None:
            return self._unverified(
                session_id=windows_session.session_id,
                windows_session_valid=True,
                visual_track_id=None,
                observed_at_monotonic=None,
                reason=owner_snapshot.invalidation_reason or "t2_owner_context_not_observed",
            )

        if assessment.session_id != windows_session.session_id:
            return self._unverified(
                session_id=windows_session.session_id,
                windows_session_valid=True,
                visual_track_id=assessment.visual_track_id,
                observed_at_monotonic=assessment.observed_at_monotonic,
                reason="t2_owner_windows_session_mismatch",
            )

        fresh = self._owner_context.has_fresh_live_owner_candidate(
            now_monotonic=self._clock(),
            max_age_seconds=self._owner_evidence_ttl_seconds,
        )
        if not fresh:
            return self._unverified(
                session_id=windows_session.session_id,
                windows_session_valid=True,
                visual_track_id=assessment.visual_track_id,
                observed_at_monotonic=assessment.observed_at_monotonic,
                reason="t2_live_owner_evidence_stale_or_insufficient",
            )

        if not assessment.face_evidence_grants_t2:
            return self._unverified(
                session_id=windows_session.session_id,
                windows_session_valid=True,
                visual_track_id=assessment.visual_track_id,
                observed_at_monotonic=assessment.observed_at_monotonic,
                reason="t2_owner_evidence_not_eligible",
            )

        return OwnerTrustContextSnapshot(
            context=InteractionContext(
                session_id=windows_session.session_id,
                trust_tier=TrustTier.CORROBORATED_OWNER,
                attention_state=AttentionState.UNAVAILABLE,
                actor_unambiguous=False,
                windows_session_valid=True,
            ),
            t2_active=True,
            visual_track_id=assessment.visual_track_id,
            observed_at_monotonic=assessment.observed_at_monotonic,
            reason_codes=("t2_live_owner_face_liveness_wts_corroborated",),
        )

    @staticmethod
    def _unverified(
        *,
        session_id: str,
        windows_session_valid: bool,
        visual_track_id: int | None,
        observed_at_monotonic: float | None,
        reason: str,
    ) -> OwnerTrustContextSnapshot:
        return OwnerTrustContextSnapshot(
            context=InteractionContext(
                session_id=session_id,
                trust_tier=TrustTier.UNVERIFIED,
                attention_state=AttentionState.UNAVAILABLE,
                actor_unambiguous=False,
                windows_session_valid=windows_session_valid,
            ),
            t2_active=False,
            visual_track_id=visual_track_id,
            observed_at_monotonic=observed_at_monotonic,
            reason_codes=(reason,),
        )
