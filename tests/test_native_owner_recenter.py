import numpy as np

from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox, FollowCommand, Track
from jarvis.vision.native_owner_tracking import NativeOwnerTrackingObserver
from jarvis.vision.owner_reacquisition import (
    NativeTrackingStatus,
    OwnerReacquisitionController,
    ReacquisitionConfig,
)
from jarvis.vision.runtime import VisionSnapshot


class FakeNativeClient:
    def __init__(self) -> None:
        self.connected = True
        self.native_status = NativeTrackingStatus(connected=True, active=False)
        self.targets: list[BoundingBox] = []
        self.clears = 0
        self.recenters = 0
        self.polls = 0

    def start(self) -> None:
        self.connected = True

    def status(self) -> NativeTrackingStatus:
        return self.native_status

    def poll_tracking(self) -> None:
        self.polls += 1

    def set_target(self, bounds: BoundingBox) -> bool:
        self.targets.append(bounds)
        return True

    def clear_target(self) -> None:
        self.clears += 1

    def recenter_gimbal(self) -> None:
        self.recenters += 1

    def close(self) -> None:
        self.connected = False


def live_owner(track_id: int, observed_at: float) -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id="session-1",
        visual_track_id=track_id,
        state=OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=observed_at,
        reason_codes=("test_live_owner",),
    )


def frame(frame_id: int, now: float) -> CapturedFrame:
    return CapturedFrame(
        frame_id=frame_id,
        captured_at=now,
        image=np.zeros((32, 32, 3), dtype=np.uint8),
    )


def track(track_id: int, bounds: BoundingBox, now: float) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=bounds,
        first_seen_at=max(0.0, now - 1.0),
        last_seen_at=now,
    )


def snapshot(frame_id: int, now: float, *tracks: Track) -> VisionSnapshot:
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=now,
        tracks=tuple(tracks),
        target=None,
        command=FollowCommand(),
        armed=False,
    )


def test_observer_recenters_once_then_reacquires_owner() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(
            recenter_after_loss_seconds=1.0,
            recenter_settle_seconds=0.75,
        )
    )
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,
        controller=controller,
    )

    first_box = BoundingBox(0.20, 0.15, 0.55, 0.85)
    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(
        frame(1, 10.0),
        snapshot(1, 10.0, track(7, first_box, 10.0)),
    )
    assert client.targets == [first_box]

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.4,
        last_subject_push_at=10.45,
    )
    owner.publish(live_owner(track_id=7, observed_at=10.5))
    observer.observe(
        frame(2, 10.5),
        snapshot(2, 10.5, track(7, first_box, 10.5)),
    )

    owner.invalidate("owner_left_frame")
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=12.0,
        last_subject_push_at=10.5,
    )
    observer.observe(frame(3, 12.0), snapshot(3, 12.0))
    assert client.clears == 0
    assert client.recenters == 0

    observer.observe(frame(4, 13.1), snapshot(4, 13.1))
    assert client.clears == 1
    assert client.recenters == 1

    observer.observe(frame(5, 13.3), snapshot(5, 13.3))
    assert client.clears == 1
    assert client.recenters == 1

    return_box = BoundingBox(0.55, 0.18, 0.88, 0.86)
    owner.publish(live_owner(track_id=22, observed_at=14.0))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=14.0,
        last_subject_push_at=10.5,
    )
    observer.observe(
        frame(6, 14.0),
        snapshot(6, 14.0, track(22, return_box, 14.0)),
    )
    assert client.targets == [first_box, return_box]
    assert client.clears == 1
    assert client.recenters == 1
