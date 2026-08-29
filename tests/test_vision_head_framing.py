from __future__ import annotations

import numpy as np
import pytest

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.follow import FollowConfig, FollowController
from jarvis.vision.framing import HeadFirstFramingConfig, HeadFirstFramingPolicy
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


def test_follow_controller_can_compose_head_above_frame_center():
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
    head = _head(BoundingBox(0.60, 0.45, 0.70, 0.55))
    framing = HeadFirstFramingPolicy().resolve(target, [head])

    command = controller.command_for_framing_target(framing)

    assert command.pan > 0
    assert command.tilt > 0


class _FakeCamera:
    def __init__(self) -> None:
        self.frame = CapturedFrame(
            frame_id=1,
            captured_at=1.0,
            image=np.zeros((100, 100, 3), dtype=np.uint8),
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
    def update(self, detections, *, now):
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

    def detect(self, frame):
        return list(self.heads)


class _RecordingPtz:
    def move(self, command) -> None:
        pass

    def close(self) -> None:
        pass


def test_runtime_can_require_linked_head_before_lock():
    heads = _MutableHeadDetector()
    runtime = VisionRuntime(
        camera=_FakeCamera(),
        detector=_FakeDetector(),
        tracker=_FakeTracker(),
        target_manager=TargetManager(),
        follow_controller=FollowController(),
        ptz=_RecordingPtz(),
        head_detector=heads,
        config=VisionRuntimeConfig(require_head_for_lock=True),
    )

    runtime.start()
    runtime.process_once()

    with pytest.raises(ValueError, match="no valid linked head"):
        runtime.lock(7)

    heads.heads = [_head(BoundingBox(0.42, 0.14, 0.58, 0.34))]
    runtime._latest_heads = list(heads.heads)
    locked = runtime.lock(7)

    assert locked.track_id == 7
    runtime.close()
