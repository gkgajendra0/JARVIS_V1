from jarvis.vision.owner_reacquisition import (
    NativeTrackingStatus,
    OwnerReacquisitionController,
    ReacquisitionAction,
    ReacquisitionConfig,
    ReacquisitionState,
)
from jarvis.vision.models import BoundingBox


OWNER_BOX = BoundingBox(left=0.30, top=0.20, right=0.60, bottom=0.80)
RETURN_BOX = BoundingBox(left=0.55, top=0.20, right=0.85, bottom=0.82)


def native(
    *,
    connected: bool = True,
    active: bool = False,
    poll_at: float | None = None,
    push_at: float | None = None,
) -> NativeTrackingStatus:
    return NativeTrackingStatus(
        connected=connected,
        active=active,
        last_poll_at=poll_at,
        last_subject_push_at=push_at,
    )


def test_initial_owner_candidate_sends_one_target_then_waits_for_lock() -> None:
    controller = OwnerReacquisitionController()

    first = controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=9.9,
        native=native(),
    )
    assert first.state is ReacquisitionState.LOCK_PENDING
    assert first.action is ReacquisitionAction.SET_OWNER_TARGET
    assert first.bounds == OWNER_BOX

    repeated = controller.step(
        now=10.2,
        owner_bounds=OWNER_BOX,
        owner_observed_at=10.1,
        native=native(),
    )
    assert repeated.state is ReacquisitionState.LOCK_PENDING
    assert repeated.action is ReacquisitionAction.NONE


def test_native_subject_push_confirms_lock_without_repeated_a6() -> None:
    controller = OwnerReacquisitionController()
    controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=9.9,
        native=native(),
    )

    locked = controller.step(
        now=10.4,
        owner_bounds=OWNER_BOX,
        owner_observed_at=10.3,
        native=native(push_at=10.35),
    )
    assert locked.state is ReacquisitionState.LOCKED
    assert locked.action is ReacquisitionAction.NONE


def test_missing_push_alone_does_not_false_trigger_reacquisition() -> None:
    controller = OwnerReacquisitionController()
    controller.step(
        now=1.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=0.9,
        native=native(),
    )
    controller.step(
        now=1.2,
        owner_bounds=OWNER_BOX,
        owner_observed_at=1.1,
        native=native(active=True, poll_at=1.15, push_at=1.1),
    )

    waiting = controller.step(
        now=3.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=1.15, push_at=1.1),
    )
    assert waiting.state is ReacquisitionState.LOCKED
    assert waiting.reason == "awaiting_native_loss_confirmation"


def test_room_scenario_reacquires_only_when_owner_returns() -> None:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(
            owner_evidence_max_age_seconds=2.0,
            subject_push_stale_seconds=1.25,
            lock_pending_timeout_seconds=2.5,
            resend_cooldown_seconds=1.0,
        )
    )

    # GK is seen, then DJI confirms a healthy native lock.
    first = controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=9.9,
        native=native(),
    )
    assert first.action is ReacquisitionAction.SET_OWNER_TARGET
    locked = controller.step(
        now=10.4,
        owner_bounds=OWNER_BOX,
        owner_observed_at=10.3,
        native=native(active=True, poll_at=10.35, push_at=10.38),
    )
    assert locked.state is ReacquisitionState.LOCKED

    # GK leaves. A fresh negative A5 is the explicit native-loss confirmation.
    lost = controller.step(
        now=13.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=12.95, push_at=11.0),
    )
    assert lost.state is ReacquisitionState.REACQUIRING
    assert lost.action is ReacquisitionAction.NONE

    # A stranger/non-owner may be visible, but there is no live OWNER box.
    stranger = controller.step(
        now=14.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=13.9),
    )
    assert stranger.state is ReacquisitionState.REACQUIRING
    assert stranger.action is ReacquisitionAction.NONE

    # GK returns on a new visual track/location. Exactly one fresh A6 is requested.
    returned = controller.step(
        now=15.0,
        owner_bounds=RETURN_BOX,
        owner_observed_at=14.9,
        native=native(active=False, poll_at=14.9),
    )
    assert returned.state is ReacquisitionState.LOCK_PENDING
    assert returned.action is ReacquisitionAction.SET_OWNER_TARGET
    assert returned.bounds == RETURN_BOX
    assert returned.reason == "owner_reacquired"

    duplicate = controller.step(
        now=15.2,
        owner_bounds=RETURN_BOX,
        owner_observed_at=15.1,
        native=native(active=False, poll_at=15.1),
    )
    assert duplicate.action is ReacquisitionAction.NONE

    relocked = controller.step(
        now=15.5,
        owner_bounds=RETURN_BOX,
        owner_observed_at=15.4,
        native=native(active=True, poll_at=15.45, push_at=15.48),
    )
    assert relocked.state is ReacquisitionState.LOCKED


def test_stale_owner_evidence_never_triggers_a6() -> None:
    controller = OwnerReacquisitionController()
    decision = controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=7.0,
        native=native(),
    )
    assert decision.action is ReacquisitionAction.NONE
    assert decision.reason == "fresh_live_owner_not_visible"


def test_transport_loss_moves_locked_session_to_reacquiring() -> None:
    controller = OwnerReacquisitionController()
    controller.step(
        now=1.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=0.9,
        native=native(),
    )
    controller.step(
        now=1.2,
        owner_bounds=OWNER_BOX,
        owner_observed_at=1.1,
        native=native(active=True, push_at=1.19),
    )

    disconnected = controller.step(
        now=2.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=1.9,
        native=native(connected=False),
    )
    assert disconnected.state is ReacquisitionState.REACQUIRING
    assert disconnected.action is ReacquisitionAction.NONE
    assert disconnected.reason == "native_transport_unavailable"
