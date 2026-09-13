from jarvis.identity.owner_context import OwnerContextState
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


def test_locked_state_can_throttle_perception_to_one_fps() -> None:
    observer = NativeOwnerTrackingObserver(
        owner_context=OwnerContextState(),
        client=_FakeNativeClient(),
        config=NativeOwnerTrackingConfig(
            searching_perception_fps=10.0,
            locked_perception_fps=1.0,
        ),
    )

    assert observer.perception_fps_hint() == 10.0

    observer.controller.state = ReacquisitionState.LOCKED
    assert observer.perception_fps_hint() == 1.0

    observer.controller.state = ReacquisitionState.REACQUIRING
    assert observer.perception_fps_hint() == 10.0
