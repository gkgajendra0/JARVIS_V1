from __future__ import annotations

from jarvis.vision.framing import HeadFirstFramingPolicy
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, TargetState, Track


def _track(bounds: BoundingBox) -> Track:
    return Track(
        track_id=11,
        category="person",
        confidence=0.95,
        bounds=bounds,
        first_seen_at=1.0,
        last_seen_at=1.0,
    )


def _head(bounds: BoundingBox) -> HeadObservation:
    return HeadObservation(
        confidence=0.95,
        bounds=bounds,
        frame_id=1,
        observed_at=1.0,
    )


def _target(track: Track) -> TargetState:
    return TargetState(track_id=track.track_id, track=track)


def test_association_accepts_head_partly_above_cropped_person_box() -> None:
    track = _track(BoundingBox(0.20, 0.38, 0.80, 0.95))
    head = _head(BoundingBox(0.42, 0.20, 0.58, 0.42))

    associated = HeadFirstFramingPolicy().associated_head(_target(track), [head])

    assert associated == head


def test_association_rejects_head_detached_above_person_box() -> None:
    track = _track(BoundingBox(0.20, 0.38, 0.80, 0.95))
    detached = _head(BoundingBox(0.42, 0.08, 0.58, 0.30))

    associated = HeadFirstFramingPolicy().associated_head(_target(track), [detached])

    assert associated is None


def test_association_rejects_head_in_lower_body_region() -> None:
    track = _track(BoundingBox(0.20, 0.10, 0.80, 0.90))
    too_low = _head(BoundingBox(0.42, 0.72, 0.58, 0.88))

    associated = HeadFirstFramingPolicy().associated_head(_target(track), [too_low])

    assert associated is None


def test_association_rejects_horizontally_unrelated_head() -> None:
    track = _track(BoundingBox(0.20, 0.10, 0.70, 0.95))
    unrelated = _head(BoundingBox(0.78, 0.14, 0.94, 0.34))

    associated = HeadFirstFramingPolicy().associated_head(_target(track), [unrelated])

    assert associated is None
