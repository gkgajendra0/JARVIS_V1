from __future__ import annotations

import numpy as np

from jarvis.identity.active_speaker import ActiveSpeakerVisualBuffer
from jarvis.identity.active_speaker_window_diagnostics import (
    diagnose_visual_window_failure,
)
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.runtime import VisionSnapshot


def _pair(frame_id: int, observed_at: float) -> tuple[CapturedFrame, VisionSnapshot]:
    track = Track(
        track_id=7,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.20, 0.10, 0.80, 0.95),
        first_seen_at=1.0,
        last_seen_at=observed_at,
    )
    head = HeadObservation(
        confidence=0.99,
        bounds=BoundingBox(0.35, 0.15, 0.65, 0.45),
        frame_id=frame_id,
        observed_at=observed_at,
    )
    frame = CapturedFrame(
        frame_id=frame_id,
        captured_at=observed_at,
        image=np.full((240, 320, 3), 125, dtype=np.uint8),
    )
    snapshot = VisionSnapshot(
        frame_id=frame_id,
        captured_at=observed_at,
        tracks=(track,),
        target=TargetState(track_id=7, track=track),
        command=FollowCommand(),
        armed=False,
        detector_persons=1,
        heads=(head,),
    )
    return frame, snapshot


def test_diagnostic_reports_too_few_frames() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(3):
        frame, snapshot = _pair(index, 10.0 + index * 0.04)
        buffer.observe(frame, snapshot)

    result = diagnose_visual_window_failure(
        buffer,
        visual_track_id=7,
        start_monotonic=10.0,
        end_monotonic=10.2,
    )

    assert result.reason_code == "visual_window_too_few_source_frames"
    assert result.candidate_count == 3
    assert result.track_sample_count == 3


def test_diagnostic_reports_end_edge_gap() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(10):
        frame, snapshot = _pair(index, 20.0 + index * 0.04)
        buffer.observe(frame, snapshot)

    result = diagnose_visual_window_failure(
        buffer,
        visual_track_id=7,
        start_monotonic=20.0,
        end_monotonic=20.60,
    )

    assert result.reason_code == "visual_window_end_edge_gap"
    assert result.end_gap_seconds is not None
    assert result.end_gap_seconds > 0.15


def test_diagnostic_reports_internal_gap() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    timestamps = [30.00, 30.04, 30.08, 30.12, 30.60, 30.64, 30.68]
    for index, observed_at in enumerate(timestamps):
        frame, snapshot = _pair(index, observed_at)
        buffer.observe(frame, snapshot)

    result = diagnose_visual_window_failure(
        buffer,
        visual_track_id=7,
        start_monotonic=30.0,
        end_monotonic=30.68,
    )

    assert result.reason_code == "visual_window_internal_gap"
    assert result.maximum_source_gap_seconds is not None
    assert result.maximum_source_gap_seconds > 0.35
