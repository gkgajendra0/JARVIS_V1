from jarvis.vision.models import BoundingBox
from jarvis.vision.owner_reacquisition import (
    NativeTrackingStatus,
    OwnerReacquisitionController,
    ReacquisitionAction,
    ReacquisitionConfig,
    ReacquisitionState,
)

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


def test_native_subject_push_confirms_authorized_owner_lock() -> None:
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
    assert locked.reason == "authorized_native_tracking_healthy"
    assert locked.owner_absence_confirmed is False


def test_short_owner_evidence_gap_does_not_false_trigger_reacquisition() -> None:
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
        now=2.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=1.95, push_at=1.9),
    )
    assert waiting.state is ReacquisitionState.LOCKED
    assert waiting.reason == "awaiting_owner_loss_confirmation"
    assert waiting.owner_absence_confirmed is False


def test_stale_subject_push_reacquires_without_claiming_owner_absence() -> None:
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

    lost = controller.step(
        now=3.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=2.95, push_at=1.1),
    )
    assert lost.state is ReacquisitionState.REACQUIRING
    assert lost.action is ReacquisitionAction.NONE
    assert lost.reason == "native_tracking_lost_reacquiring"
    assert lost.owner_absence_confirmed is False


def test_reacquiring_absence_can_confirm_after_native_loss() -> None:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(owner_evidence_max_age_seconds=2.0)
    )
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

    native_lost = controller.step(
        now=2.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=1.95, push_at=0.5),
    )
    assert native_lost.state is ReacquisitionState.REACQUIRING
    assert native_lost.owner_absence_confirmed is False

    confirmed = controller.step(
        now=4.1,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=4.0),
    )
    assert confirmed.state is ReacquisitionState.REACQUIRING
    assert confirmed.owner_absence_confirmed is True


def test_transient_reacquisition_gap_does_not_confirm_absence_if_owner_returns() -> (
    None
):
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(owner_evidence_max_age_seconds=2.0)
    )
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

    gap = controller.step(
        now=2.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=1.95, push_at=0.5),
    )
    assert gap.state is ReacquisitionState.REACQUIRING
    assert gap.owner_absence_confirmed is False

    returned = controller.step(
        now=2.8,
        owner_bounds=RETURN_BOX,
        owner_observed_at=2.7,
        native=native(active=False, poll_at=2.7),
    )
    assert returned.state is ReacquisitionState.LOCK_PENDING
    assert returned.action is ReacquisitionAction.SET_OWNER_TARGET
    assert returned.owner_absence_confirmed is False


def test_native_tracking_a_stranger_cannot_reauthorize_owner_lock() -> None:
    controller = OwnerReacquisitionController(
        ReacquisitionConfig(owner_evidence_max_age_seconds=2.0)
    )

    controller.step(
        now=10.0,
        owner_bounds=OWNER_BOX,
        owner_observed_at=9.9,
        native=native(),
    )
    locked = controller.step(
        now=10.3,
        owner_bounds=OWNER_BOX,
        owner_observed_at=10.2,
        native=native(active=True, poll_at=10.25, push_at=10.28),
    )
    assert locked.state is ReacquisitionState.LOCKED

    # GK leaves but DJI keeps producing healthy tracking pushes because it starts
    # following another visible person. Native tracking itself is not owner identity
    # evidence and cannot prevent OWNER-absence confirmation.
    confirming = controller.step(
        now=11.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=10.95, push_at=10.98),
    )
    assert confirming.state is ReacquisitionState.LOCKED
    assert confirming.reason == "awaiting_owner_loss_confirmation"
    assert confirming.owner_absence_confirmed is False

    lost = controller.step(
        now=13.1,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=13.05, push_at=13.08),
    )
    assert lost.state is ReacquisitionState.REACQUIRING
    assert lost.action is ReacquisitionAction.NONE
    assert lost.reason == "confirmed_owner_absence"
    assert lost.owner_absence_confirmed is True

    # Even with another fresh DJI subject push, REACQUIRING can never become
    # LOCKED until a fresh live OWNER causes a new A6 authorization.
    stranger_still_tracked = controller.step(
        now=13.4,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=13.35, push_at=13.38),
    )
    assert stranger_still_tracked.state is ReacquisitionState.REACQUIRING
    assert stranger_still_tracked.action is ReacquisitionAction.NONE
    assert stranger_still_tracked.owner_absence_confirmed is True


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

    # Native tracking can be lost before OWNER absence has been confirmed. That
    # requires reacquisition/recenter but must not yet authorize workstation lock.
    lost = controller.step(
        now=13.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=True, poll_at=12.95, push_at=11.0),
    )
    assert lost.state is ReacquisitionState.REACQUIRING
    assert lost.action is ReacquisitionAction.NONE
    assert lost.owner_absence_confirmed is False

    # A stranger/non-owner may be visible, but there is no live OWNER box.
    stranger = controller.step(
        now=14.0,
        owner_bounds=None,
        owner_observed_at=None,
        native=native(active=False, poll_at=13.9),
    )
    assert stranger.state is ReacquisitionState.REACQUIRING
    assert stranger.action is ReacquisitionAction.NONE
    assert stranger.owner_absence_confirmed is False

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
    assert returned.owner_absence_confirmed is False

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


def test_transport_loss_moves_locked_session_to_reacquiring_without_owner_absence() -> (
    None
):
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
    assert disconnected.reason == "native_tracking_lost_reacquiring"
    assert disconnected.owner_absence_confirmed is False
