from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.head import NormalizedPoint
from jarvis.vision.head_mediapipe import (
    MediaPipeBlazeFaceConfig,
    MediaPipeBlazeFaceDetector,
)
from jarvis.vision.models import BoundingBox


class _FakeDetector:
    def __init__(self) -> None:
        self.timestamps: list[int] = []
        self.closed = False

    def detect_for_video(self, image, timestamp_ms):
        assert image.shape == (100, 200, 3)
        self.timestamps.append(timestamp_ms)
        detection = SimpleNamespace(
            categories=[SimpleNamespace(score=0.88)],
            bounding_box=SimpleNamespace(
                origin_x=20,
                origin_y=10,
                width=80,
                height=80,
            ),
            keypoints=[
                SimpleNamespace(x=0.25, y=0.30),
                SimpleNamespace(x=0.45, y=0.30),
            ],
        )
        return SimpleNamespace(detections=[detection])

    def close(self) -> None:
        self.closed = True


def test_blazeface_adapter_normalizes_detection_and_uses_monotonic_timestamps(
    tmp_path,
):
    model = tmp_path / "blaze_face_full_range.tflite"
    model.write_bytes(b"model")
    fake = _FakeDetector()
    detector = MediaPipeBlazeFaceDetector(
        MediaPipeBlazeFaceConfig(model_path=model),
        detector_factory=lambda config: fake,
        image_factory=lambda rgb: rgb,
    )
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:, :, 0] = 7
    frame = CapturedFrame(frame_id=1, captured_at=1.0, image=image)

    observations = detector.detect(frame)
    second = detector.detect(CapturedFrame(frame_id=2, captured_at=1.0, image=image))

    assert len(observations) == 1
    observation = observations[0]
    assert observation.confidence == 0.88
    assert observation.bounds == BoundingBox(0.1, 0.1, 0.5, 0.9)
    assert observation.keypoints == (
        NormalizedPoint(0.25, 0.30),
        NormalizedPoint(0.45, 0.30),
    )
    assert observation.frame_id == 1
    assert len(second) == 1
    assert fake.timestamps == [1000, 1001]

    detector.close()
    detector.close()
    assert fake.closed
