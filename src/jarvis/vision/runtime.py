"""Minimal composition root for the Step 2.5 vision loop."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.vision.camera import CameraSource, CapturedFrame
from jarvis.vision.detector import ObjectDetector
from jarvis.vision.follow import FollowController
from jarvis.vision.framing import (
    FramingTarget,
    HeadConfirmationConfig,
    HeadConfirmationGate,
    HeadFirstFramingPolicy,
)
from jarvis.vision.head import HeadDetector, HeadObservation
from jarvis.vision.models import FollowCommand, TargetState, Track
from jarvis.vision.ptz import PtzController
from jarvis.vision.targeting import TargetManager
from jarvis.vision.tracker import Tracker


@dataclass(frozen=True, slots=True)
class VisionRuntimeConfig:
    minimum_ptz_interval_seconds: float = 0.2
    require_head_for_lock: bool = False
    required_head_confirmation_frames: int = 3

    def __post_init__(self) -> None:
        if self.minimum_ptz_interval_seconds <= 0:
            raise ValueError("minimum_ptz_interval_seconds must be positive")
        if self.required_head_confirmation_frames < 1:
            raise ValueError("required_head_confirmation_frames must be at least 1")


@dataclass(frozen=True, slots=True)
class VisionSnapshot:
    frame_id: int
    captured_at: float
    tracks: tuple[Track, ...]
    target: TargetState | None
    command: FollowCommand
    armed: bool
    heads: tuple[HeadObservation, ...] = ()
    framing_target: FramingTarget | None = None


class VisionRuntime:
    """Compose capture, perception, target policy, framing, and PTZ control."""

    def __init__(
        self,
        *,
        camera: CameraSource,
        detector: ObjectDetector,
        tracker: Tracker,
        target_manager: TargetManager,
        follow_controller: FollowController,
        ptz: PtzController,
        config: VisionRuntimeConfig | None = None,
        head_detector: HeadDetector | None = None,
        framing_policy: HeadFirstFramingPolicy | None = None,
        head_confirmation_gate: HeadConfirmationGate | None = None,
    ) -> None:
        self.config = config or VisionRuntimeConfig()
        if self.config.require_head_for_lock and head_detector is None:
            raise ValueError("require_head_for_lock needs a configured head detector")

        self._camera = camera
        self._detector = detector
        self._tracker = tracker
        self._target_manager = target_manager
        self._follow_controller = follow_controller
        self._ptz = ptz
        self._head_detector = head_detector
        self._framing_policy = (
            framing_policy
            if framing_policy is not None
            else HeadFirstFramingPolicy()
            if head_detector is not None
            else None
        )
        self._head_confirmation_gate = (
            head_confirmation_gate
            if head_confirmation_gate is not None
            else HeadConfirmationGate(
                HeadConfirmationConfig(
                    required_consecutive_frames=(
                        self.config.required_head_confirmation_frames
                    )
                )
            )
            if head_detector is not None
            else None
        )
        self._last_frame_id: int | None = None
        self._latest_frame: CapturedFrame | None = None
        self._latest_tracks: list[Track] = []
        self._latest_heads: list[HeadObservation] = []
        self._latest_framing_target: FramingTarget | None = None
        self._last_ptz_command_at: float | None = None
        self._armed = False
        self._started = False

    @property
    def latest_frame(self) -> CapturedFrame | None:
        return self._latest_frame

    @property
    def latest_tracks(self) -> tuple[Track, ...]:
        return tuple(self._latest_tracks)

    @property
    def latest_heads(self) -> tuple[HeadObservation, ...]:
        return tuple(self._latest_heads)

    @property
    def framing_target(self) -> FramingTarget | None:
        return self._latest_framing_target

    @property
    def target(self) -> TargetState | None:
        return self._target_manager.target

    @property
    def armed(self) -> bool:
        return self._armed

    def head_confirmation_frames(self, track_id: int) -> int:
        if self._head_confirmation_gate is None:
            return 0
        return self._head_confirmation_gate.confirmation_frames(track_id)

    def head_lock_eligible(self, track_id: int) -> bool:
        if self._head_confirmation_gate is None:
            return not self.config.require_head_for_lock
        return self._head_confirmation_gate.eligible(track_id)

    def start(self) -> None:
        if self._started:
            raise RuntimeError("vision runtime is already started")
        self._armed = False
        self._last_ptz_command_at = None
        if self._head_confirmation_gate is not None:
            self._head_confirmation_gate.reset()
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

        if self.config.require_head_for_lock and not self.head_lock_eligible(track_id):
            confirmed = self.head_confirmation_frames(track_id)
            required = self.config.required_head_confirmation_frames
            raise ValueError(
                f"track {track_id} head is not confirmed ({confirmed}/{required})"
            )

        self.disarm_follow()
        return self._target_manager.lock(track)

    def arm_follow(self) -> None:
        target = self._target_manager.target
        if target is None or not target.visible:
            raise RuntimeError("cannot arm follow without a visible locked target")
        self._last_ptz_command_at = None
        self._armed = True

    def disarm_follow(self) -> None:
        self._armed = False
        self._last_ptz_command_at = None

    def clear_target(self) -> None:
        self.disarm_follow()
        self._target_manager.clear()
        self._latest_framing_target = None

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
        self._latest_frame = frame
        detections = self._detector.detect(frame)
        tracks = self._tracker.update(detections, now=frame.captured_at)
        self._latest_tracks = tracks
        target = self._target_manager.update(tracks, now=frame.captured_at)
        if target is None:
            self.disarm_follow()

        heads: list[HeadObservation] = []
        framing_target: FramingTarget | None = None
        if self._head_detector is not None:
            heads = self._head_detector.detect(frame)
            assert self._framing_policy is not None
            assert self._head_confirmation_gate is not None
            self._head_confirmation_gate.update(tracks, heads, self._framing_policy)

            confirmed_heads = heads
            if target is not None and not self.head_lock_eligible(target.track_id):
                confirmed_heads = []
            framing_target = self._framing_policy.resolve(target, confirmed_heads)
            desired = self._follow_controller.command_for_framing_target(framing_target)
        else:
            desired = self._follow_controller.command_for(target)

        self._latest_heads = heads
        self._latest_framing_target = framing_target

        command = FollowCommand()
        if (
            self._armed
            and target is not None
            and target.visible
            and not desired.is_idle
        ):
            last_command_at = self._last_ptz_command_at
            interval_elapsed = (
                last_command_at is None
                or frame.captured_at - last_command_at
                >= self.config.minimum_ptz_interval_seconds
            )
            if interval_elapsed:
                command = desired
                self._ptz.move(command)
                self._last_ptz_command_at = frame.captured_at

        return VisionSnapshot(
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            tracks=tuple(tracks),
            target=target,
            command=command,
            armed=self._armed,
            heads=tuple(heads),
            framing_target=framing_target,
        )

    def close(self) -> None:
        self.clear_target()
        try:
            self._ptz.close()
        finally:
            try:
                if self._head_detector is not None:
                    self._head_detector.close()
            finally:
                self._camera.close()
                self._latest_frame = None
                self._latest_heads = []
                if self._head_confirmation_gate is not None:
                    self._head_confirmation_gate.reset()
                self._started = False
