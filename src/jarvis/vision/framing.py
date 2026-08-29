"""Head-first framing policy for an explicitly locked visual target."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.vision.head import HeadObservation
from jarvis.vision.models import TargetState


@dataclass(frozen=True, slots=True)
class FramingTarget:
    """Normalized anchor that the camera should compose around."""

    x: float
    y: float
    confidence: float
    source: str
    track_id: int

    def __post_init__(self) -> None:
        if not 0 <= self.x <= 1 or not 0 <= self.y <= 1:
            raise ValueError("framing target coordinates must be in [0, 1]")
        if not 0 <= self.confidence <= 1:
            raise ValueError("framing target confidence must be in [0, 1]")
        if self.source not in {"head", "body"}:
            raise ValueError("framing target source must be 'head' or 'body'")
        if self.track_id < 0:
            raise ValueError("track_id must be non-negative")


@dataclass(frozen=True, slots=True)
class HeadFirstFramingConfig:
    minimum_head_confidence: float = 0.5
    association_margin: float = 0.03
    maximum_head_vertical_fraction: float = 0.70
    body_fallback_vertical_fraction: float = 0.22
    allow_body_fallback: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_head_confidence <= 1:
            raise ValueError("minimum_head_confidence must be in [0, 1]")
        if not 0 <= self.association_margin <= 0.25:
            raise ValueError("association_margin must be in [0, 0.25]")
        if not 0 < self.maximum_head_vertical_fraction <= 1:
            raise ValueError("maximum_head_vertical_fraction must be in (0, 1]")
        if not 0 <= self.body_fallback_vertical_fraction <= 1:
            raise ValueError("body_fallback_vertical_fraction must be in [0, 1]")


class HeadFirstFramingPolicy:
    """Prefer a head linked to the locked body; fall back only to that body."""

    def __init__(self, config: HeadFirstFramingConfig | None = None) -> None:
        self.config = config or HeadFirstFramingConfig()

    def resolve(
        self,
        target: TargetState | None,
        heads: list[HeadObservation],
    ) -> FramingTarget | None:
        if target is None or target.track is None:
            return None

        track = target.track
        body = track.bounds
        body_height = body.bottom - body.top
        margin = self.config.association_margin
        maximum_head_y = body.top + (
            body_height * self.config.maximum_head_vertical_fraction
        )

        candidates = [
            head
            for head in heads
            if head.confidence >= self.config.minimum_head_confidence
            and body.left - margin <= head.bounds.center_x <= body.right + margin
            and body.top - margin <= head.bounds.center_y <= maximum_head_y + margin
        ]

        if candidates:
            expected_x = body.center_x
            expected_y = (
                body.top
                + body_height * self.config.body_fallback_vertical_fraction
            )
            head = min(
                candidates,
                key=lambda candidate: (
                    (candidate.bounds.center_x - expected_x) ** 2
                    + (candidate.bounds.center_y - expected_y) ** 2,
                    -candidate.confidence,
                ),
            )
            return FramingTarget(
                x=head.bounds.center_x,
                y=head.bounds.center_y,
                confidence=head.confidence,
                source="head",
                track_id=track.track_id,
            )

        if not self.config.allow_body_fallback:
            return None

        fallback_y = (
            body.top + body_height * self.config.body_fallback_vertical_fraction
        )
        return FramingTarget(
            x=body.center_x,
            y=fallback_y,
            confidence=track.confidence,
            source="body",
            track_id=track.track_id,
        )
