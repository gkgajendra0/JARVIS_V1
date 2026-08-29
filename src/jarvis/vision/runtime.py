"""Minimal composition root for the Step 2.5 vision loop."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.vision.camera import CameraSource
from jarvis.vision.detector import ObjectDetector
from jarvis.vision.follow import FollowController
from jarvis.vision.models import FollowCommand, TargetState, Track
from jarvis.vision.ptz import PtzController
from jarvis.vision.targeting import TargetManager
from jarvis.vision.tracker import Tracker


@dataclass(frozen=True, slots=True)
class VisionSnapshot:
    frame_id: int
    captured_at: float
    tracks: tuple[Track, ...]
    target: TargetState | None
    command: FollowCommand


class VisionRuntime:
    """Compose capture, detection, tracking, target policy, and PTZ control."""

    def __init__(
        self,
        *,
        camera: CameraSource,
        detector: ObjectDetector,
        tracker: Tracker,
        target_manager: TargetManager,
        follow_controller: FollowController,
        ptz: PtzController,
    ) -> None:
        self._camera = camera
        self._detector = detector
        self._tracker = tracker
        self._target_manager = target_manager
        self._follow_controller = follow_controller
        self._ptz = ptz
        self._last_frame_id: int | None = None
        self._latest_tracks: list[Track] = []
        self._started = False

    @property
    def latest_tracks(self) -> tuple[Track, ...]:
        return tuple(self._latest_tracks)

    @property
    def target(self) -> TargetState | None:
        return self._target_manager.target

    def start(self) -> None:
        if self._started:
            raise RuntimeError("vision runtime is already started")
        self._camera.start()
        self._started = True

    def lock(self, track_id: int) -> TargetState:
        track = next(
            (
                candidate
                for candidate in self._latest_tracks
                if candidate.track_id == track_id
            ),
            None,
        )
        if track is None:
            raise ValueError(f"track {track_id} is not currently visible")
        return self._target_manager.lock(track)

    def clear_target(self) -> None:
        self._target_manager.clear()

    def process_once(self, *, timeout_seconds: float = 1.0) -> VisionSnapshot | None:
        if not self._started:
            raise RuntimeError("vision runtime is not started")
        frame = self._camera.latest(
            after_frame_id=self._last_frame_id,
            timeout_seconds=timeout_seconds,
        )
        if frame is None:
            return None

        self._last_frame_id = frame.frame_id
        detections = self._detector.detect(frame)
        tracks = self._tracker.update(detections, now=frame.captured_at)
        self._latest_tracks = tracks
        target = self._target_manager.update(tracks, now=frame.captured_at)
        command = self._follow_controller.command_for(target)
        self._ptz.move(command)

        return VisionSnapshot(
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            tracks=tuple(tracks),
            target=target,
            command=command,
        )

    def close(self) -> None:
        self._target_manager.clear()
        try:
            self._ptz.close()
        finally:
            self._camera.close()
            self._started = False
