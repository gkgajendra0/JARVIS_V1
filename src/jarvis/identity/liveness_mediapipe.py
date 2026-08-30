from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class FaceLandmarkerBlendshapeObservation:
    observed_at_monotonic: float
    blendshapes: dict[str, float]


class MediaPipeFaceLandmarker:
    """On-device Face Landmarker adapter exposing only blendshape scores."""

    provider_id = "mediapipe-face-landmarker-v1"

    def __init__(
        self,
        model_path: str | Path,
        *,
        minimum_face_detection_confidence: float = 0.5,
        minimum_face_presence_confidence: float = 0.5,
        minimum_tracking_confidence: float = 0.5,
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        for name, value in {
            "minimum_face_detection_confidence": minimum_face_detection_confidence,
            "minimum_face_presence_confidence": minimum_face_presence_confidence,
            "minimum_tracking_confidence": minimum_tracking_confidence,
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

        try:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise RuntimeError(
                "MediaPipe is required for active liveness; install vision dependencies"
            ) from exc

        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=minimum_face_detection_confidence,
            min_face_presence_confidence=minimum_face_presence_confidence,
            min_tracking_confidence=minimum_tracking_confidence,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1
        self._closed = False

    def observe(
        self,
        bgr_image: np.ndarray,
        *,
        observed_at_monotonic: float,
    ) -> FaceLandmarkerBlendshapeObservation | None:
        if self._closed:
            raise RuntimeError("face landmarker is closed")
        if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            raise ValueError("active liveness expects a BGR image")

        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "MediaPipe is required for active liveness; install vision dependencies"
            ) from exc

        rgb = np.ascontiguousarray(bgr_image[:, :, ::-1])
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = max(
            self._last_timestamp_ms + 1,
            round(observed_at_monotonic * 1000.0),
        )
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        face_blendshapes = getattr(result, "face_blendshapes", ())
        if not face_blendshapes:
            return None

        scores: dict[str, float] = {}
        for category in face_blendshapes[0]:
            name = _category_name(category)
            score = getattr(category, "score", None)
            if name and isinstance(score, int | float):
                numeric = float(score)
                if 0.0 <= numeric <= 1.0:
                    scores[name] = numeric
        if not scores:
            return None
        return FaceLandmarkerBlendshapeObservation(
            observed_at_monotonic=observed_at_monotonic,
            blendshapes=scores,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._landmarker.close()
        self._closed = True

    def __enter__(self) -> MediaPipeFaceLandmarker:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def _category_name(category: Any) -> str | None:
    for attribute in ("category_name", "display_name", "label"):
        value = getattr(category, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
