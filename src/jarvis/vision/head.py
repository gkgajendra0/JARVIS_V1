"""Provider-neutral head/face detection boundary for JARVIS vision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """Normalized image point in the inclusive range [0, 1]."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not 0 <= self.x <= 1 or not 0 <= self.y <= 1:
            raise ValueError("normalized point coordinates must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class HeadObservation:
    """Canonical face/head evidence independent of a detector SDK."""

    confidence: float
    bounds: BoundingBox
    frame_id: int
    observed_at: float
    keypoints: tuple[NormalizedPoint, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("head confidence must be in [0, 1]")
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if self.observed_at < 0:
            raise ValueError("observed_at must be non-negative")


class HeadDetector(Protocol):
    """Detect visible human heads/faces in one captured frame."""

    def detect(self, frame: CapturedFrame) -> list[HeadObservation]: ...
