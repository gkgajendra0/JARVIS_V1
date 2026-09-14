from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.self_model.health import HealthState
from jarvis.vision.health_observers import (
    NativeTrackingHealthObserver,
    VisionFrameHealthTap,
    compose_frame_pair_taps,
)


class FakeAwareness:
    def __init__(self) -> None:
        self.observations: list[dict] = []

    def observe(self, **kwargs):
        self.observations.append(kwargs)


class FakeClient:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class FakeTrackingDelegate:
    def __init__(self, *, connected: bool = True, fail: bool = False) -> None:
        self.client = FakeClient(connected)
        self.controller = SimpleNamespace(state=SimpleNamespace(value="searching"))
        self.owner_context = object()
        self.config = object()
        self.fail = fail
        self.closed = False

    def observe(self, frame, snapshot) -> None:
        del frame, snapshot
        if self.fail:
            raise RuntimeError("tracking failed")

    def close(self) -> None:
        self.closed = True

    def wait_for_startup_lock(self, timeout_seconds: float) -> bool:
        return timeout_seconds > 0

    def perception_fps_hint(self) -> float:
        return 2.0


def test_vision_frame_tap_reports_fresh_pipeline_health() -> None:
    awareness = FakeAwareness()
    tap = VisionFrameHealthTap(awareness)  # type: ignore[arg-type]

    tap(SimpleNamespace(frame_id=7), SimpleNamespace(tracks=(1, 2)))

    assert len(awareness.observations) == 1
    observation = awareness.observations[0]
    assert observation["component_id"] == "vision.base"
    assert observation["state"] is HealthState.HEALTHY
    assert observation["metadata"] == {"frame_id": 7, "track_count": 2}


def test_native_tracking_wrapper_separates_transport_from_owner_search() -> None:
    awareness = FakeAwareness()
    delegate = FakeTrackingDelegate(connected=True)
    wrapper = NativeTrackingHealthObserver(
        delegate,  # type: ignore[arg-type]
        awareness,  # type: ignore[arg-type]
    )

    wrapper.observe(object(), object())  # type: ignore[arg-type]

    observation = awareness.observations[-1]
    assert observation["component_id"] == "vision.pocket3"
    assert observation["state"] is HealthState.HEALTHY
    assert observation["metadata"]["tracking_state"] == "searching"


def test_native_tracking_disconnected_is_degraded_not_base_vision_failed() -> None:
    awareness = FakeAwareness()
    wrapper = NativeTrackingHealthObserver(
        FakeTrackingDelegate(connected=False),  # type: ignore[arg-type]
        awareness,  # type: ignore[arg-type]
    )

    wrapper.observe(object(), object())  # type: ignore[arg-type]

    observation = awareness.observations[-1]
    assert observation["component_id"] == "vision.pocket3"
    assert observation["state"] is HealthState.DEGRADED
    assert "base vision remains separate" in observation["summary"]


def test_native_tracking_delegate_failure_is_reported_then_preserved() -> None:
    awareness = FakeAwareness()
    wrapper = NativeTrackingHealthObserver(
        FakeTrackingDelegate(fail=True),  # type: ignore[arg-type]
        awareness,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="tracking failed"):
        wrapper.observe(object(), object())  # type: ignore[arg-type]

    assert awareness.observations[-1]["state"] is HealthState.FAILED
    assert awareness.observations[-1]["reason_code"] == "native_tracking_observer_failed"


def test_composed_frame_taps_isolate_peer_failures() -> None:
    called: list[str] = []

    def broken(frame, snapshot) -> None:
        del frame, snapshot
        called.append("broken")
        raise RuntimeError("tap failed")

    def healthy(frame, snapshot) -> None:
        del frame, snapshot
        called.append("healthy")

    composed = compose_frame_pair_taps(broken, healthy)
    assert composed is not None
    composed(object(), object())  # type: ignore[arg-type]

    assert called == ["broken", "healthy"]
