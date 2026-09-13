"""Vision observer that reacquires the live OWNER with Pocket 3 ActiveTrack."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import OwnerLivenessBindingState
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox
from jarvis.vision.owner_reacquisition import (
    NativeTrackingStatus,
    OwnerReacquisitionController,
    ReacquisitionAction,
    ReacquisitionConfig,
    ReacquisitionState,
)
from jarvis.vision.pocket3_native import Pocket3NativeConfig, Pocket3NativeTrackerClient
from jarvis.vision.runtime import VisionSnapshot

LOGGER = logging.getLogger(__name__)


class NativeOwnerTrackingClient(Protocol):
    @property
    def connected(self) -> bool: ...

    def start(self) -> None: ...

    def status(self) -> NativeTrackingStatus: ...

    def poll_tracking(self) -> None: ...

    def set_target(self, bounds: BoundingBox) -> bool: ...

    def clear_target(self) -> None: ...

    def recenter_gimbal(self) -> None: ...

    def close(self) -> None: ...


class OwnerPresenceObserver(Protocol):
    def observe(
        self,
        *,
        now: float,
        tracking_state: ReacquisitionState,
        owner_present: bool,
    ) -> object: ...

    def reset(self) -> None: ...


class Pocket3NativeOwnerTrackingClient(Pocket3NativeTrackerClient):
    """Pocket transport plus Mimo's native one-shot gimbal recenter command."""

    def recenter_gimbal(self) -> None:
        if not self.connected:
            return
        self._send_command(
            receiver=0x04,
            flags=0x40,
            cmd_set=0x04,
            cmd_id=0x4C,
            payload=b"\xfe\x08",
        )


@dataclass(frozen=True, slots=True)
class NativeOwnerTrackingConfig:
    poll_interval_seconds: float = 0.50
    reconnect_backoff_seconds: float = 5.0
    searching_perception_fps: float = 10.0
    locked_perception_fps: float = 2.0

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.reconnect_backoff_seconds <= 0:
            raise ValueError("reconnect_backoff_seconds must be positive")
        if self.searching_perception_fps <= 0:
            raise ValueError("searching_perception_fps must be positive")
        if self.locked_perception_fps <= 0:
            raise ValueError("locked_perception_fps must be positive")
        if self.locked_perception_fps > self.searching_perception_fps:
            raise ValueError(
                "locked_perception_fps must not exceed searching_perception_fps"
            )


