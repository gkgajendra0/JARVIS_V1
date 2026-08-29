from __future__ import annotations

import numpy as np

from jarvis.vision.framing import FramingTarget
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.observer import render_snapshot
from jarvis.vision.runtime import VisionSnapshot


def test_render_snapshot_preserves_frame_shape_and_draws_state() -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    track = Track(
        track_id=7,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.2, 0.1, 0.8, 0.9),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )
    head = HeadObservation(
        confidence=0.9,
        bounds=BoundingBox(0.4, 0.15, 0.6, 0.35),
        frame_id=1,
        observed_at=1.0,
    )
    snapshot = VisionSnapshot(
        frame_id=1,
        captured_at=1.0,
        tracks=(track,),
        target=TargetState(track_id=7, track=track),
        command=FollowCommand(pan=0.2, tilt=-0.1, zoom=0.15),
        armed=True,
        detector_persons=2,
        heads=(head,),
        framing_target=FramingTarget(
            x=0.5,
            y=0.25,
            confidence=0.9,
            source="head",
            track_id=7,
        ),
    )

    rendered = render_snapshot(image, snapshot)

    assert rendered.shape == image.shape
    assert np.any(rendered != image)
