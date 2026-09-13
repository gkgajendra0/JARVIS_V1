from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from jarvis.identity.owner_context import OwnerContextObserver, OwnerContextState
from jarvis.identity.owner_evidence import (
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
)
from jarvis.identity.passive_liveness import PassiveLivenessState
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.models import FollowCommand
from jarvis.vision.runtime import VisionSnapshot
from jarvis.vision.tracker import _RoboflowTrackerAdapter


@dataclass
class _Detections:
    xyxy: np.ndarray
    confidence: np.ndarray
    tracker_id: np.ndarray


class _FakeRoboflowTracker:
    def __init__(self) -> None:
        self.current = _Detections(
            xyxy=np.asarray([[10.0, 10.0, 40.0, 80.0]], dtype=np.float32),
            confidence=np.asarray([0.9], dtype=np.float32),
            tracker_id=np.asarray([7], dtype=int),
        )
        self.tracked_objects = _Detections(
            xyxy=np.asarray([[10.0, 10.0, 40.0, 80.0]], dtype=np.float32),
            confidence=np.empty((0,), dtype=np.float32),
            tracker_id=np.asarray([7], dtype=int),
        )


class _FakeAdapter(_RoboflowTrackerAdapter):
    def __init__(self, tracker: _FakeRoboflowTracker) -> None:
        super().__init__(tracker=tracker, detections_factory=lambda **_: None)

    def _update_external(self, detections, *, now, frame):
        del detections, now, frame
        return self._tracker.current


class _FakeWindow:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1


class _UnusedSessionProvider:
    def current_session(self):
        raise AssertionError("session provider should not be polled in this test")


def _live_owner_assessment(
    *, observed_at: float = 1.0
) -> OwnerLivenessBindingAssessment:
    return OwnerLivenessBindingAssessment(
        session_id="session-1",
        visual_track_id=7,
        state=OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE,
        identity_state=OwnerIdentityState.OWNER_CANDIDATE,
        liveness_state=PassiveLivenessState.LIVE,
        observed_at_monotonic=observed_at,
        reason_codes=("test_live_owner",),
    )


def _snapshot(
    *, frame_id: int, captured_at: float, alive: tuple[int, ...]
) -> VisionSnapshot:
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=captured_at,
        tracks=(),
        target=None,
        command=FollowCommand(),
        armed=False,
        detector_persons=1,
        heads=(),
        alive_track_ids=alive,
    )


def _frame(*, frame_id: int, captured_at: float) -> CapturedFrame:
    return CapturedFrame(
        frame_id=frame_id,
        captured_at=captured_at,
        image=np.zeros((100, 100, 3), dtype=np.uint8),
    )


def test_adapter_keeps_alive_track_id_separate_from_current_frame_visibility() -> None:
    tracker = _FakeRoboflowTracker()
    adapter = _FakeAdapter(tracker)
    image = np.zeros((100, 100, 3), dtype=np.uint8)

    visible = adapter.update([], now=1.0, frame=image)
    assert [track.track_id for track in visible] == [7]
    assert adapter.alive_track_ids() == (7,)

    tracker.current = _Detections(
        xyxy=np.empty((0, 4), dtype=np.float32),
        confidence=np.empty((0,), dtype=np.float32),
        tracker_id=np.empty((0,), dtype=int),
    )

    missed = adapter.update([], now=1.1, frame=image)
    assert missed == []
    assert adapter.alive_track_ids() == (7,)


def test_owner_context_holds_verified_owner_through_alive_track_miss() -> None:
    state = OwnerContextState()
    assessment = _live_owner_assessment()
    state.publish(assessment)
    identity_window = _FakeWindow()
    liveness_window = _FakeWindow()
    observer = OwnerContextObserver(
        owner_template=object(),
        face_detector=object(),
        face_recognizer=object(),
        pad_provider=object(),
        session_provider=_UnusedSessionProvider(),
        state=state,
    )
    observer._session_id = "session-1"
    observer._last_session_poll_at = 1.0
    observer._track_id = 7
    observer._identity_window = identity_window
    observer._liveness_window = liveness_window

    observer.observe(
        _frame(frame_id=1, captured_at=1.1),
        _snapshot(frame_id=1, captured_at=1.1, alive=(7,)),
    )

    current = state.snapshot()
    assert current.assessment == assessment
    assert current.invalidation_reason is None
    assert observer._track_id == 7
    assert identity_window.clear_calls == 0
    assert liveness_window.clear_calls == 0


def test_owner_context_fails_closed_after_bound_track_really_expires() -> None:
    state = OwnerContextState()
    state.publish(_live_owner_assessment())
    identity_window = _FakeWindow()
    liveness_window = _FakeWindow()
    observer = OwnerContextObserver(
        owner_template=object(),
        face_detector=object(),
        face_recognizer=object(),
        pad_provider=object(),
        session_provider=_UnusedSessionProvider(),
        state=state,
    )
    observer._session_id = "session-1"
    observer._last_session_poll_at = 1.0
    observer._track_id = 7
    observer._identity_window = identity_window
    observer._liveness_window = liveness_window

    observer.observe(
        _frame(frame_id=2, captured_at=1.1),
        _snapshot(frame_id=2, captured_at=1.1, alive=()),
    )

    current = state.snapshot()
    assert current.assessment is None
    assert (
        current.invalidation_reason
        == "owner_context_requires_one_head_associated_subject"
    )
    assert observer._track_id is None
    assert identity_window.clear_calls == 1
    assert liveness_window.clear_calls == 1
