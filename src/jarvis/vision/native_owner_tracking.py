"""Vision observer that reacquires the live OWNER with Pocket 3 ActiveTrack."""

from __future__ import annotations

import logging
import threading
import time
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
from jarvis.vision.pocket3_native import Pocket3NativeConfig
from jarvis.vision.pocket3_recovery import ResilientPocket3NativeOwnerTrackingClient
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

    def recover_tracking_session(self) -> None: ...

    def close(self) -> None: ...


Pocket3NativeOwnerTrackingClient = ResilientPocket3NativeOwnerTrackingClient


@dataclass(frozen=True, slots=True)
class NativeOwnerTrackingConfig:
    poll_interval_seconds: float = 0.50
    reconnect_backoff_seconds: float = 5.0
    searching_perception_fps: float = 10.0
    locked_perception_fps: float = 2.0
    target_attempts_before_session_recovery: int = 3
    session_recovery_cooldown_seconds: float = 10.0
    transport_rx_stale_seconds: float = 3.0

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
        if self.target_attempts_before_session_recovery <= 0:
            raise ValueError("target_attempts_before_session_recovery must be positive")
        if self.session_recovery_cooldown_seconds <= 0:
            raise ValueError("session_recovery_cooldown_seconds must be positive")
        if self.transport_rx_stale_seconds <= 0:
            raise ValueError("transport_rx_stale_seconds must be positive")


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
    ) -> None:
        self.owner_context = owner_context
        self.client = client
        self.controller = controller or OwnerReacquisitionController()
        self.config = config or NativeOwnerTrackingConfig()
        self._last_poll_at: float | None = None
        self._last_connect_attempt_at: float | None = None
        self._last_logged_state: ReacquisitionState | None = None
        self._owner_observed_in_latest_snapshot = False
        self._target_attempts_without_native_lock = 0
        self._last_session_recovery_at: float | None = None
        self._recovery_thread: threading.Thread | None = None
        self._recovery_succeeded: bool | None = None
        self._closing = threading.Event()
        self._startup_lock_event = threading.Event()

    def wait_for_startup_lock(self, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._startup_lock_event.wait(timeout_seconds)

    def perception_fps_hint(self) -> float:
        """Return the useful JARVIS perception rate for the current trust state.

        Native ActiveTrack lets JARVIS reduce CPU while an already-authorized OWNER
        lock is healthy. The biometric assessment may intentionally survive a short
        Roboflow association miss, but such a miss must still trigger full-rate
        perception so the local tracker can re-associate quickly. Low-rate mode is
        therefore allowed only while the verified OWNER is also observed in the
        latest processed snapshot.
        """
        if (
            self.controller.state is ReacquisitionState.LOCKED
            and self._owner_observed_in_latest_snapshot
            and self.owner_context.has_fresh_live_owner_candidate()
        ):
            return self.config.locked_perception_fps
        return self.config.searching_perception_fps

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        now = frame.captured_at
        self._finish_session_recovery(now)
        if self._session_recovery_in_progress():
            return

        if not self.client.connected:
            if not self._reconnect_due(now):
                return
            try:
                self.client.start()
            except Exception:
                # The attempt can spend many seconds in BLE/WLAN setup. Start the
                # reconnect cooldown when that attempt actually finishes, not from the
                # stale frame timestamp captured before it began.
                self._last_connect_attempt_at = time.monotonic()
                if not self._closing.is_set():
                    LOGGER.exception(
                        "Pocket 3 native tracking connection attempt failed"
                    )
                return
            self._last_connect_attempt_at = time.monotonic()
            LOGGER.info(
                "Pocket 3 native owner tracking transport connected; "
                "software PTZ remains SAFE"
            )
            # Do not feed a frame captured before a potentially slow connection into
            # reacquisition timing. The next fresh vision frame will poll/target.
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
        self._owner_observed_in_latest_snapshot = owner_bounds is not None

        native_status = self.client.status()
        if self._transport_rx_is_stale(now, native_status):
            if self._session_recovery_due(now):
                self._start_session_recovery(now, reason="stale_transport_rx")
            return

        if self._native_lock_evidence_is_fresh(now, native_status):
            self._target_attempts_without_native_lock = 0

        decision = self.controller.step(
            now=now,
            owner_bounds=owner_bounds,
            owner_observed_at=owner_observed_at,
            native=native_status,
        )
        if decision.state is ReacquisitionState.LOCKED:
            self._startup_lock_event.set()
        if decision.state is not self._last_logged_state:
            LOGGER.info(
                "Pocket 3 owner-tracking state: %s (%s)",
                decision.state.value,
                decision.reason,
            )
            self._last_logged_state = decision.state

        if decision.action is ReacquisitionAction.RECENTER_GIMBAL:
            self._target_attempts_without_native_lock = 0
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

        if (
            self._target_attempts_without_native_lock
            >= self.config.target_attempts_before_session_recovery
            and self._session_recovery_due(now)
        ):
            self._start_session_recovery(now, reason="unconfirmed_native_lock")
            return

        try:
            direct_ack = self.client.set_target(decision.bounds)
            self._target_attempts_without_native_lock += 1
            LOGGER.info(
                "Pocket 3 A6 owner target sent: reason=%s direct_ack=%s "
                "attempt_without_native_lock=%s center=(%.3f, %.3f) size=(%.3f, %.3f)",
                decision.reason,
                direct_ack,
                self._target_attempts_without_native_lock,
                decision.bounds.center_x,
                decision.bounds.center_y,
                decision.bounds.width,
                decision.bounds.height,
            )
        except Exception:
            self._target_attempts_without_native_lock += 1
            LOGGER.exception("Pocket 3 A6 owner target failed")

    def close(self) -> None:
        self._closing.set()
        self.client.close()
        recovery_thread = self._recovery_thread
        if recovery_thread is not None and recovery_thread.is_alive():
            recovery_thread.join(timeout=2.0)
            if recovery_thread.is_alive():
                LOGGER.warning("Pocket 3 recovery thread is still winding down")
            self.client.close()
        self._recovery_thread = None
        self.controller.reset()
        self._owner_observed_in_latest_snapshot = False
        self._target_attempts_without_native_lock = 0
        self._startup_lock_event.clear()

    def _reconnect_due(self, now: float) -> bool:
        attempted = self._last_connect_attempt_at
        return (
            attempted is None
            or now - attempted >= self.config.reconnect_backoff_seconds
        )

    def _transport_rx_is_stale(
        self,
        now: float,
        native_status: NativeTrackingStatus,
    ) -> bool:
        if not native_status.connected:
            return False
        received_at = native_status.last_transport_rx_at
        if received_at is None:
            return False
        age = now - received_at
        return age >= 0 and age > self.config.transport_rx_stale_seconds

    def _native_lock_evidence_is_fresh(
        self,
        now: float,
        native_status: NativeTrackingStatus,
    ) -> bool:
        if not native_status.connected or not native_status.active:
            return False
        pushed_at = native_status.last_subject_push_at
        if pushed_at is None:
            return False
        freshness_seconds = self.controller.config.subject_push_stale_seconds
        return 0 <= now - pushed_at <= freshness_seconds

    def _session_recovery_due(self, now: float) -> bool:
        attempted = self._last_session_recovery_at
        return (
            attempted is None
            or now - attempted >= self.config.session_recovery_cooldown_seconds
        )

    def _session_recovery_in_progress(self) -> bool:
        thread = self._recovery_thread
        return thread is not None and thread.is_alive()

    def _start_session_recovery(self, now: float, *, reason: str) -> None:
        if self._session_recovery_in_progress():
            return
        self._last_session_recovery_at = now
        self._recovery_succeeded = None

        def recover() -> None:
            succeeded = False
            try:
                self.client.recover_tracking_session()
                succeeded = True
            except Exception:
                LOGGER.exception("Pocket 3 native tracking session recovery failed")
            finally:
                if self._closing.is_set():
                    self.client.close()
                self._recovery_succeeded = succeeded

        self._recovery_thread = threading.Thread(
            target=recover,
            name="jarvis-pocket3-tracking-recovery",
            daemon=True,
        )
        self._recovery_thread.start()
        LOGGER.warning(
            "Pocket 3 native tracking recovery started: reason=%s "
            "target_attempts_without_native_lock=%s",
            reason,
            self._target_attempts_without_native_lock,
        )

    def _finish_session_recovery(self, now: float) -> None:
        thread = self._recovery_thread
        if thread is None or thread.is_alive():
            return
        thread.join(timeout=0.0)
        succeeded = bool(self._recovery_succeeded)
        self._recovery_thread = None
        self._recovery_succeeded = None
        self._target_attempts_without_native_lock = 0
        self._last_poll_at = None
        self._last_connect_attempt_at = now
        if succeeded:
            self.controller.reset()
            self._last_logged_state = None
            LOGGER.info(
                "Pocket 3 native tracking session recovered; OWNER reacquisition reset "
                "to searching until fresh native lock evidence returns"
            )
        else:
            LOGGER.warning(
                "Pocket 3 native tracking session recovery did not restore transport; "
                "normal reconnect backoff remains active"
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
    )
