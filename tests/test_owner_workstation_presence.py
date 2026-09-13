from jarvis.computer.owner_presence import (
    OwnerWorkstationPresenceConfig,
    OwnerWorkstationPresenceController,
    WorkstationPresenceAction,
)
from jarvis.vision.owner_reacquisition import ReacquisitionState


class FakeWorkstation:
    def __init__(self, *, lock_result: bool = True) -> None:
        self.lock_result = lock_result
        self.lock_calls = 0

    def lock(self) -> bool:
        self.lock_calls += 1
        return self.lock_result


def _controller(workstation: FakeWorkstation) -> OwnerWorkstationPresenceController:
    return OwnerWorkstationPresenceController(
        workstation,
        OwnerWorkstationPresenceConfig(
            lock_after_loss_seconds=0.0,
            lock_retry_seconds=2.0,
        ),
    )


def _confirm_owner(controller: OwnerWorkstationPresenceController, now: float) -> None:
    controller.observe(
        now=now,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )


def _leave_and_lock(
    controller: OwnerWorkstationPresenceController,
    *,
    lost_at: float,
) -> WorkstationPresenceAction:
    return controller.observe(
        now=lost_at,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )


def test_does_not_lock_before_owner_was_ever_confirmed() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)

    action = controller.observe(
        now=10.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 0


def test_lock_pending_owner_gap_never_locks() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)

    action = controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.LOCK_PENDING,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 0


def test_native_failure_does_not_lock_while_live_owner_is_still_present() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)

    action = controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=True,
    )

    assert action is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 0


def test_confirmed_owner_absence_locks_immediately_and_exactly_once() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)

    action = _leave_and_lock(controller, lost_at=1.0)
    repeated = controller.observe(
        now=20.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.LOCK_WORKSTATION
    assert repeated is WorkstationPresenceAction.NONE
    assert workstation.lock_calls == 1
    assert controller.auto_lock_issued is True


def test_unbound_subject_does_not_complete_auto_lock_cycle() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)
    _leave_and_lock(controller, lost_at=1.0)

    action = controller.observe(
        now=8.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=False,
    )

    assert action is WorkstationPresenceAction.NONE
    assert controller.auto_lock_issued is True
    assert workstation.lock_calls == 1


def test_confirmed_owner_relock_after_windows_unlock_rearms_policy() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)
    _leave_and_lock(controller, lost_at=1.0)

    action = controller.observe(
        now=9.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )

    assert action is WorkstationPresenceAction.NONE
    assert controller.auto_lock_issued is False
    assert workstation.lock_calls == 1


def test_policy_can_auto_lock_again_after_normal_windows_unlock() -> None:
    workstation = FakeWorkstation()
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)

    first = _leave_and_lock(controller, lost_at=1.0)
    controller.observe(
        now=10.0,
        tracking_state=ReacquisitionState.LOCKED,
        owner_present=True,
    )
    second = _leave_and_lock(controller, lost_at=11.0)

    assert first is WorkstationPresenceAction.LOCK_WORKSTATION
    assert second is WorkstationPresenceAction.LOCK_WORKSTATION
    assert workstation.lock_calls == 2
    assert controller.auto_lock_issued is True


def test_failed_immediate_lock_retries_only_after_cooldown() -> None:
    workstation = FakeWorkstation(lock_result=False)
    controller = _controller(workstation)
    _confirm_owner(controller, 0.0)

    controller.observe(
        now=1.0,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=1.9,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )
    controller.observe(
        now=3.1,
        tracking_state=ReacquisitionState.REACQUIRING,
        owner_present=False,
    )

    assert workstation.lock_calls == 2
