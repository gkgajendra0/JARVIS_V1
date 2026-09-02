from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from jarvis.identity.active_speaker import (
    LR_ASD_PROVIDER_ID,
    ActiveSpeakerAssessment,
    ActiveSpeakerState,
    ActiveSpeakerVisualBuffer,
    _context_frame_ranges,
    _mfcc_fft_size,
)
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, FollowCommand, TargetState, Track
from jarvis.vision.runtime import VisionSnapshot


def _track(track_id: int, observed_at: float) -> Track:
    return Track(
        track_id=track_id,
        category="person",
        confidence=0.95,
        bounds=BoundingBox(0.20, 0.10, 0.80, 0.95),
        first_seen_at=1.0,
        last_seen_at=observed_at,
    )


def _pair(
    frame_id: int,
    observed_at: float,
    *,
    track_id: int = 7,
    include_head: bool = True,
) -> tuple[CapturedFrame, VisionSnapshot]:
    track = _track(track_id, observed_at)
    head = (
        (
            HeadObservation(
                confidence=0.99,
                bounds=BoundingBox(0.35, 0.15, 0.65, 0.45),
                frame_id=frame_id,
                observed_at=observed_at,
            ),
        )
        if include_head
        else ()
    )
    frame = CapturedFrame(
        frame_id=frame_id,
        captured_at=observed_at,
        image=np.full((240, 320, 3), 100 + frame_id % 50, dtype=np.uint8),
    )
    snapshot = VisionSnapshot(
        frame_id=frame_id,
        captured_at=observed_at,
        tracks=(track,),
        target=TargetState(track_id=track_id, track=track),
        command=FollowCommand(),
        armed=False,
        detector_persons=1,
        heads=head,
    )
    return frame, snapshot


def test_visual_buffer_preserves_25fps_source_frames() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(31):
        frame, snapshot = _pair(index, 10.0 + index * 0.04)
        buffer.observe(frame, snapshot)

    window = buffer.build_window(
        visual_track_id=7,
        start_monotonic=10.0,
        end_monotonic=11.2,
    )

    assert window is not None
    assert window.visual_track_id == 7
    assert window.frames.shape == (31, 112, 112)
    assert window.frames.dtype == np.uint8
    assert window.source_sample_count == 31
    assert window.unique_source_frames == 31
    assert window.source_fps == pytest.approx(25.0)
    assert window.maximum_source_gap_seconds < 0.05


def test_visual_buffer_preserves_full_multicontext_window_up_to_six_seconds() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(126):
        frame, snapshot = _pair(index, 70.0 + index * 0.04)
        buffer.observe(frame, snapshot)

    window = buffer.build_window(
        visual_track_id=7,
        start_monotonic=70.0,
        end_monotonic=75.0,
    )

    assert window is not None
    assert window.duration_seconds == pytest.approx(5.0)
    assert window.unique_source_frames == 126
    assert window.source_fps == pytest.approx(25.0)


def test_lr_asd_context_ranges_cover_every_frame_for_each_duration() -> None:
    for duration_seconds in range(1, 7):
        ranges = _context_frame_ranges(115, 22.85, duration_seconds)

        assert ranges
        assert ranges[0][0] == 0
        assert ranges[-1][1] == 115
        assert sum(end - start for start, end in ranges) == 115
        assert all(
            left_end == right_start
            for (_, left_end), (right_start, _) in pairwise(ranges)
        )


def test_lr_asd_mfcc_fft_never_truncates_low_cadence_window() -> None:
    assert _mfcc_fft_size(25.0) == 512
    assert _mfcc_fft_size(18.0) == 1024

    frame_samples = round(0.025 * 25.0 / 12.5 * 16_000)
    assert _mfcc_fft_size(12.5) >= frame_samples


