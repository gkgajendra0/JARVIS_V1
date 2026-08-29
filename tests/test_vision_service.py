from __future__ import annotations

from jarvis.vision.models import BoundingBox, TargetState, Track
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


class _FakeRuntime:
    def __init__(self, tracks: list[Track], eligible_ids: set[int]) -> None:
        self.latest_tracks = tuple(tracks)
        self._eligible_ids = eligible_ids
        self.target: TargetState | None = None
        self.armed = False

    def head_lock_eligible(self, track_id: int) -> bool:
        return track_id in self._eligible_ids

    def lock(self, track_id: int) -> TargetState:
        track = next(track for track in self.latest_tracks if track.track_id == track_id)
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
