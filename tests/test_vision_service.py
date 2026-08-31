from __future__ import annotations

import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.runtime import VisionSnapshot
from jarvis.vision.service import VisionService


def _track(track_id: int) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.2, 0.1, 0.8, 0.95),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )


def _snapshot(frame_id: int, observed_at: float) -> VisionSnapshot:
    track = _track(7)
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=observed_at,
        tracks=(track,),
        target=TargetState(track_id=7, track=track),
        command=FollowCommand(),
        armed=False,
        detector_persons=1,
    )


class _FakeRuntime:
    def __init__(self, tracks: list[Track], eligible_ids: set[int]) -> None:
        self.latest_tracks = tuple(tracks)
        self._eligible_ids = eligible_ids
        self.target: TargetState | None = None
        self.armed = False

    def head_lock_eligible(self, track_id: int) -> bool:
        return track_id in self._eligible_ids

    def lock(self, track_id: int) -> TargetState:
        track = next(
            track for track in self.latest_tracks if track.track_id == track_id
        )
        self.target = TargetState(track_id=track_id, track=track)
        self.armed = False
        return self.target

    def arm_follow(self) -> None:
        if self.target is None or not self.target.visible:
            raise RuntimeError("cannot arm follow without a visible locked target")
        self.armed = True

    def disarm_follow(self) -> None:
        self.armed = False

    def clear_target(self) -> None:
        self.armed = False
        self.target = None


def test_service_locks_only_one_head_confirmed_visible_person() -> None:
    runtime = _FakeRuntime([_track(7)], {7})
    service = VisionService(runtime)  # type: ignore[arg-type]

    result = service.lock_only_confirmed_person()

    assert result == {"ok": True, "track_id": 7, "armed": False}
    assert runtime.target is not None
    assert runtime.target.track_id == 7


def test_service_refuses_ambiguous_head_confirmed_people() -> None:
    runtime = _FakeRuntime([_track(7), _track(8)], {7, 8})
    service = VisionService(runtime)  # type: ignore[arg-type]

    result = service.lock_only_confirmed_person()

    assert result["ok"] is False
    assert "exactly one" in str(result["reason"])
    assert runtime.target is None


def test_service_requires_lock_before_arming() -> None:
    runtime = _FakeRuntime([_track(7)], {7})
    service = VisionService(runtime)  # type: ignore[arg-type]

    try:
        service.arm_follow()
    except RuntimeError as exc:
        assert "visible locked target" in str(exc)
    else:
        raise AssertionError("arming without a target must fail")


def test_frame_pair_tap_accepts_only_fresh_perception_context() -> None:
    runtime = _FakeRuntime([_track(7)], {7})
    service = VisionService(
        runtime,  # type: ignore[arg-type]
        frame_pair_tap=lambda frame, snapshot: None,
        frame_pair_tap_max_snapshot_age_seconds=0.15,
    )
    service._latest_snapshot = _snapshot(10, 100.0)
    fresh_frame = CapturedFrame(
        frame_id=11,
        captured_at=100.10,
        image=np.zeros((10, 10, 3), dtype=np.uint8),
    )
    stale_frame = CapturedFrame(
        frame_id=12,
        captured_at=100.151,
        image=np.zeros((10, 10, 3), dtype=np.uint8),
    )
    earlier_frame = CapturedFrame(
        frame_id=9,
        captured_at=99.99,
        image=np.zeros((10, 10, 3), dtype=np.uint8),
    )

    assert service._fresh_snapshot_for_frame(fresh_frame) is service._latest_snapshot
    assert service._fresh_snapshot_for_frame(stale_frame) is None
    assert service._fresh_snapshot_for_frame(earlier_frame) is None
