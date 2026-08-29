from __future__ import annotations

import numpy as np

from jarvis.vision.models import BoundingBox, Detection
from jarvis.vision.tracker import OCSORTAdapter, OCSORTConfig


class _ExternalDetections:
    def __init__(self, *, xyxy, confidence):
        self.xyxy = np.asarray(xyxy)
        self.confidence = np.asarray(confidence)
        self.tracker_id = None


class _FakeIoU:
    pass


class _FakeStateEstimator:
    pass


class _FakeOCSORT:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.last_timestamp = None
        self.last_detections = None

    def update(self, detections, *, timestamp):
        self.last_timestamp = timestamp
        self.last_detections = detections
        output = _ExternalDetections(
            xyxy=detections.xyxy,
            confidence=detections.confidence,
        )
        output.tracker_id = np.array([12], dtype=int)
        return output


def test_ocsort_adapter_uses_fast_motion_configuration_and_timestamp() -> None:
    tracker = _FakeOCSORT()
    config = OCSORTConfig(
        lost_track_buffer=60,
        minimum_consecutive_frames=2,
        minimum_iou_threshold=-0.30,
        direction_consistency_weight=0.20,
        high_conf_det_threshold=0.40,
        delta_t=2,
    )
    adapter = OCSORTAdapter(
        config,
        tracker_factory=lambda **kwargs: (
            tracker.__dict__.update(kwargs=kwargs) or tracker
        ),
        detections_factory=_ExternalDetections,
        iou_factory=_FakeIoU,
        state_estimator_class=_FakeStateEstimator,
    )
    detection = Detection(
        category="person",
        confidence=0.75,
        bounds=BoundingBox(0.10, 0.20, 0.40, 0.90),
        frame_id=1,
        observed_at=5.0,
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    track = adapter.update([detection], now=5.25, frame=frame)[0]

    assert tracker.kwargs["lost_track_buffer"] == 60
    assert tracker.kwargs["minimum_iou_threshold"] == -0.30
    assert tracker.kwargs["high_conf_det_threshold"] == 0.40
    assert tracker.kwargs["delta_t"] == 2
    assert tracker.kwargs["state_estimator_class"] is _FakeStateEstimator
    assert isinstance(tracker.kwargs["iou"], _FakeIoU)
    assert tracker.last_timestamp == 5.25
    assert np.allclose(tracker.last_detections.xyxy[0], [20, 20, 80, 90])
    assert track.track_id == 12
    assert track.bounds == BoundingBox(0.10, 0.20, 0.40, 0.90)