class NativeOwnerTrackingObserver:
    """Bridge JARVIS OWNER evidence to native DJI tracking and recovery.

    Healthy native tracking owns continuous gimbal movement. JARVIS sends a fresh
    A6 only when a live OWNER candidate is visible and the native tracker is not
    already healthy. After a confirmed OWNER loss, the controller may clear the
    stale target and issue Mimo's native recenter before searching from home view.
    """

    def __init__(
        self,
        *,
        owner_context: OwnerContextState,
        client: NativeOwnerTrackingClient,
        controller: OwnerReacquisitionController | None = None,
        config: NativeOwnerTrackingConfig | None = None,
        owner_presence_observer: OwnerPresenceObserver | None = None,
    ) -> None:
        self.owner_context = owner_context
        self.client = client
        self.controller = controller or OwnerReacquisitionController()
        self.config = config or NativeOwnerTrackingConfig()
        self.owner_presence_observer = owner_presence_observer
        self._last_poll_at: float | None = None
        self._last_connect_attempt_at: float | None = None
        self._last_logged_state: ReacquisitionState | None = None

    def perception_fps_hint(self) -> float:
        """Return the maximum useful JARVIS perception rate for the current state."""
        if self.controller.state is ReacquisitionState.LOCKED:
            return self.config.locked_perception_fps
        return self.config.searching_perception_fps

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        now = frame.captured_at
        if not self.client.connected:
            if not self._reconnect_due(now):
                return
            self._last_connect_attempt_at = now
            try:
                self.client.start()
                LOGGER.info(
                    "Pocket 3 native owner tracking transport connected; "
                    "software PTZ remains SAFE"
                )
            except Exception:
                LOGGER.exception("Pocket 3 native tracking connection attempt failed")
                return

        if self._last_poll_at is None or (
            now - self._last_poll_at >= self.config.poll_interval_seconds
        ):
            try:
                self.client.poll_tracking()
                self._last_poll_at = now
            except Exception:
                LOGGER.exception("Pocket 3 A5 tracking poll failed")

        owner_bounds = None
        owner_observed_at = None
        context = self.owner_context.snapshot()
        assessment = context.assessment
        if (
            assessment is not None
            and assessment.state is OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE
        ):
            track = next(
                (
                    candidate
                    for candidate in snapshot.tracks
                    if candidate.track_id == assessment.visual_track_id
                ),
                None,
            )
            if track is not None:
                owner_bounds = track.bounds
                owner_observed_at = assessment.observed_at_monotonic

        decision = self.controller.step(
            now=now,
            owner_bounds=owner_bounds,
            owner_observed_at=owner_observed_at,
            native=self.client.status(),
        )
        if decision.state is not self._last_logged_state:
            LOGGER.info(
                "Pocket 3 owner-tracking state: %s (%s)",
                decision.state.value,
                decision.reason,
            )
            self._last_logged_state = decision.state

        if self.owner_presence_observer is not None:
            try:
                self.owner_presence_observer.observe(
                    now=now,
                    tracking_state=decision.state,
                    owner_present=owner_bounds is not None,
                )
            except Exception:
                LOGGER.exception("OWNER workstation-presence policy failed")

        if decision.action is ReacquisitionAction.RECENTER_GIMBAL:
            try:
                self.client.clear_target()
                self.client.recenter_gimbal()
                LOGGER.info(
                    "Pocket 3 native gimbal recenter sent after confirmed OWNER loss"
                )
            except Exception:
                LOGGER.exception("Pocket 3 native gimbal recenter failed")
            return

        if decision.action is not ReacquisitionAction.SET_OWNER_TARGET:
            return
        assert decision.bounds is not None
        try:
            direct_ack = self.client.set_target(decision.bounds)
            LOGGER.info(
                "Pocket 3 A6 owner target sent: reason=%s direct_ack=%s "
                "center=(%.3f, %.3f) size=(%.3f, %.3f)",
                decision.reason,
                direct_ack,
                decision.bounds.center_x,
                decision.bounds.center_y,
                decision.bounds.width,
                decision.bounds.height,
            )
        except Exception:
            LOGGER.exception("Pocket 3 A6 owner target failed")

    def close(self) -> None:
        self.client.close()
        self.controller.reset()
        if self.owner_presence_observer is not None:
            self.owner_presence_observer.reset()

    def _reconnect_due(self, now: float) -> bool:
        attempted = self._last_connect_attempt_at
        return (
            attempted is None
            or now - attempted >= self.config.reconnect_backoff_seconds
        )


def build_default_native_owner_tracking_observer(
    *,
    owner_context: OwnerContextState,
    ble_name: str = "OsmoPocket3-C36F",
    owner_evidence_max_age_seconds: float = 2.0,
    subject_push_stale_seconds: float = 1.25,
    lock_pending_timeout_seconds: float = 2.5,
    resend_cooldown_seconds: float = 1.0,
    recenter_after_loss_seconds: float = 1.0,
    recenter_settle_seconds: float = 0.75,
    searching_perception_fps: float = 10.0,
    locked_perception_fps: float = 2.0,
    owner_presence_observer: OwnerPresenceObserver | None = None,
) -> NativeOwnerTrackingObserver:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(
            owner_evidence_max_age_seconds=owner_evidence_max_age_seconds,
            subject_push_stale_seconds=subject_push_stale_seconds,
            lock_pending_timeout_seconds=lock_pending_timeout_seconds,
            resend_cooldown_seconds=resend_cooldown_seconds,
            recenter_after_loss_seconds=recenter_after_loss_seconds,
            recenter_settle_seconds=recenter_settle_seconds,
        )
    )
    return NativeOwnerTrackingObserver(
        owner_context=owner_context,
        client=Pocket3NativeOwnerTrackingClient(Pocket3NativeConfig(ble_name=ble_name)),
        controller=controller,
        config=NativeOwnerTrackingConfig(
            searching_perception_fps=searching_perception_fps,
            locked_perception_fps=locked_perception_fps,
        ),
        owner_presence_observer=owner_presence_observer,
    )
