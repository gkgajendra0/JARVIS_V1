"""Provider-neutral domain models for JARVIS vision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Normalized left/top/right/bottom bounds in the inclusive range [0, 1]."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.right, self.bottom)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("bounding-box coordinates must be normalized to [0, 1]")
        if self.left >= self.right:
            raise ValueError("bounding-box left must be less than right")
        if self.top >= self.bottom:
            raise ValueError("bounding-box top must be less than bottom")

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class Detection:
    """Canonical detector output independent of any model/provider SDK."""

    category: str
    confidence: float
    bounds: BoundingBox
    frame_id: int
    observed_at: float

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("detection category must not be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("detection confidence must be in [0, 1]")
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if self.observed_at < 0:
            raise ValueError("observed_at must be non-negative")


@dataclass(frozen=True, slots=True)
class Track:
    """Canonical tracking state independent of tracker implementation."""

    track_id: int
    category: str
    confidence: float
    bounds: BoundingBox
    first_seen_at: float
    last_seen_at: float

    def __post_init__(self) -> None:
        if self.track_id < 0:
            raise ValueError("track_id must be non-negative")
        if not self.category.strip():
            raise ValueError("track category must not be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("track confidence must be in [0, 1]")
        if self.first_seen_at < 0 or self.last_seen_at < 0:
            raise ValueError("track timestamps must be non-negative")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at must not precede first_seen_at")


@dataclass(frozen=True, slots=True)
class TargetState:
    """JARVIS-owned truth for an explicitly locked visual target."""

    track_id: int
    track: Track | None
    missing_since: float | None = None

    @property
    def visible(self) -> bool:
        return self.track is not None


@dataclass(frozen=True, slots=True)
class FollowCommand:
    """Normalized PTZ movement intent, not device-specific control units."""

    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0

    def __post_init__(self) -> None:
        if not -1 <= self.pan <= 1:
            raise ValueError("pan command must be in [-1, 1]")
        if not -1 <= self.tilt <= 1:
            raise ValueError("tilt command must be in [-1, 1]")
        if not -1 <= self.zoom <= 1:
            raise ValueError("zoom command must be in [-1, 1]")

    @property
    def is_idle(self) -> bool:
        return self.pan == 0 and self.tilt == 0 and self.zoom == 0
