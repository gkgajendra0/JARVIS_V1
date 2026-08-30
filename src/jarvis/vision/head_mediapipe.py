"""MediaPipe BlazeFace Full-Range adapter for JARVIS head detection."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.head import HeadObservation, NormalizedPoint
from jarvis.vision.models import BoundingBox

DetectorFactory = Callable[["MediaPipeBlazeFaceConfig"], Any]
ImageFactory = Callable[[np.ndarray], Any]

BLAZEFACE_MODEL_NAME = "blaze_face_full_range.tflite"


def default_blazeface_model_path() -> Path:
    """Resolve the single local BlazeFace asset path used by JARVIS diagnostics."""
    configured = os.environ.get("JARVIS_BLAZEFACE_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JARVIS" / "models" / BLAZEFACE_MODEL_NAME
    return Path.home() / ".jarvis" / "models" / BLAZEFACE_MODEL_NAME


@dataclass(frozen=True, slots=True)
class MediaPipeBlazeFaceConfig:
    """Production settings selected from the Pocket 3 benchmark."""

    model_path: Path | str
    minimum_confidence: float = 0.65
    minimum_suppression_threshold: float = 0.30

    def __post_init__(self) -> None:
        path = Path(self.model_path)
        object.__setattr__(self, "model_path", path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be in [0, 1]")
        if not 0 <= self.minimum_suppression_threshold <= 1:
            raise ValueError("minimum_suppression_threshold must be in [0, 1]")


class MediaPipeBlazeFaceDetector:
    """Translate MediaPipe face detections into canonical HeadObservation values."""

    def __init__(
        self,
        config: MediaPipeBlazeFaceConfig,
        *,
        detector_factory: DetectorFactory | None = None,
        image_factory: ImageFactory | None = None,
    ) -> None:
        self.config = config
        self._detector = (detector_factory or _default_detector_factory)(config)
        self._image_factory = image_factory or _default_image_factory
        self._last_timestamp_ms = -1
        self._closed = False

    def detect(self, frame: CapturedFrame) -> list[HeadObservation]:
        if self._closed:
            raise RuntimeError("head detector is closed")

        rgb = np.ascontiguousarray(frame.image[:, :, ::-1])
        image = self._image_factory(rgb)
        timestamp_ms = max(
            self._last_timestamp_ms + 1,
            round(frame.captured_at * 1000.0),
        )
        self._last_timestamp_ms = timestamp_ms
        result = self._detector.detect_for_video(image, timestamp_ms)

        observations: list[HeadObservation] = []
        for detection in getattr(result, "detections", ()):
            categories = getattr(detection, "categories", ())
            if not categories:
                continue
            confidence = float(categories[0].score)
            if confidence < self.config.minimum_confidence:
                continue

            box = detection.bounding_box
            left = _clamp(float(box.origin_x) / frame.width)
            top = _clamp(float(box.origin_y) / frame.height)
            right = _clamp(float(box.origin_x + box.width) / frame.width)
            bottom = _clamp(float(box.origin_y + box.height) / frame.height)
            if left >= right or top >= bottom:
                continue

            keypoints = tuple(
                NormalizedPoint(x=_clamp(float(point.x)), y=_clamp(float(point.y)))
                for point in getattr(detection, "keypoints", ())
            )
            observations.append(
                HeadObservation(
                    confidence=confidence,
                    bounds=BoundingBox(left, top, right, bottom),
                    frame_id=frame.frame_id,
                    observed_at=frame.captured_at,
                    keypoints=keypoints,
                )
            )

        return observations

    def close(self) -> None:
        if self._closed:
            return
        self._detector.close()
        self._closed = True


def _default_detector_factory(config: MediaPipeBlazeFaceConfig) -> Any:
    try:
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise RuntimeError(
            "MediaPipe is required for BlazeFace head detection; install the vision dependencies"
        ) from exc

    options = vision.FaceDetectorOptions(
        base_options=python.BaseOptions(model_asset_path=str(config.model_path)),
        running_mode=vision.RunningMode.VIDEO,
        min_detection_confidence=config.minimum_confidence,
        min_suppression_threshold=config.minimum_suppression_threshold,
    )
    return vision.FaceDetector.create_from_options(options)


def _default_image_factory(rgb: np.ndarray) -> Any:
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError(
            "MediaPipe is required for BlazeFace head detection; install the vision dependencies"
        ) from exc
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
