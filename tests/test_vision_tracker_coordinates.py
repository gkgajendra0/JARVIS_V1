from __future__ import annotations

import numpy as np

from jarvis.vision.models import BoundingBox, Detection
from jarvis.vision.tracker import BoTSORTAdapter


class _FakeExternalDetections:
    def __init__(self, *, xyxy, confidence):
        self.xyxy = np.asarray(xyxy)
        self.confidence = np.asarray(confidence)
        self.tracker_id = None


class _RecordingBoTSORT:
    def __init__(self, **kwargs):
        self.received_xyxy = None

    def update(self, detections, *, frame, timestamp):
        del frame, timestamp
        self.received_xyxy = np.asarray(detections.xyxy).copy()
        output = _FakeExternalDetections(
            xyxy=detections.xyxy,
            confidence=detections.confidence,
        )
        output.tracker_id = np.array([11], dtype=int)
        return output


def test_botsort_uses_pixel_space_and_returns_normalized_jarvis_bounds():
    tracker = _RecordingBoTSORT()
    adapter = BoTSORTAdapter(
        tracker_factory=lambda **_: tracker,
        detections_factory=_FakeExternalDetections,
    )
    detection = Detection(
        category="person",
        confidence=0.92,
        bounds=BoundingBox(0.10, 0.20, 0.40, 0.80),
        frame_id=1,
        observed_at=10.0,
    )
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    track = adapter.update([detection], now=10.0, frame=frame)[0]

    assert tracker.received_xyxy is not None
    np.testing.assert_allclose(
        tracker.received_xyxy,
        np.array([[128.0, 144.0, 512.0, 576.0]], dtype=np.float32),
    )
    assert track.bounds == BoundingBox(0.10, 0.20, 0.40, 0.80)
