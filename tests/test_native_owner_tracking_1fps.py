import time

from jarvis.identity.owner_context import OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState
from jarvis.vision.native_owner_tracking import (
    NativeOwnerTrackingConfig,
    NativeOwnerTrackingObserver,
)
from jarvis.vision.owner_reacquisition import NativeTrackingStatus, ReacquisitionState


class _FakeNativeClient:
    connected = True

    def start(self) -> None:
        pass

    def status(self) -> NativeTrackingStatus:
        return NativeTrackingStatus(connected=True, active=False)

    def poll_tracking(self) -> None:
        pass

    def set_target(self, bounds) -> bool:
        return True

    def clear_target(self) -> None:
        pass

    def recenter_gimbal(self) -> None:
        pass

    def close(self) -> None:
        pass


def _fresh_owner() -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id="session-1",
        visual_track_id=7,
        state=OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=time.monotonic(),
        reason_codes=("test_live_owner",),
    )


def test_locked_state_throttles_only_with_fresh_and_current_owner() -> None:
    owner = OwnerContextState()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=_FakeNativeClient(),
        config=NativeOwnerTrackingConfig(
            searching_perception_fps=10.0,
            locked_perception_fps=1.0,
        ),
    )

    assert observer.perception_fps_hint() == 10.0

    observer.controller.state = ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 10.0

    owner.publish(_fresh_owner())
    assert observer.perception_fps_hint() == 10.0

    observer._owner_observed_in_latest_snapshot = True
    assert observer.perception_fps_hint() == 1.0

    observer._owner_observed_in_latest_snapshot = False
    assert observer.perception_fps_hint() == 10.0

    observer.controller.state = ReacquisitionState.REACQUIRING
    assert observer.perception_fps_hint() == 10.0
