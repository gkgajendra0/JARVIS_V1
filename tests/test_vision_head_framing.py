from __future__ import annotations

import numpy as np
import pytest

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.follow import FollowConfig, FollowController
from jarvis.vision.framing import (
    HeadConfirmationConfig,
    HeadConfirmationGate,
    HeadFirstFramingConfig,
    HeadFirstFramingPolicy,
)
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, Detection, TargetState, Track
from jarvis.vision.runtime import VisionRuntime, VisionRuntimeConfig
from jarvis.vision.targeting import TargetManager


def _track(track_id: int = 7) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.20, 0.10, 0.80, 0.95),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )


def _head(
    bounds: BoundingBox,
    *,
    confidence: float = 0.9,
) -> HeadObservation:
    return HeadObservation(
        confidence=confidence,
        bounds=bounds,
        frame_id=1,
        observed_at=1.0,
    )


def test_head_first_policy_prefers_head_linked_to_locked_body():
    track = _track()
    target = TargetState(track_id=track.track_id, track=track)
    linked = _head(BoundingBox(0.42, 0.14, 0.58, 0.34), confidence=0.88)
    unrelated = _head(BoundingBox(0.82, 0.10, 0.98, 0.32), confidence=0.99)

    framing = HeadFirstFramingPolicy().resolve(target, [unrelated, linked])

    assert framing is not None
    assert framing.source == "head"
    assert framing.track_id == track.track_id
    assert framing.x == pytest.approx(linked.bounds.center_x)
    assert framing.y == pytest.approx(linked.bounds.center_y)
    assert framing.confidence == linked.confidence


def test_head_first_policy_uses_only_locked_body_as_fallback():
    track = _track()
    target = TargetState(track_id=track.track_id, track=track)
    unrelated = _head(BoundingBox(0.82, 0.10, 0.98, 0.32), confidence=0.99)
    policy = HeadFirstFramingPolicy(
        HeadFirstFramingConfig(body_fallback_vertical_fraction=0.20)
    )

    framing = policy.resolve(target, [unrelated])

    assert framing is not None
    assert framing.source == "body"
    assert framing.track_id == track.track_id
    assert framing.x == pytest.approx(track.bounds.center_x)
    assert framing.y == pytest.approx(0.27)


def test_head_first_policy_returns_none_without_locked_visible_target():
    head = _head(BoundingBox(0.42, 0.14, 0.58, 0.34))

    assert HeadFirstFramingPolicy().resolve(None, [head]) is None
    assert (
        HeadFirstFramingPolicy().resolve(
            TargetState(track_id=7, track=None, missing_since=1.0),
            [head],
        )
        is None
    )


def test_follow_controller_maps_image_y_to_pocket3_tilt_direction():
    controller = FollowController(
        FollowConfig(
            horizontal_dead_zone=0.05,
            vertical_dead_zone=0.05,
            gain=1.0,
            max_command=0.5,
            desired_x=0.5,
            desired_y=0.4,
        )
    )
    track = _track()
    target = TargetState(track_id=track.track_id, track=track)

    below_target = _head(BoundingBox(0.60, 0.45, 0.70, 0.55))
    below_framing = HeadFirstFramingPolicy().resolve(target, [below_target])
    below_command = controller.command_for_framing_target(below_framing)

    assert below_command.pan > 0
    assert below_command.tilt < 0

    above_target = _head(BoundingBox(0.42, 0.15, 0.58, 0.25))
    above_framing = HeadFirstFramingPolicy().resolve(target, [above_target])
    above_command = controller.command_for_framing_target(above_framing)

    assert above_command.tilt > 0


def test_head_confirmation_gate_requires_three_consecutive_linked_frames():
    policy = HeadFirstFramingPolicy()
    gate = HeadConfirmationGate(HeadConfirmationConfig(required_consecutive_frames=3))
    track = _track()
    linked = _head(BoundingBox(0.42, 0.14, 0.58, 0.34), confidence=0.90)

    gate.update([track], [linked], policy)
    assert gate.confirmation_frames(track.track_id) == 1
    assert not gate.eligible(track.track_id)

    gate.update([track], [linked], policy)
    assert gate.confirmation_frames(track.track_id) == 2
    assert not gate.eligible(track.track_id)

    gate.update([track], [linked], policy)
    assert gate.confirmation_frames(track.track_id) == 3
    assert gate.eligible(track.track_id)

    gate.update([track], [], policy)
    assert gate.confirmation_frames(track.track_id) == 0
    assert not gate.eligible(track.track_id)


