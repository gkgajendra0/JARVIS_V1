"""Bounded movement policies for keeping one visual target framed."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.vision.framing import FramingTarget
from jarvis.vision.models import FollowCommand, TargetState


@dataclass(frozen=True, slots=True)
class FollowConfig:
    horizontal_dead_zone: float = 0.12
    vertical_dead_zone: float = 0.12
    gain: float = 1.5
    max_command: float = 0.35
    minimum_confidence: float = 0.5
    desired_x: float = 0.5
    desired_y: float = 0.5

    def __post_init__(self) -> None:
        for name in ("horizontal_dead_zone", "vertical_dead_zone"):
            value = getattr(self, name)
            if not 0 <= value < 0.5:
                raise ValueError(f"{name} must be in [0, 0.5)")
        if self.gain <= 0:
            raise ValueError("gain must be positive")
        if not 0 < self.max_command <= 1:
            raise ValueError("max_command must be in (0, 1]")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be in [0, 1]")
        if not 0 <= self.desired_x <= 1:
            raise ValueError("desired_x must be in [0, 1]")
        if not 0 <= self.desired_y <= 1:
            raise ValueError("desired_y must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ZoomConfig:
    """Keep the locked body's apparent height inside a comfortable framing band."""

    desired_body_height: float = 0.56
    dead_zone: float = 0.08
    gain: float = 1.4
    max_command: float = 0.30
    minimum_confidence: float = 0.5

    def __post_init__(self) -> None:
        if not 0 < self.desired_body_height <= 1:
            raise ValueError("desired_body_height must be in (0, 1]")
        if not 0 <= self.dead_zone < 0.5:
            raise ValueError("dead_zone must be in [0, 0.5)")
        if self.gain <= 0:
            raise ValueError("gain must be positive")
        if not 0 < self.max_command <= 1:
            raise ValueError("max_command must be in (0, 1]")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be in [0, 1]")


class FollowController:
    """Convert target geometry into normalized, bounded pan/tilt intent."""

    def __init__(self, config: FollowConfig | None = None) -> None:
        self.config = config or FollowConfig()

    def command_for(self, target: TargetState | None) -> FollowCommand:
        if target is None or target.track is None:
            return FollowCommand()
        if target.track.confidence < self.config.minimum_confidence:
            return FollowCommand()

        return self._command_for_point(
            x=target.track.bounds.center_x,
            y=target.track.bounds.center_y,
        )

    def command_for_framing_target(
        self,
        target: FramingTarget | None,
    ) -> FollowCommand:
        if target is None or target.confidence < self.config.minimum_confidence:
            return FollowCommand()
        return self._command_for_point(x=target.x, y=target.y)

    def _command_for_point(self, *, x: float, y: float) -> FollowCommand:
        horizontal_error = x - self.config.desired_x
        # Image-space Y increases downward, while the Pocket 3's positive tilt
        # direction physically moves the camera upward. Invert the vertical error
        # so movement reduces image-space error instead of amplifying it.
        vertical_error = self.config.desired_y - y

        pan = self._axis_command(horizontal_error, self.config.horizontal_dead_zone)
        tilt = self._axis_command(vertical_error, self.config.vertical_dead_zone)
        return FollowCommand(pan=pan, tilt=tilt)

    def _axis_command(self, error: float, dead_zone: float) -> float:
        if abs(error) <= dead_zone:
            return 0.0
        raw = error * self.config.gain
        limit = self.config.max_command
        return max(-limit, min(limit, raw))


class ZoomController:
    """Generate conservative adaptive zoom from the locked body track only."""

    def __init__(self, config: ZoomConfig | None = None) -> None:
        self.config = config or ZoomConfig()

    def command_for(self, target: TargetState | None) -> float:
        if target is None or target.track is None:
            return 0.0
        if target.track.confidence < self.config.minimum_confidence:
            return 0.0

        error = self.config.desired_body_height - target.track.bounds.height
        if abs(error) <= self.config.dead_zone:
            return 0.0
        raw = error * self.config.gain
        limit = self.config.max_command
        return max(-limit, min(limit, raw))
