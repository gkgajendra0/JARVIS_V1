"""Fail-open health adapters for the accepted JARVIS vision stack."""

from __future__ import annotations

import time
from collections.abc import Callable

from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.native_owner_tracking import NativeOwnerTrackingObserver
from jarvis.vision.runtime import VisionSnapshot

FramePairTap = Callable[[CapturedFrame, VisionSnapshot], None]


def _observe_safely(
    awareness: SelfAwarenessRuntime,
    *,
    component_id: str,
    source: str,
    state: HealthState,
    reason_code: str,
    summary: str,
    ttl_seconds: float,
    metadata: dict[str, object] | None = None,
) -> None:
    try:
        awareness.observe(
            component_id=component_id,
            source=source,
            state=state,
            reason_code=reason_code,
            summary=summary,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001,S110 - health reporting must never break vision
        pass


class VisionFrameHealthTap:
    """Refresh base-vision health from successful canonical frame/snapshot pairs."""

    def __init__(
        self,
        awareness: SelfAwarenessRuntime,
        *,
        minimum_emit_interval_seconds: float = 2.0,
        ttl_seconds: float = 6.0,
    ) -> None:
        if minimum_emit_interval_seconds <= 0:
            raise ValueError("minimum_emit_interval_seconds must be positive")
        if ttl_seconds <= minimum_emit_interval_seconds:
            raise ValueError("ttl_seconds must exceed the emit interval")
        self._awareness = awareness
        self._minimum_emit_interval_seconds = minimum_emit_interval_seconds
        self._ttl_seconds = ttl_seconds
        self._last_emit_at: float | None = None

    def __call__(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        now = time.monotonic()
        if (
            self._last_emit_at is not None
            and now - self._last_emit_at < self._minimum_emit_interval_seconds
        ):
            return
        self._last_emit_at = now
        _observe_safely(
            self._awareness,
            component_id="vision.base",
            source="vision_frame_pipeline",
            state=HealthState.HEALTHY,
            reason_code="fresh_frame_snapshot_pair",
            summary="Vision is producing fresh frame/snapshot pairs",
            ttl_seconds=self._ttl_seconds,
            metadata={"frame_id": frame.frame_id, "track_count": len(snapshot.tracks)},
        )


class NativeTrackingHealthObserver:
    """Wrap native OWNER tracking and report transport health without changing it."""

    def __init__(
        self,
        delegate: NativeOwnerTrackingObserver,
        awareness: SelfAwarenessRuntime,
        *,
        healthy_refresh_seconds: float = 2.0,
        ttl_seconds: float = 8.0,
    ) -> None:
        if healthy_refresh_seconds <= 0:
            raise ValueError("healthy_refresh_seconds must be positive")
        if ttl_seconds <= healthy_refresh_seconds:
            raise ValueError("ttl_seconds must exceed the refresh interval")
        self._delegate = delegate
        self._awareness = awareness
        self._healthy_refresh_seconds = healthy_refresh_seconds
        self._ttl_seconds = ttl_seconds
        self._last_connected: bool | None = None
        self._last_emit_at: float | None = None

    @property
    def owner_context(self):
        return self._delegate.owner_context

    @property
    def client(self):
        return self._delegate.client

    @property
    def controller(self):
        return self._delegate.controller

    @property
    def config(self):
        return self._delegate.config

    def wait_for_startup_lock(self, timeout_seconds: float) -> bool:
        return self._delegate.wait_for_startup_lock(timeout_seconds)

    def perception_fps_hint(self) -> float:
        return self._delegate.perception_fps_hint()

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        try:
            self._delegate.observe(frame, snapshot)
        except Exception as exc:
            self._report(
                connected=False,
                state=HealthState.FAILED,
                reason_code="native_tracking_observer_failed",
                summary="Pocket 3 native tracking observer failed",
                metadata={"error_type": type(exc).__name__},
                force=True,
            )
            raise

        connected = bool(self._delegate.client.connected)
        if connected:
            self._report(
                connected=True,
                state=HealthState.HEALTHY,
                reason_code="native_tracking_transport_connected",
                summary="Pocket 3 native tracking transport is connected",
                metadata={"tracking_state": self._delegate.controller.state.value},
            )
        else:
            self._report(
                connected=False,
                state=HealthState.DEGRADED,
                reason_code="native_tracking_transport_unavailable",
                summary=(
                    "Pocket 3 native tracking transport is unavailable; "
                    "base vision remains separate"
                ),
                metadata={"tracking_state": self._delegate.controller.state.value},
            )

    def close(self) -> None:
        try:
            self._delegate.close()
        finally:
            _observe_safely(
                self._awareness,
                component_id="vision.pocket3",
                source="native_tracking_transport",
                state=HealthState.DISABLED,
                reason_code="native_tracking_stopped",
                summary="Pocket 3 native tracking observer stopped",
                ttl_seconds=self._ttl_seconds,
            )

    def _report(
        self,
        *,
        connected: bool,
        state: HealthState,
        reason_code: str,
        summary: str,
        metadata: dict[str, object],
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        state_changed = connected != self._last_connected
        refresh_due = (
            self._last_emit_at is None
            or now - self._last_emit_at >= self._healthy_refresh_seconds
        )
        if not force and not state_changed and not refresh_due:
            return
        self._last_connected = connected
        self._last_emit_at = now
        _observe_safely(
            self._awareness,
            component_id="vision.pocket3",
            source="native_tracking_transport",
            state=state,
            reason_code=reason_code,
            summary=summary,
            ttl_seconds=self._ttl_seconds,
            metadata=metadata,
        )


def compose_frame_pair_taps(*taps: FramePairTap | None) -> FramePairTap | None:
    active = tuple(tap for tap in taps if tap is not None)
    if not active:
        return None
    if len(active) == 1:
        return active[0]

    def composed(frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        for tap in active:
            try:
                tap(frame, snapshot)
            except Exception:  # noqa: BLE001,S110 - one diagnostic tap must not block peers
                pass

    return composed