def test_visual_buffer_preserves_lower_real_cadence_without_duplication() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(16):
        frame, snapshot = _pair(index, 40.0 + index * 0.08)
        buffer.observe(frame, snapshot)

    window = buffer.build_window(
        visual_track_id=7,
        start_monotonic=40.0,
        end_monotonic=41.2,
    )

    assert window is not None
    assert window.frames.shape == (16, 112, 112)
    assert window.source_sample_count == 16
    assert window.unique_source_frames == 16
    assert window.source_fps == pytest.approx(12.5)


def test_visual_buffer_accepts_camera_frames_with_fresh_perception_context() -> None:
    buffer = ActiveSpeakerVisualBuffer(max_snapshot_age_seconds=0.15)
    _, snapshot = _pair(100, 50.0)
    timestamps = [50.02, 50.05, 50.08, 50.11, 50.14]
    for index, observed_at in enumerate(timestamps, start=101):
        frame = CapturedFrame(
            frame_id=index,
            captured_at=observed_at,
            image=np.full((240, 320, 3), 125, dtype=np.uint8),
        )
        buffer.observe(frame, snapshot)

    window = buffer.build_window(
        visual_track_id=7,
        start_monotonic=50.02,
        end_monotonic=50.14,
    )

    assert window is not None
    assert window.unique_source_frames == 5
    assert window.source_fps == pytest.approx(33.333333, rel=1e-5)


def test_visual_buffer_rejects_stale_or_future_perception_context() -> None:
    buffer = ActiveSpeakerVisualBuffer(max_snapshot_age_seconds=0.15)
    _, snapshot = _pair(200, 60.0)
    stale_frame = CapturedFrame(
        frame_id=201,
        captured_at=60.151,
        image=np.full((240, 320, 3), 125, dtype=np.uint8),
    )
    earlier_frame = CapturedFrame(
        frame_id=199,
        captured_at=59.99,
        image=np.full((240, 320, 3), 125, dtype=np.uint8),
    )

    buffer.observe(stale_frame, snapshot)
    buffer.observe(earlier_frame, snapshot)

    assert (
        buffer.build_window(
            visual_track_id=7,
            start_monotonic=59.9,
            end_monotonic=60.2,
        )
        is None
    )


def test_visual_buffer_never_stitches_different_tracks() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    for index in range(15):
        frame, snapshot = _pair(index, 20.0 + index * 0.04, track_id=7)
        buffer.observe(frame, snapshot)
    for index in range(15, 30):
        frame, snapshot = _pair(index, 20.0 + index * 0.04, track_id=8)
        buffer.observe(frame, snapshot)

    assert (
        buffer.build_window(
            visual_track_id=7,
            start_monotonic=20.0,
            end_monotonic=21.16,
        )
        is None
    )


def test_visual_buffer_rejects_large_temporal_gap_and_missing_head() -> None:
    buffer = ActiveSpeakerVisualBuffer()
    timestamps = [30.00, 30.04, 30.08, 30.12, 30.80, 30.84, 30.88]
    for index, observed_at in enumerate(timestamps):
        frame, snapshot = _pair(index, observed_at)
        buffer.observe(frame, snapshot)

    frame, snapshot = _pair(50, 30.92, include_head=False)
    buffer.observe(frame, snapshot)

    assert (
        buffer.build_window(
            visual_track_id=7,
            start_monotonic=30.0,
            end_monotonic=30.92,
        )
        is None
    )


def test_active_speaker_score_cannot_confirm_actor_before_calibration() -> None:
    assessment = ActiveSpeakerAssessment(
        provider_id=LR_ASD_PROVIDER_ID,
        state=ActiveSpeakerState.SCORED,
        audio_turn_id="turn-1",
        windows_session_id="wts:1",
        visual_track_id=7,
        start_monotonic=1.0,
        end_monotonic=2.0,
        visual_frames=25,
        unique_visual_frames=25,
        audio_feature_frames=100,
        mean_score=0.99,
        median_score=0.99,
        minimum_score=0.98,
        maximum_score=1.0,
        reason_codes=("active_speaker_shadow_score_no_threshold",),
    )

    assert assessment.active_speaker_confirmed is False
