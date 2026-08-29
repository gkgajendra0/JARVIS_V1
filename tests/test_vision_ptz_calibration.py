from __future__ import annotations

from jarvis.vision.models import FollowCommand
from jarvis.vision.ptz import DuvcPtzConfig, DuvcPtzController, PtzAxisRange


class _Backend:
    def __init__(self) -> None:
        self.values = {"pan": 50, "tilt": 0}
        self.writes: list[tuple[str, int]] = []

    def get_axis_range(self, axis: str) -> PtzAxisRange:
        if axis == "pan":
            return PtzAxisRange(-35, 215, 1, 0)
        return PtzAxisRange(-90, 90, 1, 0)

    def get_axis_value(self, axis: str) -> int:
        return self.values[axis]

    def set_axis_value(self, axis: str, value: int) -> None:
        self.values[axis] = value
        self.writes.append((axis, value))

    def close(self) -> None:
        pass


def test_positive_pan_scale_can_be_stronger_than_negative_pan_scale() -> None:
    config = DuvcPtzConfig(
        pan_step_fraction=0.02,
        tilt_step_fraction=0.015,
        pan_negative_scale=1.25,
        pan_positive_scale=1.75,
    )

    right_backend = _Backend()
    right = DuvcPtzController(config, backend=right_backend)
    right.move(FollowCommand(pan=0.4))

    left_backend = _Backend()
    left = DuvcPtzController(config, backend=left_backend)
    left.move(FollowCommand(pan=-0.4))

    right_delta = right_backend.values["pan"] - 50
    left_delta = 50 - left_backend.values["pan"]

    assert right_delta > left_delta > 0
