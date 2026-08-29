"""Tracking boundary and ByteTrack adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from jarvis.vision.models import BoundingBox, Detection, Track


class Tracker(Protocol):
    def update(self, detections: list[Detection], *, now: float) -> list[Track]: ...


@dataclass(frozen=True, slots=True)
class ByteTrackConfig:
    frame_rate: float = 30.0
    lost_track_buffer: int = 30
    track_activation_threshold: float = 0.7
    minimum_consecutive_frames: int = 2
    minimum_iou_threshold: float = 0.1
    high_conf_det_threshold: float = 0.6


class ByteTrackAdapter:
    """Translate JARVIS detections to/from Roboflow ByteTrack."""

    def __init__(
        self,
        config: ByteTrackConfig | None = None,
        *,
        tracker_factory: Callable[..., object] | None = None,
        detections_factory: Callable[..., object] | None = None,
    ) -> None:
        self.config = config or ByteTrackConfig()
        if tracker_factory is None:
            from trackers import ByteTrackTracker

            tracker_factory = ByteTrackTracker
        if detections_factory is None:
            import supervision as sv

            detections_factory = sv.Detections

        self._detections_factory = detections_factory
        self._tracker = tracker_factory(
            lost_track_buffer=self.config.lost_track_buffer,
            frame_rate=self.config.frame_rate,
            track_activation_threshold=self.config.track_activation_threshold,
            minimum_consecutive_frames=self.config.minimum_consecutive_frames,
            minimum_iou_threshold=self.config.minimum_iou_threshold,
            high_conf_det_threshold=self.config.high_conf_det_threshold,
        )
        self._first_seen: dict[int, float] = {}

    def update(self, detections: list[Detection], *, now: float) -> list[Track]:
        if now < 0:
            raise ValueError("now must be non-negative")

        external = self._to_external(detections)
        tracked = self._tracker.update(external, timestamp=now)
        tracker_ids = getattr(tracked, "tracker_id", None)
        if tracker_ids is None:
            return []

        xyxy = np.asarray(tracked.xyxy)
        confidences = np.asarray(tracked.confidence)
        ids = np.asarray(tracker_ids)
        output: list[Track] = []

        for box, confidence, track_id in zip(xyxy, confidences, ids, strict=True):
            track_id = int(track_id)
            if track_id < 0:
                continue
            bounds = BoundingBox(
                left=float(box[0]),
                top=float(box[1]),
                right=float(box[2]),
                bottom=float(box[3]),
            )
            first_seen = self._first_seen.setdefault(track_id, now)
            output.append(
                Track(
                    track_id=track_id,
                    category="person",
                    confidence=float(confidence),
                    bounds=bounds,
                    first_seen_at=first_seen,
                    last_seen_at=now,
                )
            )
        return output

    def _to_external(self, detections: list[Detection]) -> object:
        if not detections:
            return self._detections_factory(
                xyxy=np.empty((0, 4), dtype=np.float32),
                confidence=np.empty((0,), dtype=np.float32),
            )

        boxes = np.asarray(
            [
                [
                    detection.bounds.left,
                    detection.bounds.top,
                    detection.bounds.right,
                    detection.bounds.bottom,
                ]
                for detection in detections
            ],
            dtype=np.float32,
        )
        confidences = np.asarray(
            [detection.confidence for detection in detections],
            dtype=np.float32,
        )
        return self._detections_factory(xyxy=boxes, confidence=confidences)
