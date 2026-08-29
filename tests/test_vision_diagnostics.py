from __future__ import annotations

from jarvis.vision.diagnostics import VisionDiagnostics
from jarvis.vision.framing import FramingTarget
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.runtime import VisionSnapshot


def _track(track_id: int = 7, *, now: float = 1.0) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.2, 0.1, 0.8, 0.95),
        first_seen_at=1.0,
        last_seen_at=max(1.0, now),
    )


def _snapshot(
    frame_id: int,
    *,
    target: TargetState | None,
    source: str | None,
    armed: bool = False,
    people: tuple[Track, ...] | None = None,
    detector_persons: int | None = None,
) -> VisionSnapshot:
    track = target.track if target is not None else None
    tracks = people if people is not None else ((track,) if track is not None else ())
    framing_target = (
        FramingTarget(
            x=0.5,
            y=0.4,
            confidence=0.9,
            source=source,
            track_id=target.track_id,
        )
        if source is not None and target is not None
        else None
    )
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=float(frame_id),
        tracks=tracks,
        target=target,
        command=FollowCommand(pan=0.1 if armed else 0.0),
        armed=armed,
        detector_persons=len(tracks) if detector_persons is None else detector_persons,
        heads=(),
        framing_target=framing_target,
    )


def test_diagnostics_records_head_body_loss_and_reacquisition_transitions() -> None:
    diagnostics = VisionDiagnostics()
    diagnostics.set_running(True)

    first_track = _track(now=1.0)
    diagnostics.observe(
        _snapshot(
            1,
            target=TargetState(track_id=7, track=first_track),
            source="head",
        )
    )
    diagnostics.observe(
        _snapshot(
            2,
            target=TargetState(track_id=7, track=_track(now=2.0)),
            source="body",
            armed=True,
        )
    )
    diagnostics.observe(
        _snapshot(
            3,
            target=TargetState(track_id=7, track=None, missing_since=3.0),
            source=None,
            armed=True,
        )
    )
    diagnostics.observe(
        _snapshot(
            4,
            target=TargetState(track_id=7, track=_track(now=4.0)),
            source="head",
            armed=True,
        )
    )

    report = diagnostics.report(event_limit=20)
    codes = [event["code"] for event in report["recent_events"]]

    assert "vision_started" in codes
    assert "vision_ready" in codes
    assert "follow_armed" in codes
    assert "framing_source_changed" in codes
    assert "target_temporarily_lost" in codes
    assert "target_reacquired" in codes
    assert report["status"]["target_id"] == 7
    assert report["status"]["target_visible"] is True
    assert report["status"]["framing_source"] == "head"


def test_diagnostics_exposes_detector_tracker_counts_on_track_dropout() -> None:
    diagnostics = VisionDiagnostics()
    diagnostics.set_running(True)
    track = _track()

    diagnostics.observe(
        _snapshot(
            1,
            target=TargetState(track_id=7, track=track),
            source="head",
            detector_persons=1,
        )
    )
    diagnostics.observe(
        _snapshot(
            2,
            target=TargetState(track_id=7, track=None, missing_since=2.0),
            source=None,
            people=(),
            detector_persons=1,
        )
    )

    report = diagnostics.report(event_limit=10)
    event = next(
        item
        for item in report["recent_events"]
        if item["code"] == "people_count_changed"
    )

    assert "RF-DETR=1" in event["message"]
    assert "BoT-SORT=0" in event["message"]
    assert report["status"]["detector_persons"] == 1
    assert report["status"]["visible_people"] == 0


def test_diagnostics_history_is_bounded() -> None:
    diagnostics = VisionDiagnostics(max_events=3)
    diagnostics.set_running(True)
    diagnostics.record_action(code="one", message="one")
    diagnostics.record_action(code="two", message="two")
    diagnostics.record_action(code="three", message="three")

    report = diagnostics.report(event_limit=10)

    assert [event["code"] for event in report["recent_events"]] == [
        "one",
        "two",
        "three",
    ]
