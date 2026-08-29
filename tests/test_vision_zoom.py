from __future__ import annotations

from jarvis.vision.follow import ZoomConfig, ZoomController
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.ptz import DuvcPtzConfig, DuvcPtzController, PtzAxisRange


def _target(*, body_height: float, confidence: float = 0.95) -> TargetState:
    top = 0.2
    track = Track(
        track_id=4,
        category="person",
        confidence=confidence,
        bounds=BoundingBox(0.3, top, 0.7, top + body_height),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )
    return TargetState(track_id=4, track=track)


def test_zoom_controller_zooms_in_far_target_and_out_near_target() -> None:
    controller = ZoomController(
        ZoomConfig(
            desired_body_height=0.56,
            dead_zone=0.08,
            gain=1.4,
            max_command=0.30,
        )
    )

    assert controller.command_for(_target(body_height=0.30)) > 0
    assert controller.command_for(_target(body_height=0.55)) == 0
    assert controller.command_for(_target(body_height=0.75)) < 0


class _ZoomBackend:
    def __init__(self) -> None:
        self.values = {"pan": 0, "tilt": 0, "zoom": 100}
        self.writes: list[tuple[str, int]] = []

    def get_axis_range(self, axis: str) -> PtzAxisRange:
        if axis == "pan":
            return PtzAxisRange(-35, 215, 1, 0)
        if axis == "tilt":
            return PtzAxisRange(-90, 90, 1, 0)
        return PtzAxisRange(100, 400, 1, 100)

    def get_axis_value(self, axis: str) -> int:
        return self.values[axis]

    def set_axis_value(self, axis: str, value: int) -> None:
        self.values[axis] = value
        self.writes.append((axis, value))

    def close(self) -> None:
        pass


def test_pocket3_zoom_is_bounded_to_safe_fraction() -> None:
    backend = _ZoomBackend()
    controller = DuvcPtzController(
        DuvcPtzConfig(
            zoom_step_fraction=0.25,
            zoom_max_fraction=0.50,
        ),
        backend=backend,
    )

    for _ in range(20):
        controller.move(FollowCommand(zoom=1.0))

    assert backend.values["zoom"] == 250
    assert all(axis == "zoom" for axis, _ in backend.writes)
