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
from jarvis.vision.tracker import ByteTrackAdapter


class FakeRFModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inference_kwargs = None

    def inference(self, **kwargs):
        self.inference_kwargs = kwargs

    def predict(self, image, threshold):
        assert image.shape == (100, 200, 3)
        assert threshold == 0.5
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

        def predict(self, image, threshold):
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

    first = adapter.update([detection], now=10.0)[0]
    second = adapter.update([detection], now=10.1)[0]

    assert first.track_id == 4
    assert first.first_seen_at == 10.0
    assert second.first_seen_at == 10.0
    assert second.last_seen_at == 10.1


class FakePtzBackend:
    def __init__(self):
        self.values = {"pan": 0, "tilt": 0}
        self.writes = []

    def get_axis_range(self, axis):
        if axis == "pan":
            return PtzAxisRange(-35, 215, 1, 0)
        return PtzAxisRange(-90, 90, 1, 0)

    def get_axis_value(self, axis):
        return self.values[axis]

    def set_axis_value(self, axis, value):
        self.values[axis] = value
        self.writes.append((axis, value))

    def close(self):
        pass


def test_duvc_ptz_maps_normalized_command_and_clamps():
    backend = FakePtzBackend()
    ptz = DuvcPtzController(backend=backend)

    ptz.move(FollowCommand(pan=0.35, tilt=-0.35))

    assert backend.writes == [("pan", 4), ("tilt", -3)]

    backend.values["pan"] = 215
    ptz.move(FollowCommand(pan=0.35))
    assert backend.values["pan"] == 215


class FakeCamera:
    def __init__(self, frame):
        self.frame = frame
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def latest(self, *, after_frame_id=None, timeout_seconds=None):
        if after_frame_id is not None and self.frame.frame_id <= after_frame_id:
            return None
        return self.frame

    def close(self):
        self.closed = True


class FakeDetector:
    def __init__(self, detection):
        self.detection = detection

    def detect(self, frame):
        return [self.detection]


class MutableFakeTracker:
    def __init__(self, tracks):
        self.tracks = list(tracks)

    def update(self, detections, *, now):
        return list(self.tracks)


class RecordingPtz:
    def __init__(self):
        self.commands = []
        self.closed = False

    def move(self, command):
        self.commands.append(command)

    def close(self):
        self.closed = True


def _make_runtime_fixture():
    frame = CapturedFrame(
        frame_id=1,
        captured_at=5.0,
        image=np.zeros((100, 100, 3), dtype=np.uint8),
    )
    detection = Detection(
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.7, 0.3, 0.9, 0.7),
        frame_id=1,
        observed_at=5.0,
    )
    track = Track(
        track_id=3,
        category="person",
        confidence=0.95,
        bounds=detection.bounds,
        first_seen_at=5.0,
        last_seen_at=5.0,
    )
    camera = FakeCamera(frame)
    tracker = MutableFakeTracker([track])
    ptz = RecordingPtz()
    runtime = VisionRuntime(
        camera=camera,
        detector=FakeDetector(detection),
        tracker=tracker,
        target_manager=TargetManager(lost_timeout_seconds=0.5),
        follow_controller=FollowController(),
        ptz=ptz,
        config=VisionRuntimeConfig(minimum_ptz_interval_seconds=0.2),
    )
    return runtime, camera, tracker, ptz


def test_runtime_requires_lock_and_separate_arm_before_movement():
    runtime, camera, tracker, ptz = _make_runtime_fixture()

    runtime.start()
    first = runtime.process_once()
    assert first is not None
    assert first.command.is_idle
    assert not first.armed
    assert ptz.commands == []

    runtime.lock(3)
    camera.frame = CapturedFrame(
        frame_id=2,
        captured_at=5.1,
        image=camera.frame.image,
    )
    locked = runtime.process_once()
    assert locked is not None
    assert locked.target is not None
    assert locked.command.is_idle
    assert not runtime.armed
    assert ptz.commands == []

    runtime.arm_follow()
    camera.frame = CapturedFrame(
        frame_id=3,
        captured_at=5.2,
        image=camera.frame.image,
    )
    armed = runtime.process_once()
    assert armed is not None
    assert armed.armed
    assert armed.command.pan > 0
    assert len(ptz.commands) == 1

    runtime.close()
    assert camera.closed
    assert ptz.closed


def test_runtime_rate_limits_ptz_and_disarms_after_target_expires():
    runtime, camera, tracker, ptz = _make_runtime_fixture()

    runtime.start()
    runtime.process_once()
    runtime.lock(3)
    runtime.arm_follow()

    camera.frame = CapturedFrame(frame_id=2, captured_at=5.1, image=camera.frame.image)
    runtime.process_once()
    assert len(ptz.commands) == 1

    camera.frame = CapturedFrame(frame_id=3, captured_at=5.2, image=camera.frame.image)
    rate_limited = runtime.process_once()
    assert rate_limited is not None
    assert rate_limited.command.is_idle
    assert len(ptz.commands) == 1

    tracker.tracks = []
    camera.frame = CapturedFrame(frame_id=4, captured_at=5.3, image=camera.frame.image)
    missing = runtime.process_once()
    assert missing is not None
    assert runtime.armed
    assert missing.command.is_idle
    assert len(ptz.commands) == 1

    camera.frame = CapturedFrame(frame_id=5, captured_at=5.9, image=camera.frame.image)
    expired = runtime.process_once()
    assert expired is not None
    assert expired.target is None
    assert not runtime.armed
    assert expired.command.is_idle
    assert len(ptz.commands) == 1

    runtime.close()
