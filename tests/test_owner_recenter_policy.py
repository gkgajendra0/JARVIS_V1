from jarvis.vision.models import BoundingBox
from jarvis.vision.owner_reacquisition import (
    NativeTrackingStatus,
    OwnerReacquisitionController,
    ReacquisitionAction,
    ReacquisitionConfig,
    ReacquisitionState,
)

OWNER_BOX = BoundingBox(left=0.30, top=0.20, right=0.60, bottom=0.80)


def native(*, active: bool, poll_at: float, push_at: float | None) -> NativeTrackingStatus:
    return NativeTrackingStatus(
        connected=True,
        active=active,
        last_poll_at=poll_at,
        last_subject_push_at=push_at,
    )


def test_confirmed_owner_loss_recenters_once_then_waits_for_return() -> None:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(
            recenter_after_loss_seconds=1.0,
            recenter_settle_seconds=0.75,
        )
    )
    controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=9.9,
        native=NativeTrackingStatus(connected=True, active=False),
    )
    locked = controller.step(
        now=10.4,
        owner_bounds=OWNER_BOX,
        owner_observed_at=10.3,
        native=native(active=True, poll_at=10.35, push_at=10.38),
    )
    assert locked.state is ReacquisitionState.LOCKED

    lost = controller.step(
        now=12.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=11.95, push_at=10.5),
    )
    assert lost.state is ReacquisitionState.REACQUIRING
    assert lost.action is ReacquisitionAction.NONE

    grace = controller.step(
        now=12.8,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=12.75, push_at=10.5),
    )
    assert grace.action is ReacquisitionAction.NONE

    recenter = controller.step(
        now=13.1,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=13.05, push_at=10.5),
    )
    assert recenter.action is ReacquisitionAction.RECENTER_GIMBAL
    assert recenter.reason == "confirmed_owner_loss_recenter"

    no_repeat = controller.step(
        now=14.2,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=14.15, push_at=10.5),
    )
    assert no_repeat.action is ReacquisitionAction.NONE


def test_owner_return_during_loss_grace_skips_recenter_and_relocks() -> None:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(
            recenter_after_loss_seconds=1.0,
            recenter_settle_seconds=0.75,
        )
    )
    controller.step(
        now=20.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=19.9,
        native=NativeTrackingStatus(connected=True, active=False),
    )
    controller.step(
        now=20.4,
        owner_bounds=OWNER_BOX,
        owner_observed_at=20.3,
        native=native(active=True, poll_at=20.35, push_at=20.38),
    )
    controller.step(
        now=22.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=21.95, push_at=20.5),
    )

    returned = controller.step(
        now=22.6,
        owner_bounds=OWNER_BOX,
        owner_observed_at=22.55,
        native=native(active=False, poll_at=22.55, push_at=20.5),
    )
    assert returned.state is ReacquisitionState.LOCK_PENDING
    assert returned.action is ReacquisitionAction.SET_OWNER_TARGET
    assert returned.reason == "owner_reacquired"
