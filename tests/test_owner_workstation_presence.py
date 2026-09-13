from jarvis.computer.owner_presence import (
    OwnerWorkstationPresenceConfig,
    OwnerWorkstationPresenceController,
    WorkstationPresenceAction,
)
from jarvis.vision.owner_reacquisition import ReacquisitionState


class FakeWorkstation:
    def __init__(self, *, lock_result: bool = True, wake_result: bool = True) -> None:
        self.lock_result = lock_result
        self.wake_result = wake_result
        self.lock_calls = 0
        self.wake_calls = 0

    def lock(self) -> bool:
        self.lock_calls += 1
        return self.lock_result

    def wake_display(self) -> bool:
        self.wake_calls += 1
        return self.wake_result


def _controller(workstation: FakeWorkstation) -> OwnerWorkstationPresenceController:
    return OwnerWorkstationPresenceController(
        workstation,
        OwnerWorkstationPresenceConfig(
            lock_after_loss_seconds=5.0,
            lock_retry_seconds=2.0,
        ),
    )


def test_does_not_lock_before_owner_was_ever_confirmed() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)

    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    action = controller.observe(
        now=10.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 0


def test_short_owner_occlusion_never_locks() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=4.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=4.5,
        tracking_state=ReacquisitionState.LOCK_PENDING,
        owner_present=True,
    )

    assert workstation.lock_calls == 0


def test_native_failure_does_not_lock_while_live_owner_is_still_present() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=True,
    )
    action = controller.observe(
        now=20.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=True,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 0


def test_sustained_confirmed_owner_absence_locks_exactly_once() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    action = controller.observe(
        now=6.1,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    repeated = controller.observe(
        now=20.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.LOCK_WORKSTATION
    assert repeated is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 1
    assert controller.auto_lock_issued is True


def test_stranger_or_unbound_subject_never_wakes_after_auto_lock() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=6.1,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    action = controller.observe(
        now=8.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.wake_calls == 0


def test_confirmed_owner_return_wakes_once_after_jarvis_auto_lock() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=6.1,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    action = controller.observe(
        now=9.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    repeated = controller.observe(
        now=10.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )

    assert action is WorkstationPresenceAction.WAKE_DISPLAY
    assert repeated is WorkstationPresenceAction.NONE
    assert workstation.wake_calls == 1
    assert controller.auto_lock_issued is False


def test_failed_lock_retries_only_after_cooldown() -> None:
    workstation = FakeWorkstation(lock_result=False)
    controller = _controller(workstation)
    controller.observe(
        now=0.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    controller.observe(
        now=6.1,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=7.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=8.2,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert workstation.lock_calls == 2
