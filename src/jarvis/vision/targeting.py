"""Deterministic target ownership for JARVIS vision."""

from __future__ import annotations

from jarvis.vision.models import TargetState, Track


class TargetManager:
    """Own exactly one explicitly locked track without silent target switching."""

    def __init__(self, *, lost_timeout_seconds: float = 0.5) -> None:
        if lost_timeout_seconds <= 0:
            raise ValueError("lost_timeout_seconds must be positive")
        self._lost_timeout_seconds = lost_timeout_seconds
        self._target: TargetState | None = None

    @property
    def target(self) -> TargetState | None:
        return self._target

    def lock(self, track: Track) -> TargetState:
        self._target = TargetState(track_id=track.track_id, track=track)
        return self._target

    def clear(self) -> None:
        self._target = None

    def update(self, tracks: list[Track], *, now: float) -> TargetState | None:
        target = self._target
        if target is None:
            return None

        matching = next((track for track in tracks if track.track_id == target.track_id), None)
        if matching is not None:
            self._target = TargetState(track_id=target.track_id, track=matching)
            return self._target

        missing_since = target.missing_since if target.missing_since is not None else now
        if now - missing_since >= self._lost_timeout_seconds:
            self._target = None
            return None

        self._target = TargetState(
            track_id=target.track_id,
            track=None,
            missing_since=missing_since,
        )
        return self._target
