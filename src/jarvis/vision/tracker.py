"""Tracking boundary plus mature Roboflow tracker adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from jarvis.vision.models import BoundingBox, Detection, Track

_FIRST_SEEN_RETENTION_SECONDS = 120.0


class Tracker(Protocol):
    def update(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None = None,
    ) -> list[Track]: ...


@dataclass(frozen=True, slots=True)
class ByteTrackConfig:
    frame_rate: float = 30.0
    lost_track_buffer: int = 30
    track_activation_threshold: float = 0.7
    minimum_consecutive_frames: int = 2
    minimum_iou_threshold: float = 0.1
    high_conf_det_threshold: float = 0.6


@dataclass(frozen=True, slots=True)
class BoTSORTConfig:
    frame_rate: float = 30.0
    lost_track_buffer: int = 30
    track_activation_threshold: float = 0.7
    minimum_consecutive_frames: int = 2
    minimum_iou_threshold_first_assoc: float = 0.2
    minimum_iou_threshold_second_assoc: float = 0.5
    minimum_iou_threshold_unconfirmed_assoc: float = 0.3
    high_conf_det_threshold: float = 0.6
    enable_cmc: bool = True
    cmc_method: str = "sparseOptFlow"
    cmc_downscale: int = 2
    instant_first_frame_activation: bool = True


@dataclass(frozen=True, slots=True)
class OCSORTConfig:
    """Fast-motion profile for observation-centric person tracking."""

    frame_rate: float = 30.0
    lost_track_buffer: int = 60
    minimum_consecutive_frames: int = 2
    minimum_iou_threshold: float = -0.30
    direction_consistency_weight: float = 0.20
    high_conf_det_threshold: float = 0.40
    delta_t: int = 2


class _RoboflowTrackerAdapter:
    """Shared translation between canonical JARVIS and supervision detections."""

    def __init__(
        self,
        *,
        tracker: object,
        detections_factory: Callable[..., object] | None = None,
    ) -> None:
        if detections_factory is None:
            import supervision as sv

            detections_factory = sv.Detections
        self._detections_factory = detections_factory
        self._tracker = tracker
        self._first_seen: dict[int, float] = {}
        self._last_seen: dict[int, float] = {}

    def _update_external(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None,
    ) -> object:
        raise NotImplementedError

    def update(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None = None,
    ) -> list[Track]:
        if now < 0:
            raise ValueError("now must be non-negative")

        tracked = self._update_external(detections, now=now, frame=frame)
        tracker_ids = getattr(tracked, "tracker_id", None)
        if tracker_ids is None:
            self._prune_track_history(now)
            return []

        xyxy = np.asarray(tracked.xyxy)
        confidences = np.asarray(tracked.confidence)
        ids = np.asarray(tracker_ids)
        output: list[Track] = []

        for box, confidence, track_id in zip(xyxy, confidences, ids, strict=True):
            track_id = int(track_id)
            if track_id < 0:
                continue
            bounds = self._from_external_box(box, frame=frame)
            first_seen = self._first_seen.setdefault(track_id, now)
            self._last_seen[track_id] = now
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

        self._prune_track_history(now)
        return output

    def _prune_track_history(self, now: float) -> None:
        cutoff = now - _FIRST_SEEN_RETENTION_SECONDS
        stale_ids = [
            track_id
            for track_id, last_seen in self._last_seen.items()
            if last_seen < cutoff
        ]
        for track_id in stale_ids:
            self._last_seen.pop(track_id, None)
            self._first_seen.pop(track_id, None)

    def _to_external(
        self,
        detections: list[Detection],
        *,
        frame: np.ndarray | None = None,
    ) -> object:
        if not detections:
            return self._detections_factory(
                xyxy=np.empty((0, 4), dtype=np.float32),
                confidence=np.empty((0,), dtype=np.float32),
            )

        width = float(frame.shape[1]) if frame is not None else 1.0
        height = float(frame.shape[0]) if frame is not None else 1.0
        boxes = np.asarray(
            [
                [
                    detection.bounds.left * width,
                    detection.bounds.top * height,
                    detection.bounds.right * width,
                    detection.bounds.bottom * height,
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

    @staticmethod
    def _from_external_box(
        box: np.ndarray,
        *,
        frame: np.ndarray | None,
    ) -> BoundingBox:
        width = float(frame.shape[1]) if frame is not None else 1.0
        height = float(frame.shape[0]) if frame is not None else 1.0
        return BoundingBox(
            left=float(box[0]) / width,
            top=float(box[1]) / height,
            right=float(box[2]) / width,
            bottom=float(box[3]) / height,
        )


class ByteTrackAdapter(_RoboflowTrackerAdapter):
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
        tracker = tracker_factory(
            lost_track_buffer=self.config.lost_track_buffer,
            frame_rate=self.config.frame_rate,
            track_activation_threshold=self.config.track_activation_threshold,
            minimum_consecutive_frames=self.config.minimum_consecutive_frames,
            minimum_iou_threshold=self.config.minimum_iou_threshold,
            high_conf_det_threshold=self.config.high_conf_det_threshold,
        )
        super().__init__(tracker=tracker, detections_factory=detections_factory)

    def _update_external(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None,
    ) -> object:
        return self._tracker.update(
            self._to_external(detections, frame=frame),
            timestamp=now,
        )


class BoTSORTAdapter(_RoboflowTrackerAdapter):
    """Use Roboflow BoT-SORT with camera-motion compensation for Pocket 3."""

    def __init__(
        self,
        config: BoTSORTConfig | None = None,
        *,
        tracker_factory: Callable[..., object] | None = None,
        detections_factory: Callable[..., object] | None = None,
    ) -> None:
        self.config = config or BoTSORTConfig()
        if tracker_factory is None:
            from trackers import BoTSORTTracker

            tracker_factory = BoTSORTTracker
        tracker = tracker_factory(
            lost_track_buffer=self.config.lost_track_buffer,
            frame_rate=self.config.frame_rate,
            track_activation_threshold=self.config.track_activation_threshold,
            minimum_consecutive_frames=self.config.minimum_consecutive_frames,
            minimum_iou_threshold_first_assoc=(
                self.config.minimum_iou_threshold_first_assoc
            ),
            minimum_iou_threshold_second_assoc=(
                self.config.minimum_iou_threshold_second_assoc
            ),
            minimum_iou_threshold_unconfirmed_assoc=(
                self.config.minimum_iou_threshold_unconfirmed_assoc
            ),
            high_conf_det_threshold=self.config.high_conf_det_threshold,
            enable_cmc=self.config.enable_cmc,
            cmc_method=self.config.cmc_method,
            cmc_downscale=self.config.cmc_downscale,
            instant_first_frame_activation=self.config.instant_first_frame_activation,
        )
        super().__init__(tracker=tracker, detections_factory=detections_factory)

    def _update_external(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None,
    ) -> object:
        if self.config.enable_cmc and frame is None:
            raise ValueError("BoT-SORT camera-motion compensation requires a frame")
        return self._tracker.update(
            self._to_external(detections, frame=frame),
            frame=frame,
            timestamp=now,
        )


class OCSORTAdapter(_RoboflowTrackerAdapter):
    """Use OC-SORT + DIoU for fast, non-linear target motion."""

    def __init__(
        self,
        config: OCSORTConfig | None = None,
        *,
        tracker_factory: Callable[..., object] | None = None,
        detections_factory: Callable[..., object] | None = None,
        iou_factory: Callable[[], object] | None = None,
        state_estimator_class: type | None = None,
    ) -> None:
        self.config = config or OCSORTConfig()
        if tracker_factory is None:
            from trackers import OCSORTTracker

            tracker_factory = OCSORTTracker
        if iou_factory is None:
            from trackers.utils.iou import DIoU

            iou_factory = DIoU
        if state_estimator_class is None:
            from trackers.utils.state_representations import XYXYStateEstimator

            state_estimator_class = XYXYStateEstimator

        tracker = tracker_factory(
            lost_track_buffer=self.config.lost_track_buffer,
            frame_rate=self.config.frame_rate,
            minimum_consecutive_frames=self.config.minimum_consecutive_frames,
            minimum_iou_threshold=self.config.minimum_iou_threshold,
            direction_consistency_weight=self.config.direction_consistency_weight,
            high_conf_det_threshold=self.config.high_conf_det_threshold,
            delta_t=self.config.delta_t,
            state_estimator_class=state_estimator_class,
            iou=iou_factory(),
        )
        super().__init__(tracker=tracker, detections_factory=detections_factory)

    def _update_external(
        self,
        detections: list[Detection],
        *,
        now: float,
        frame: np.ndarray | None,
    ) -> object:
        return self._tracker.update(
            self._to_external(detections, frame=frame),
            timestamp=now,
        )