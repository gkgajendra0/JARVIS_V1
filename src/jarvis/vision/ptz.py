"""PTZ boundary and duvc-ctl adapter for the DJI Pocket 3 path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.vision.models import FollowCommand


@dataclass(frozen=True, slots=True)
class PtzAxisRange:
    minimum: int
    maximum: int
    step: int
    default: int

    def __post_init__(self) -> None:
        if self.minimum >= self.maximum:
            raise ValueError("PTZ range minimum must be less than maximum")
        if self.step <= 0:
            raise ValueError("PTZ range step must be positive")

    @property
    def span(self) -> int:
        return self.maximum - self.minimum

    def clamp_and_snap(self, value: float) -> int:
        clamped = max(self.minimum, min(self.maximum, value))
        steps = round((clamped - self.minimum) / self.step)
        return int(self.minimum + steps * self.step)


class PtzController(Protocol):
    def move(self, command: FollowCommand) -> None: ...

    def close(self) -> None: ...


class _DuvcBackend(Protocol):
    def get_axis_range(self, axis: str) -> PtzAxisRange: ...

    def get_axis_value(self, axis: str) -> int: ...

    def set_axis_value(self, axis: str, value: int) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DuvcPtzConfig:
    device_index: int = 0
    pan_step_fraction: float = 0.04
    tilt_step_fraction: float = 0.04

    def __post_init__(self) -> None:
        if self.device_index < 0:
            raise ValueError("device_index must be non-negative")
        for name in ("pan_step_fraction", "tilt_step_fraction"):
            value = getattr(self, name)
            if not 0 < value <= 0.25:
                raise ValueError(f"{name} must be in (0, 0.25]")


class DuvcPtzController:
    """Apply normalized JARVIS movement intents through duvc-ctl."""

    def __init__(
        self,
        config: DuvcPtzConfig | None = None,
        *,
        backend: _DuvcBackend | None = None,
    ) -> None:
        self.config = config or DuvcPtzConfig()
        self._backend = backend or _ResultApiDuvcBackend(self.config.device_index)
        self._pan_range = self._backend.get_axis_range("pan")
        self._tilt_range = self._backend.get_axis_range("tilt")

    @property
    def pan_range(self) -> PtzAxisRange:
        return self._pan_range

    @property
    def tilt_range(self) -> PtzAxisRange:
        return self._tilt_range

    def move(self, command: FollowCommand) -> None:
        if command.is_idle:
            return
        if command.pan != 0:
            self._move_axis(
                "pan",
                command.pan,
                self._pan_range,
                self.config.pan_step_fraction,
            )
        if command.tilt != 0:
            self._move_axis(
                "tilt",
                command.tilt,
                self._tilt_range,
                self.config.tilt_step_fraction,
            )

    def close(self) -> None:
        self._backend.close()

    def _move_axis(
        self,
        axis: str,
        normalized_command: float,
        axis_range: PtzAxisRange,
        step_fraction: float,
    ) -> None:
        current = self._backend.get_axis_value(axis)
        delta = normalized_command * axis_range.span * step_fraction
        target = axis_range.clamp_and_snap(current + delta)
        if target != current:
            self._backend.set_axis_value(axis, target)


class _ResultApiDuvcBackend:
    """Small wrapper around duvc-ctl 2.1.0's Result-based API."""

    def __init__(self, device_index: int) -> None:
        import duvc_ctl as duvc

        self._duvc = duvc
        result = duvc.open_camera(device_index)
        if not result.is_ok():
            raise RuntimeError(
                f"failed to open PTZ camera: {result.error().description()}"
            )
        self._camera = result.value()

    def get_axis_range(self, axis: str) -> PtzAxisRange:
        prop = self._property(axis)
        result = self._camera.get_range(prop)
        if not result.is_ok():
            raise RuntimeError(
                f"failed to query {axis} range: {result.error().description()}"
            )
        value = result.value()
        return PtzAxisRange(
            minimum=int(value.min),
            maximum=int(value.max),
            step=int(value.step),
            default=int(value.default_val),
        )

    def get_axis_value(self, axis: str) -> int:
        result = self._camera.get(self._property(axis))
        if not result.is_ok():
            raise RuntimeError(
                f"failed to read {axis}: {result.error().description()}"
            )
        return int(result.value().value)

    def set_axis_value(self, axis: str, value: int) -> None:
        result = self._camera.set(self._property(axis), int(value))
        if not result.is_ok():
            raise RuntimeError(
                f"failed to set {axis}: {result.error().description()}"
            )

    def close(self) -> None:
        close = getattr(self._camera, "close", None)
        if close is not None:
            close()

    def _property(self, axis: str):
        if axis == "pan":
            return self._duvc.CamProp.Pan
        if axis == "tilt":
            return self._duvc.CamProp.Tilt
        raise ValueError(f"unsupported PTZ axis: {axis}")
