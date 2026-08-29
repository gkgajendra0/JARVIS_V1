from jarvis.vision import (
    BoundingBox,
    FollowConfig,
    FollowController,
    TargetManager,
    Track,
)


def _track(track_id: int, *, x: float, y: float, confidence: float = 0.9) -> Track:
    half = 0.05
    return Track(
        track_id=track_id,
        category="person",
        confidence=confidence,
        bounds=BoundingBox(x - half, y - half, x + half, y + half),
        first_seen_at=0.0,
        last_seen_at=1.0,
    )


def test_target_manager_never_switches_to_another_track() -> None:
    manager = TargetManager(lost_timeout_seconds=1.0)
    manager.lock(_track(1, x=0.5, y=0.5))

    state = manager.update([_track(2, x=0.2, y=0.5)], now=1.2)

    assert state is not None
    assert state.track_id == 1
    assert state.track is None


def test_target_manager_recovers_same_track_before_timeout() -> None:
    manager = TargetManager(lost_timeout_seconds=1.0)
    manager.lock(_track(4, x=0.5, y=0.5))
    manager.update([], now=2.0)

    state = manager.update([_track(4, x=0.7, y=0.5)], now=2.5)

    assert state is not None
    assert state.visible
    assert state.track is not None
    assert state.track.track_id == 4


def test_target_manager_clears_target_after_loss_timeout() -> None:
    manager = TargetManager(lost_timeout_seconds=0.5)
    manager.lock(_track(7, x=0.5, y=0.5))
    manager.update([], now=10.0)

    assert manager.update([], now=10.5) is None


def test_follow_controller_is_idle_inside_dead_zone() -> None:
    manager = TargetManager()
    target = manager.lock(_track(1, x=0.55, y=0.45))

    command = FollowController().command_for(target)

    assert command.is_idle


def test_follow_controller_moves_toward_off_center_target() -> None:
    manager = TargetManager()
    target = manager.lock(_track(1, x=0.8, y=0.2))

    command = FollowController().command_for(target)

    assert command.pan > 0
    assert command.tilt < 0


def test_follow_controller_clamps_large_error() -> None:
    manager = TargetManager()
    target = manager.lock(_track(1, x=0.94, y=0.5))
    controller = FollowController(FollowConfig(gain=10.0, max_command=0.2))

    command = controller.command_for(target)

    assert command.pan == 0.2


def test_follow_controller_stops_for_missing_or_low_confidence_target() -> None:
    manager = TargetManager(lost_timeout_seconds=1.0)
    manager.lock(_track(1, x=0.9, y=0.5))
    missing = manager.update([], now=2.0)
    controller = FollowController()

    assert controller.command_for(missing).is_idle

    low = manager.lock(_track(1, x=0.9, y=0.5, confidence=0.2))
    assert controller.command_for(low).is_idle


def test_bounding_box_rejects_invalid_coordinates() -> None:
    try:
        BoundingBox(0.8, 0.1, 0.2, 0.9)
    except ValueError as error:
        assert "left" in str(error)
    else:
        raise AssertionError("invalid bounding box was accepted")
