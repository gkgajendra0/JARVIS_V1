import numpy as np
import pytest

from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox, FollowCommand, Track
from jarvis.vision.native_owner_tracking import (
    NativeOwnerTrackingConfig,
    NativeOwnerTrackingObserver,
)
from jarvis.vision.owner_reacquisition import NativeTrackingStatus
from jarvis.vision.runtime import VisionSnapshot


class FakeNativeClient:
    def __init__(self, status: NativeTrackingStatus) -> None:
        self.connected = status.connected
        self.native_status = status
        self.targets: list[BoundingBox] = []
        self.recoveries = 0

    def start(self) -> None:
        self.connected = True

    def status(self) -> NativeTrackingStatus:
        return self.native_status

    def poll_tracking(self) -> None:
        return None

    def set_target(self, bounds: BoundingBox) -> bool:
        self.targets.append(bounds)
        return True

    def clear_target(self) -> None:
        return None

    def recenter_gimbal(self) -> None:
        return None

    def recover_tracking_session(self) -> None:
        self.recoveries += 1
        self.connected = True
        self.native_status = NativeTrackingStatus(
            connected=True,
            active=False,
            last_transport_rx_at=None,
        )

    def close(self) -> None:
        self.connected = False


def _owner(track_id: int, now: float) -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id="session-transport-watchdog",
        visual_track_id=track_id,
        state=OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=now,
        reason_codes=("test_live_owner",),
    )


def _frame(frame_id: int, now: float) -> CapturedFrame:
    return CapturedFrame(
        frame_id=frame_id,
        captured_at=now,
        image=np.zeros((32, 32, 3), dtype=np.uint8),
    )


def _snapshot(frame_id: int, now: float, bounds: BoundingBox) -> VisionSnapshot:
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=now,
        tracks=(
            Track(
                track_id=7,
                category="person",
                confidence=0.95,
                bounds=bounds,
                first_seen_at=max(0.0, now - 1.0),
                last_seen_at=now,
            ),
        ),
        target=None,
        command=FollowCommand(),
        armed=False,
    )


def test_tracking_config_rejects_invalid_transport_watchdog() -> None:
    with pytest.raises(ValueError, match="transport_rx_stale_seconds"):
        NativeOwnerTrackingConfig(transport_rx_stale_seconds=0.0)


def test_stale_transport_receive_triggers_one_session_recovery() -> None:
    now = 10.0
    bounds = BoundingBox(0.2, 0.15, 0.6, 0.85)
    owner_context = OwnerContextState()
    owner_context.publish(_owner(7, now))
    client = FakeNativeClient(
        NativeTrackingStatus(
            connected=True,
            active=True,
            last_poll_at=now,
            last_subject_push_at=now,
            last_transport_rx_at=5.0,
        )
    )
    observer = NativeOwnerTrackingObserver(
        owner_context=owner_context,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(
            transport_rx_stale_seconds=3.0,
            session_recovery_cooldown_seconds=10.0,
        ),
    )

    observer.observe(_frame(1, now), _snapshot(1, now, bounds))

    recovery_thread = observer._recovery_thread
    assert recovery_thread is not None
    recovery_thread.join(timeout=1.0)
    assert client.recoveries == 1
    assert client.targets == []
    observer.close()


def test_fresh_transport_receive_does_not_trigger_session_recovery() -> None:
    now = 10.0
    bounds = BoundingBox(0.2, 0.15, 0.6, 0.85)
    owner_context = OwnerContextState()
    owner_context.publish(_owner(7, now))
    client = FakeNativeClient(
        NativeTrackingStatus(
            connected=True,
            active=True,
            last_poll_at=now,
            last_subject_push_at=now,
            last_transport_rx_at=9.5,
        )
    )
    observer = NativeOwnerTrackingObserver(
        owner_context=owner_context,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(transport_rx_stale_seconds=3.0),
    )

    observer.observe(_frame(1, now), _snapshot(1, now, bounds))

    assert observer._recovery_thread is None
    assert client.recoveries == 0
    assert client.targets == [bounds]
    observer.close()


def test_missing_transport_receive_evidence_does_not_false_trigger_watchdog() -> None:
    now = 10.0
    bounds = BoundingBox(0.2, 0.15, 0.6, 0.85)
    owner_context = OwnerContextState()
    owner_context.publish(_owner(7, now))
    client = FakeNativeClient(
        NativeTrackingStatus(
            connected=True,
            active=False,
            last_transport_rx_at=None,
        )
    )
    observer = NativeOwnerTrackingObserver(
        owner_context=owner_context,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(transport_rx_stale_seconds=3.0),
    )

    observer.observe(_frame(1, now), _snapshot(1, now, bounds))

    assert observer._recovery_thread is None
    assert client.recoveries == 0
    assert client.targets == [bounds]
    observer.close()
