from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.detector import RFDetrNanoDetector
from jarvis.vision.follow import FollowController
from jarvis.vision.models import BoundingBox, Detection, FollowCommand, Track
from jarvis.vision.ptz import DuvcPtzController, PtzAxisRange
from jarvis.vision.runtime import VisionRuntime, VisionRuntimeConfig
from jarvis.vision.targeting import TargetManager
from jarvis.vision.tracker import BoTSORTAdapter, ByteTrackAdapter


class FakeRFModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inference_kwargs = None

    def inference(self, **kwargs):
        self.inference_kwargs = kwargs

    def predict(self, image, threshold, include_source_image=True):
        assert image.shape == (100, 200, 3)
        assert threshold == 0.1
        assert include_source_image is False
        return SimpleNamespace(
            class_id=np.array([1, 2]),
            confidence=np.array([0.9, 0.8]),
            xyxy=np.array([[20, 10, 100, 90], [0, 0, 20, 20]], dtype=float),
        )


def identity_suppressor(boxes, confidences, threshold):
    assert threshold == 0.98
    return boxes, confidences


def test_rf_detr_adapter_filters_person_and_normalizes_box():
    model = FakeRFModel()
    detector = RFDetrNanoDetector(
        model_factory=lambda **_: model,
        duplicate_suppressor=identity_suppressor,
    )
    frame = CapturedFrame(
        frame_id=7,
        captured_at=12.5,
        image=np.zeros((100, 200, 3), dtype=np.uint8),
    )

    detections = detector.detect(frame)

    assert len(detections) == 1
    detection = detections[0]
    assert detection.category == "person"
    assert detection.confidence == 0.9
    assert detection.bounds == BoundingBox(0.1, 0.1, 0.5, 0.9)
    assert detection.frame_id == 7
    assert detection.observed_at == 12.5


def test_rf_detr_adapter_uses_duplicate_suppressor_for_person_candidates():
    class DuplicateRFModel:
        def inference(self, **kwargs):
            pass

        def predict(self, image, threshold, include_source_image=True):
            assert include_source_image is False
            return SimpleNamespace(
                class_id=np.array([1, 1]),
                confidence=np.array([0.95, 0.53]),
                xyxy=np.array([[20, 10, 180, 95], [40, 30, 100, 80]], dtype=float),
            )

    def keep_highest(boxes, confidences, threshold):
        assert len(boxes) == 2
        assert threshold == 0.98
        index = int(np.argmax(confidences))
        return boxes[[index]], confidences[[index]]

    detector = RFDetrNanoDetector(
        model_factory=lambda **_: DuplicateRFModel(),
        duplicate_suppressor=keep_highest,
    )
    frame = CapturedFrame(
        frame_id=8,
        captured_at=13.0,
        image=np.zeros((100, 200, 3), dtype=np.uint8),
    )

    detections = detector.detect(frame)

    assert len(detections) == 1
    assert detections[0].confidence == 0.95
    assert detections[0].bounds == BoundingBox(0.1, 0.1, 0.9, 0.95)


class FakeExternalDetections:
    def __init__(self, *, xyxy, confidence):
        self.xyxy = np.asarray(xyxy)
        self.confidence = np.asarray(confidence)
        self.tracker_id = None


class FakeByteTracker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def update(self, detections, timestamp):
        output = FakeExternalDetections(
            xyxy=detections.xyxy,
            confidence=detections.confidence,
        )
        output.tracker_id = np.array([4], dtype=int)
        return output


def test_bytetrack_adapter_preserves_first_seen_timestamp():
    adapter = ByteTrackAdapter(
        tracker_factory=FakeByteTracker,
        detections_factory=FakeExternalDetections,
    )
    detection = Detection(
        category="person",
        confidence=0.92,
        bounds=BoundingBox(0.1, 0.2, 0.4, 0.8),
        frame_id=1,
        observed_at=10.0,
    )

    first = adapter.update([detection], now=10.0)
    second = adapter.update([detection], now=11.0)

    assert first[0].first_seen_at == 10.0
    assert first[0].last_seen_at == 10.0
    assert second[0].first_seen_at == 10.0
    assert second[0].last_seen_at == 11.0


class FakeBoTTracker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def update(self, detections, frame):
        output = FakeExternalDetections(
            xyxy=detections.xyxy,
            confidence=detections.confidence,
        )
        output.tracker_id = np.array([5], dtype=int)
        return output


def test_botsort_adapter_passes_frame_and_preserves_first_seen_timestamp():
    adapter = BoTSORTAdapter(
        tracker_factory=FakeBoTTracker,
        detections_factory=FakeExternalDetections,
    )
    detection = Detection(
        category="person",
        confidence=0.91,
        bounds=BoundingBox(0.1, 0.2, 0.4, 0.8),
        frame_id=1,
        observed_at=10.0,
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    first = adapter.update([detection], now=10.0, frame=frame)
    second = adapter.update([detection], now=11.0, frame=frame)

    assert first[0].first_seen_at == 10.0
    assert first[0].last_seen_at == 10.0
    assert second[0].first_seen_at == 10.0
    assert second[0].last_seen_at == 11.0


def test_follow_controller_uses_horizontal_and_vertical_errors():
    controller = FollowController()
    target = SimpleNamespace(
        visible=True,
        track=Track(
            track_id=1,
            category="person",
            confidence=0.9,
            bounds=BoundingBox(0.7, 0.7, 0.9, 0.95),
            first_seen_at=1.0,
            last_seen_at=1.0,
        ),
    )

    command = controller.command_for(target)

    assert command.pan > 0
    assert command.tilt > 0


def test_follow_controller_returns_idle_for_missing_target():
    controller = FollowController()
    assert controller.command_for(None) == FollowCommand()


class FakePtzDevice:
    def __init__(self):
        self.calls = []

    def get_range(self, name):
        if name == "Pan":
            return PtzAxisRange(minimum=-100, maximum=100, step=1, default=0)
        if name == "Tilt":
            return PtzAxisRange(minimum=-50, maximum=50, step=1, default=0)
        if name == "Zoom":
            return PtzAxisRange(minimum=100, maximum=400, step=1, default=100)
        raise KeyError(name)

    def get(self, name):
        return {"Pan": 0, "Tilt": 0, "Zoom": 100}[name]

    def set(self, name, value):
        self.calls.append((name, value))

    def close(self):
        pass


def test_duvc_ptz_controller_stays_closed_until_used():
    device = FakePtzDevice()
    controller = DuvcPtzController(device_factory=lambda _: device)

    controller.close()

    assert device.calls == []
