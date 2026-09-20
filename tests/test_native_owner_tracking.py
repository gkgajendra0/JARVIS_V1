import time

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
        self.recoveries = 0

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

    def recover_tracking_session(self) -> None:
        self.recoveries += 1
        self.connected = True
        self.native_status = NativeTrackingStatus(connected=True, active=False)

    def close(self) -> None:
        self.closed = True
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


def snapshot(
    frame_id: int,
    now: float,
    *tracks: Track,
    alive_track_ids: tuple[int, ...] = (),
) -> VisionSnapshot:
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=now,
        tracks=tuple(tracks),
        target=None,
        command=FollowCommand(),
        armed=False,
        alive_track_ids=alive_track_ids,
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


def test_observer_holds_authorized_track_through_transient_biometric_gap() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
    )
    bounds = BoundingBox(0.20, 0.15, 0.55, 0.85)

    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(
        frame(1, 10.0),
        snapshot(
            1,
            10.0,
            track(7, bounds, 10.0),
            alive_track_ids=(7,),
        ),
    )

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.4,
        last_subject_push_at=10.45,
    )
    owner.publish(live_owner(track_id=7, observed_at=10.5))
    observer.observe(
        frame(2, 10.5),
        snapshot(
            2,
            10.5,
            track(7, bounds, 10.5),
            alive_track_ids=(7,),
        ),
    )
    assert observer.controller.state is ReacquisitionState.LOCKED

    # Face/head evidence can age out while the exact already-authorized tracker ID
    # remains alive inside the tracker's bounded lost-track window.
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=12.95,
        last_subject_push_at=12.95,
    )
    observer.observe(
        frame(3, 13.0),
        snapshot(3, 13.0, alive_track_ids=(7,)),
    )
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert client.clears == 0
    assert client.recenters == 0

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=15.95,
        last_subject_push_at=15.95,
    )
    observer.observe(
        frame(4, 16.0),
        snapshot(4, 16.0, alive_track_ids=(7,)),
    )
    assert observer.controller.state is ReacquisitionState.LOCKED
    assert client.clears == 0
    assert client.recenters == 0

    # Once the bound visual track really expires, native tracking alone cannot
    # preserve OWNER identity. Start a fresh bounded absence confirmation window.
    owner.invalidate("owner_track_expired")
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=16.05,
        last_subject_push_at=16.05,
    )
    observer.observe(frame(5, 16.1), snapshot(5, 16.1))
    assert observer.controller.state is ReacquisitionState.LOCKED

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=18.15,
        last_subject_push_at=18.15,
    )
    observer.observe(frame(6, 18.2), snapshot(6, 18.2))
    assert observer.controller.state is ReacquisitionState.REACQUIRING
    assert client.recenters == 0

    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=19.25,
        last_subject_push_at=19.25,
    )
    observer.observe(frame(7, 19.3), snapshot(7, 19.3))
    assert client.clears == 1
    assert client.recenters == 1
    observer.close()


def test_observer_recenters_after_confirmed_owner_loss() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(owner_context=owner, client=client)  # type: ignore[arg-type]
    bounds = BoundingBox(0.20, 0.15, 0.55, 0.85)

    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(frame(1, 10.0), snapshot(1, 10.0, track(7, bounds, 10.0)))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.4,
        last_subject_push_at=10.45,
    )
    owner.publish(live_owner(track_id=7, observed_at=10.5))
    observer.observe(frame(2, 10.5), snapshot(2, 10.5, track(7, bounds, 10.5)))
    assert observer.wait_for_startup_lock(0.001) is True
    assert observer.controller.state is ReacquisitionState.LOCKED

    owner.invalidate("owner_left_frame")
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=13.0,
        last_subject_push_at=11.0,
    )
    observer.observe(frame(3, 13.0), snapshot(3, 13.0))
    assert observer.controller.state is ReacquisitionState.REACQUIRING
    assert client.recenters == 0

    observer.observe(frame(4, 14.1), snapshot(4, 14.1))
    assert client.clears == 1
    assert client.recenters == 1


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


def test_tracking_config_rejects_invalid_recovery_policy() -> None:
    with pytest.raises(ValueError, match="target_attempts_before_session_recovery"):
        NativeOwnerTrackingConfig(target_attempts_before_session_recovery=0)
    with pytest.raises(ValueError, match="session_recovery_cooldown_seconds"):
        NativeOwnerTrackingConfig(session_recovery_cooldown_seconds=0.0)


def test_observer_rebuilds_session_after_bounded_unconfirmed_target_attempts() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(
            target_attempts_before_session_recovery=1,
            session_recovery_cooldown_seconds=10.0,
        ),
    )
    bounds = BoundingBox(0.2, 0.15, 0.6, 0.85)

    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(
        frame(1, 10.0),
        snapshot(1, 10.0, track(7, bounds, 10.0)),
    )
    assert client.targets == [bounds]

    # A fresh target gets the controller's full native-lock confirmation window.
    owner.publish(live_owner(track_id=7, observed_at=12.0))
    observer.observe(
        frame(2, 12.0),
        snapshot(2, 12.0, track(7, bounds, 12.0)),
    )
    assert observer._recovery_thread is None
    assert client.recoveries == 0

    # Once LOCK_PENDING times out, the next resend opportunity is replaced by one
    # bounded session rebuild instead of blindly sending another A6.
    owner.publish(live_owner(track_id=7, observed_at=13.0))
    observer.observe(
        frame(3, 13.0),
        snapshot(3, 13.0, track(7, bounds, 13.0)),
    )
    recovery_thread = observer._recovery_thread
    assert recovery_thread is not None
    recovery_thread.join(timeout=1.0)
    assert client.recoveries == 1

    owner.publish(live_owner(track_id=7, observed_at=13.1))
    observer.observe(
        frame(4, 13.1),
        snapshot(4, 13.1, track(7, bounds, 13.1)),
    )
    assert observer._target_attempts_without_native_lock <= 1
    observer.close()


def test_stale_native_active_does_not_prevent_bounded_session_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(
            target_attempts_before_session_recovery=3,
            session_recovery_cooldown_seconds=10.0,
        ),
    )
    bounds = BoundingBox(0.2, 0.15, 0.6, 0.85)

    def timed_out_target(target: BoundingBox) -> bool:
        client.targets.append(target)
        return False

    monkeypatch.setattr(client, "set_target", timed_out_target)

    for frame_id, now in enumerate((10.0, 13.0, 16.0, 19.0), start=1):
        client.native_status = NativeTrackingStatus(
            connected=True,
            active=True,
            last_poll_at=now,
            last_subject_push_at=1.0,
        )
        owner.publish(live_owner(track_id=7, observed_at=now))
        observer.observe(
            frame(frame_id, now),
            snapshot(frame_id, now, track(7, bounds, now)),
        )

    recovery_thread = observer._recovery_thread
    assert recovery_thread is not None
    recovery_thread.join(timeout=1.0)
    assert client.recoveries == 1
    assert len(client.targets) == 3
    observer.close()
