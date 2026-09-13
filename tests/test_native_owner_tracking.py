import time

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
from jarvis.vision.native_owner_tracking import (
    NativeOwnerTrackingConfig,
    NativeOwnerTrackingObserver,
)
from jarvis.vision.owner_reacquisition import NativeTrackingStatus, ReacquisitionState
from jarvis.vision.runtime import VisionSnapshot


class FakeNativeClient:
    def __init__(self) -> None:
        self.connected = True
        self.native_status = NativeTrackingStatus(connected=True, active=False)
        self.targets: list[BoundingBox] = []
        self.polls = 0
        self.closed = False
        self.clears = 0
        self.recenters = 0

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
        self.closed = True
        self.connected = False


class PresenceRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[ReacquisitionState, bool, bool]] = []

    def observe(
        self,
        *,
        now: float,
        tracking_state: ReacquisitionState,
        owner_present: bool,
        owner_absence_confirmed: bool = False,
    ) -> None:
        del now
        self.events.append(
            (tracking_state, owner_present, owner_absence_confirmed)
        )

    def reset(self) -> None:
        pass


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


def track(track_id: int, bounds: BoundingBox, now: float) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=bounds,
        first_seen_at=max(0.0, now - 1.0),
        last_seen_at=now,
    )


def frame(frame_id: int, now: float) -> CapturedFrame:
    return CapturedFrame(
        frame_id=frame_id,
        captured_at=now,
        image=np.zeros((32, 32, 3), dtype=np.uint8),
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


def test_observer_targets_confirmed_owner_and_reacquires_after_native_loss() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(owner_context=owner, client=client)  # type: ignore[arg-type]

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
    assert client.targets == [first_box]

    owner.invalidate("owner_left_frame")
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=13.0,
        last_subject_push_at=11.0,
    )
    observer.observe(frame(3, 13.0), snapshot(3, 13.0))
    assert client.targets == [first_box]

    return_box = BoundingBox(0.55, 0.18, 0.88, 0.86)
    owner.publish(live_owner(track_id=22, observed_at=15.0))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=15.0,
        last_subject_push_at=11.0,
    )
    observer.observe(
        frame(4, 15.0),
        snapshot(4, 15.0, track(22, return_box, 15.0)),
    )
    assert client.targets == [first_box, return_box]

    owner.publish(live_owner(track_id=22, observed_at=15.1))
    observer.observe(
        frame(5, 15.1),
        snapshot(5, 15.1, track(22, return_box, 15.1)),
    )
    assert client.targets == [first_box, return_box]

    observer.close()
    assert client.closed is True


def test_observer_never_targets_unconfirmed_visible_person() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(owner_context=owner, client=client)  # type: ignore[arg-type]

    stranger_box = BoundingBox(0.10, 0.10, 0.40, 0.80)
    observer.observe(
        frame(1, 5.0),
        snapshot(1, 5.0, track(99, stranger_box, 5.0)),
    )
    assert client.targets == []


def test_perception_hint_throttles_only_with_fresh_current_owner_lock() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(
            searching_perception_fps=10.0,
            locked_perception_fps=2.0,
        ),
    )

    assert observer.perception_fps_hint() == 10.0

    observer.controller.state = ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 10.0

    owner.publish(live_owner(track_id=7, observed_at=time.monotonic()))
    assert observer.perception_fps_hint() == 10.0

    observer._owner_observed_in_latest_snapshot = True
    assert observer.perception_fps_hint() == 2.0

    observer._owner_observed_in_latest_snapshot = False
    assert observer.perception_fps_hint() == 10.0

    observer.controller.state = ReacquisitionState.REACQUIRING
    assert observer.perception_fps_hint() == 10.0


def test_repeated_short_owner_association_misses_never_confirm_departure() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    presence = PresenceRecorder()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(
            searching_perception_fps=10.0,
            locked_perception_fps=1.0,
        ),
        owner_presence_observer=presence,
    )
    box = BoundingBox(0.20, 0.15, 0.55, 0.85)

    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(frame(1, 10.0), snapshot(1, 10.0, track(7, box, 10.0)))
    assert observer.controller.state is ReacquisitionState.LOCK_PENDING

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.2,
        last_subject_push_at=10.2,
    )
    owner.publish(live_owner(track_id=7, observed_at=10.2))
    observer.observe(frame(2, 10.2), snapshot(2, 10.2, track(7, box, 10.2)))
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 1.0

    observer.observe(frame(3, 10.6), snapshot(3, 10.6))
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 10.0

    owner.publish(live_owner(track_id=7, observed_at=10.8))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.8,
        last_subject_push_at=10.8,
    )
    observer.observe(frame(4, 10.8), snapshot(4, 10.8, track(7, box, 10.8)))
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 1.0

    observer.observe(frame(5, 11.1), snapshot(5, 11.1))
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 10.0

    owner.publish(live_owner(track_id=7, observed_at=11.3))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=11.3,
        last_subject_push_at=11.3,
    )
    observer.observe(frame(6, 11.3), snapshot(6, 11.3, track(7, box, 11.3)))

    assert observer.controller.state is ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 1.0
    assert all(not confirmed for _, _, confirmed in presence.events)
