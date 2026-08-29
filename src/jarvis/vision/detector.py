"""Object-detection boundary and RF-DETR Nano adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox, Detection


class ObjectDetector(Protocol):
    def detect(self, frame: CapturedFrame) -> list[Detection]: ...


@dataclass(frozen=True, slots=True)
class RFDetrNanoConfig:
    device: str = "cuda"
    threshold: float = 0.25
    dtype: str = "bfloat16"
    person_class_id: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be in [0, 1]")
        if self.person_class_id < 0:
            raise ValueError("person_class_id must be non-negative")


class RFDetrNanoDetector:
    """Translate RF-DETR Nano outputs into canonical JARVIS detections."""

    def __init__(
        self,
        config: RFDetrNanoConfig | None = None,
        *,
        model_factory: Callable[..., object] | None = None,
    ) -> None:
        self.config = config or RFDetrNanoConfig()
        if model_factory is None:
            from rfdetr import RFDETRNano

            model_factory = RFDETRNano

        self._model = model_factory(device=self.config.device)
        inference = getattr(self._model, "inference", None)
        if inference is not None:
            inference(
                compile=False,
                inplace=True,
                dtype=self.config.dtype,
            )

    def detect(self, frame: CapturedFrame) -> list[Detection]:
        rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
        raw = self._model.predict(rgb, threshold=self.config.threshold)

        class_ids = np.asarray(raw.class_id)
        confidences = np.asarray(raw.confidence)
        boxes = np.asarray(raw.xyxy)

        mask = class_ids == self.config.person_class_id
        detections: list[Detection] = []
        for box, confidence in zip(boxes[mask], confidences[mask], strict=True):
            normalized = self._normalize_box(
                box, width=frame.width, height=frame.height
            )
            if normalized is None:
                continue
            detections.append(
                Detection(
                    category="person",
                    confidence=float(confidence),
                    bounds=normalized,
                    frame_id=frame.frame_id,
                    observed_at=frame.captured_at,
                )
            )
        return detections

    @staticmethod
    def _normalize_box(
        box: np.ndarray,
        *,
        width: int,
        height: int,
    ) -> BoundingBox | None:
        left, top, right, bottom = (float(value) for value in box)
        left = max(0.0, min(float(width), left)) / width
        right = max(0.0, min(float(width), right)) / width
        top = max(0.0, min(float(height), top)) / height
        bottom = max(0.0, min(float(height), bottom)) / height
        if left >= right or top >= bottom:
            return None
        return BoundingBox(left=left, top=top, right=right, bottom=bottom)
