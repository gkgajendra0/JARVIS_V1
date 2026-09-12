"""Owner-aware native tracking reacquisition policy.

This module deliberately contains no DJI transport code. It decides *when* JARVIS
may hand a fresh owner box to a native camera tracker. Continuous gimbal motion
remains the camera firmware's job once a native lock is healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.vision.models import BoundingBox


class ReacquisitionState(str, Enum):
    SEARCHING = "searching"
    LOCK_PENDING = "lock_pending"
    LOCKED = "locked"
    REACQUIRING = "reacquiring"


class ReacquisitionAction(str, Enum):
    NONE = "none"
    SET_OWNER_TARGET = "set_owner_target"


@dataclass(frozen=True, slots=True)
class NativeTrackingStatus:
    connected: bool
    active: bool
    last_poll_at: float | None = None
    last_subject_push_at: float | None = None


@dataclass(frozen=True, slots=True)
class ReacquisitionConfig:
    owner_evidence_max_age_seconds: float = 2.0
    subject_push_stale_seconds: float = 1.25
    lock_pending_timeout_seconds: float = 2.5
    resend_cooldown_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "owner_evidence_max_age_seconds",
            "subject_push_stale_seconds",
            "lock_pending_timeout_seconds",
            "resend_cooldown_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class ReacquisitionDecision:
    state: ReacquisitionState
    action: ReacquisitionAction = ReacquisitionAction.NONE
    bounds: BoundingBox | None = None
    reason: str = ""


class OwnerReacquisitionController:
    """State machine for initial owner lock and automatic return-to-frame relock."""

    def __init__(self, config: ReacquisitionConfig | None = None) -> None:
        self.config = config or ReacquisitionConfig()
        self.state = ReacquisitionState.SEARCHING
        self._last_target_sent_at: float | None = None
        self._lock_pending_since: float | None = None
        self._ever_locked = False

    def reset(self) -> None:
        self.state = ReacquisitionState.SEARCHING
        self._last_target_sent_at = None
        self._lock_pending_since = None
        self._ever_locked = False

    def step(
        self,
        *,
        now: float,
        owner_bounds: BoundingBox | None,
        owner_observed_at: float | None,
        native: NativeTrackingStatus,
    ) -> ReacquisitionDecision:
        if now < 0:
            raise ValueError("now must be non-negative")

        owner_fresh = self._owner_is_fresh(
            now=now,
            owner_bounds=owner_bounds,
            owner_observed_at=owner_observed_at,
        )
        native_healthy = self._native_is_healthy(now=now, native=native)

        if native_healthy:
            self.state = ReacquisitionState.LOCKED
            self._lock_pending_since = None
            self._ever_locked = True
            return ReacquisitionDecision(
                state=self.state,
                reason="native_tracking_healthy",
            )

        if self.state is ReacquisitionState.LOCKED:
            # Do not recenter or issue another target merely because 0x89 went quiet.
            # A fresh negative A5 poll (or transport loss) is the fail-closed signal
            # that native tracking has actually dropped the subject.
            if not native.connected or self._fresh_negative_poll(now=now, native=native):
                self.state = ReacquisitionState.REACQUIRING
            else:
                return ReacquisitionDecision(
                    state=self.state,
                    reason="awaiting_native_loss_confirmation",
                )

        if self.state is ReacquisitionState.LOCK_PENDING:
            pending_since = self._lock_pending_since
            if (
                pending_since is not None
                and now - pending_since < self.config.lock_pending_timeout_seconds
            ):
                return ReacquisitionDecision(
                    state=self.state,
                    reason="awaiting_native_lock",
                )
            self.state = (
                ReacquisitionState.REACQUIRING
                if self._ever_locked
                else ReacquisitionState.SEARCHING
            )
            self._lock_pending_since = None

        if not native.connected:
            return ReacquisitionDecision(
                state=self.state,
                reason="native_transport_unavailable",
            )

        if not owner_fresh:
            return ReacquisitionDecision(
                state=self.state,
                reason="fresh_live_owner_not_visible",
            )

        if not self._resend_allowed(now):
            return ReacquisitionDecision(
                state=self.state,
                reason="target_resend_cooldown",
            )

        assert owner_bounds is not None
        self.state = ReacquisitionState.LOCK_PENDING
        self._last_target_sent_at = now
        self._lock_pending_since = now
        return ReacquisitionDecision(
            state=self.state,
            action=ReacquisitionAction.SET_OWNER_TARGET,
            bounds=owner_bounds,
            reason=(
                "owner_reacquired" if self._ever_locked else "initial_owner_acquisition"
            ),
        )

    def _owner_is_fresh(
        self,
        *,
        now: float,
        owner_bounds: BoundingBox | None,
        owner_observed_at: float | None,
    ) -> bool:
        if owner_bounds is None or owner_observed_at is None:
            return False
        age = now - owner_observed_at
        return 0 <= age <= self.config.owner_evidence_max_age_seconds

    def _native_is_healthy(
        self,
        *,
        now: float,
        native: NativeTrackingStatus,
    ) -> bool:
        if not native.connected:
            return False
        if native.active:
            return True
        pushed_at = native.last_subject_push_at
        return bool(
            pushed_at is not None
            and 0 <= now - pushed_at <= self.config.subject_push_stale_seconds
        )

    def _fresh_negative_poll(
        self,
        *,
        now: float,
        native: NativeTrackingStatus,
    ) -> bool:
        polled_at = native.last_poll_at
        return bool(
            native.connected
            and not native.active
            and polled_at is not None
            and 0 <= now - polled_at <= self.config.subject_push_stale_seconds
        )

    def _resend_allowed(self, now: float) -> bool:
        sent_at = self._last_target_sent_at
        return sent_at is None or now - sent_at >= self.config.resend_cooldown_seconds
