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
    RECENTER_GIMBAL = "recenter_gimbal"


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
    recenter_after_loss_seconds: float = 1.0
    recenter_settle_seconds: float = 0.75

    def __post_init__(self) -> None:
        for name in (
            "owner_evidence_max_age_seconds",
            "subject_push_stale_seconds",
            "lock_pending_timeout_seconds",
            "resend_cooldown_seconds",
            "recenter_after_loss_seconds",
            "recenter_settle_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class ReacquisitionDecision:
    state: ReacquisitionState
    action: ReacquisitionAction = ReacquisitionAction.NONE
    bounds: BoundingBox | None = None
    reason: str = ""
    owner_absence_confirmed: bool = False


class OwnerReacquisitionController:
    """State machine for initial owner lock and automatic return-to-frame relock.

    A native DJI tracking signal is not an identity signal. Native tracking may
    confirm a LOCK_PENDING target that JARVIS selected from fresh live-OWNER
    evidence, and it may maintain that already-authorized lock while OWNER
    evidence is only briefly missing. It may never promote SEARCHING or
    REACQUIRING to LOCKED by itself.

    Native-tracking loss and OWNER absence are separate signals. Losing DJI's
    subject box may require reacquisition/recenter, but it must never by itself be
    treated as proof that the OWNER left the workstation. ``owner_absence_confirmed``
    is raised only after live OWNER evidence has remained absent for the configured
    confirmation window.
    """

    def __init__(self, config: ReacquisitionConfig | None = None) -> None:
        self.config = config or ReacquisitionConfig()
        self.state = ReacquisitionState.SEARCHING
        self._last_target_sent_at: float | None = None
        self._lock_pending_since: float | None = None
        self._lost_since: float | None = None
        self._recenter_sent_at: float | None = None
        self._owner_missing_since: float | None = None
        self._ever_locked = False

    def reset(self) -> None:
        self.state = ReacquisitionState.SEARCHING
        self._last_target_sent_at = None
        self._lock_pending_since = None
        self._lost_since = None
        self._recenter_sent_at = None
        self._owner_missing_since = None
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

        if owner_fresh:
            self._owner_missing_since = None
        elif (
            self._ever_locked
            and self.state
            in (
                ReacquisitionState.LOCKED,
                ReacquisitionState.REACQUIRING,
            )
            and self._owner_missing_since is None
        ):
            self._owner_missing_since = now

        owner_absence_confirmed = self._owner_loss_is_confirmed(now)

        if self.state is ReacquisitionState.LOCK_PENDING and native_healthy:
            self.state = ReacquisitionState.LOCKED
            self._lock_pending_since = None
            self._lost_since = None
            self._recenter_sent_at = None
            self._owner_missing_since = None if owner_fresh else now
            self._ever_locked = True
            return ReacquisitionDecision(
                state=self.state,
                reason="authorized_native_tracking_healthy",
            )

        if self.state is ReacquisitionState.LOCKED:
            native_loss_confirmed = (
                not native.connected
                or self._fresh_negative_poll(now=now, native=native)
                or self._subject_push_is_stale(now=now, native=native)
            )
            if owner_absence_confirmed or native_loss_confirmed:
                self.state = ReacquisitionState.REACQUIRING
                self._lost_since = now
                self._recenter_sent_at = None
                return ReacquisitionDecision(
                    state=self.state,
                    reason=(
                        "confirmed_owner_absence"
                        if owner_absence_confirmed
                        else "native_tracking_lost_reacquiring"
                    ),
                    owner_absence_confirmed=owner_absence_confirmed,
                )
            if native_healthy:
                return ReacquisitionDecision(
                    state=self.state,
                    reason=(
                        "native_tracking_healthy"
                        if owner_fresh
                        else "awaiting_owner_loss_confirmation"
                    ),
                )
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
            if (
                self.state is ReacquisitionState.REACQUIRING
                and self._lost_since is None
            ):
                self._lost_since = now
                self._recenter_sent_at = None

        if not native.connected:
            return ReacquisitionDecision(
                state=self.state,
                reason="native_transport_unavailable",
                owner_absence_confirmed=owner_absence_confirmed,
            )

        if owner_fresh:
            if self._recenter_is_settling(now):
                return ReacquisitionDecision(
                    state=self.state,
                    reason="awaiting_recenter_settle",
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
                    "owner_reacquired"
                    if self._ever_locked
                    else "initial_owner_acquisition"
                ),
            )

        if self.state is ReacquisitionState.REACQUIRING:
            if self._recenter_is_settling(now):
                return ReacquisitionDecision(
                    state=self.state,
                    reason="awaiting_recenter_settle",
                    owner_absence_confirmed=owner_absence_confirmed,
                )
            if self._recenter_is_due(now):
                self._recenter_sent_at = now
                return ReacquisitionDecision(
                    state=self.state,
                    action=ReacquisitionAction.RECENTER_GIMBAL,
                    reason="confirmed_owner_loss_recenter",
                    owner_absence_confirmed=owner_absence_confirmed,
                )

        return ReacquisitionDecision(
            state=self.state,
            reason="fresh_live_owner_not_visible",
            owner_absence_confirmed=owner_absence_confirmed,
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

    def _owner_loss_is_confirmed(self, now: float) -> bool:
        missing_since = self._owner_missing_since
        return bool(
            missing_since is not None
            and now - missing_since >= self.config.owner_evidence_max_age_seconds
        )

    def _native_is_healthy(
        self,
        *,
        now: float,
        native: NativeTrackingStatus,
    ) -> bool:
        if not native.connected:
            return False
        pushed_at = native.last_subject_push_at
        if pushed_at is not None:
            return 0 <= now - pushed_at <= self.config.subject_push_stale_seconds
        return native.active

    def _subject_push_is_stale(
        self,
        *,
        now: float,
        native: NativeTrackingStatus,
    ) -> bool:
        pushed_at = native.last_subject_push_at
        return bool(
            native.connected
            and pushed_at is not None
            and now - pushed_at > self.config.subject_push_stale_seconds
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

    def _recenter_is_due(self, now: float) -> bool:
        lost_since = self._lost_since
        return bool(
            lost_since is not None
            and self._recenter_sent_at is None
            and now - lost_since > self.config.recenter_after_loss_seconds
        )

    def _recenter_is_settling(self, now: float) -> bool:
        sent_at = self._recenter_sent_at
        return bool(
            sent_at is not None and now - sent_at < self.config.recenter_settle_seconds
        )