class _FakeCamera:
    def __init__(self) -> None:
        self.frame = CapturedFrame(
            frame_id=1,
            captured_at=1.0,
            image=np.zeros((100, 100, 3), dtype=np.uint8),
        )

    def advance(self) -> None:
        self.frame = CapturedFrame(
            frame_id=self.frame.frame_id + 1,
            captured_at=self.frame.captured_at + 0.1,
            image=self.frame.image,
        )

    def start(self) -> None:
        pass

    def latest(self, *, after_frame_id=None, timeout_seconds=None):
        if after_frame_id is not None and self.frame.frame_id <= after_frame_id:
            return None
        return self.frame

    def close(self) -> None:
        pass


class _FakeDetector:
    def detect(self, frame):
        return [
            Detection(
                category="person",
                confidence=0.95,
                bounds=_track().bounds,
                frame_id=frame.frame_id,
                observed_at=frame.captured_at,
            )
        ]


class _FakeTracker:
    def update(self, detections, *, now, frame=None):
        track = _track()
        return [
            Track(
                track_id=track.track_id,
                category=track.category,
                confidence=track.confidence,
                bounds=track.bounds,
                first_seen_at=track.first_seen_at,
                last_seen_at=now,
            )
        ]


class _MutableHeadDetector:
    def __init__(self) -> None:
        self.heads: list[HeadObservation] = []
        self.closed = False

    def detect(self, frame):
        return list(self.heads)

    def close(self) -> None:
        self.closed = True


class _RecordingPtz:
    def __init__(self) -> None:
        self.commands = []

    def move(self, command) -> None:
        self.commands.append(command)

    def close(self) -> None:
        pass


def test_runtime_requires_confirmed_linked_head_before_lock():
    camera = _FakeCamera()
    heads = _MutableHeadDetector()
    runtime = VisionRuntime(
        camera=camera,
        detector=_FakeDetector(),
        tracker=_FakeTracker(),
        target_manager=TargetManager(),
        follow_controller=FollowController(),
        ptz=_RecordingPtz(),
        head_detector=heads,
        config=VisionRuntimeConfig(
            require_head_for_lock=True,
            required_head_confirmation_frames=3,
        ),
    )

    runtime.start()
    heads.heads = [_head(BoundingBox(0.42, 0.14, 0.58, 0.34))]

    runtime.process_once()
    with pytest.raises(ValueError, match=r"not confirmed \(1/3\)"):
        runtime.lock(7)

    camera.advance()
    runtime.process_once()
    with pytest.raises(ValueError, match=r"not confirmed \(2/3\)"):
        runtime.lock(7)

    camera.advance()
    runtime.process_once()
    locked = runtime.lock(7)

    assert locked.track_id == 7
    assert runtime.head_lock_eligible(7)
    runtime.close()
    assert heads.closed


def test_runtime_holds_head_briefly_and_makes_fallback_horizontal_only():
    camera = _FakeCamera()
    heads = _MutableHeadDetector()
    ptz = _RecordingPtz()
    runtime = VisionRuntime(
        camera=camera,
        detector=_FakeDetector(),
        tracker=_FakeTracker(),
        target_manager=TargetManager(),
        follow_controller=FollowController(
            FollowConfig(
                horizontal_dead_zone=0.01,
                vertical_dead_zone=0.01,
                gain=1.0,
                max_command=0.5,
                desired_x=0.4,
                desired_y=0.4,
            )
        ),
        ptz=ptz,
        head_detector=heads,
        config=VisionRuntimeConfig(
            minimum_ptz_interval_seconds=0.05,
            require_head_for_lock=True,
            required_head_confirmation_frames=3,
            head_loss_grace_seconds=0.25,
        ),
    )

    runtime.start()
    heads.heads = [_head(BoundingBox(0.42, 0.18, 0.58, 0.38))]
    runtime.process_once()
    camera.advance()
    runtime.process_once()
    camera.advance()
    runtime.process_once()
    runtime.lock(7)
    runtime.arm_follow()

    camera.advance()
    heads.heads = []
    held = runtime.process_once()

    assert held is not None
    assert held.framing_target is not None
    assert held.framing_target.source == "head_hold"
    assert held.command.pan > 0
    assert held.command.tilt == 0

    camera.advance()
    runtime.process_once()
    camera.advance()
    body = runtime.process_once()

    assert body is not None
    assert body.framing_target is not None
    assert body.framing_target.source == "body"
    assert body.command.pan > 0
    assert body.command.tilt == 0

    camera.advance()
    heads.heads = [_head(BoundingBox(0.42, 0.18, 0.58, 0.38))]
    resumed = runtime.process_once()

    assert resumed is not None
    assert resumed.framing_target is not None
    assert resumed.framing_target.source == "head"
    assert runtime.head_confirmation_frames(7) == 1
    assert resumed.command.tilt != 0

    runtime.close()
