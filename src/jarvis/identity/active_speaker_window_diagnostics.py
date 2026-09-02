"""Diagnostic-only explanation for LR-ASD visual-window rejection.

The production acceptance rules remain owned by ``ActiveSpeakerVisualBuffer``.
This module intentionally mirrors those gates only so a rejected real-machine
window has observable timing/cadence evidence before any tolerance is changed.
It never changes scoring, trust, or authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from jarvis.identity.active_speaker import ActiveSpeakerVisualBuffer


@dataclass(frozen=True, slots=True)
class ActiveSpeakerVisualWindowDiagnostic:
    reason_code: str
    candidate_count: int
    track_sample_count: int
    start_gap_seconds: float | None
    end_gap_seconds: float | None
    maximum_source_gap_seconds: float | None
    source_fps: float | None


def diagnose_visual_window_failure(
    buffer: ActiveSpeakerVisualBuffer,
    *,
    visual_track_id: int,
    start_monotonic: float,
    end_monotonic: float,
    max_duration_seconds: float = 6.0,
    minimum_source_frames: int = 5,
    maximum_source_gap_seconds: float = 0.35,
    maximum_edge_gap_seconds: float = 0.15,
) -> ActiveSpeakerVisualWindowDiagnostic:
    """Explain which accepted visual-window gate rejected the requested interval."""
    if end_monotonic <= start_monotonic:
        return ActiveSpeakerVisualWindowDiagnostic(
            reason_code="visual_window_non_positive_duration",
            candidate_count=0,
            track_sample_count=0,
            start_gap_seconds=None,
            end_gap_seconds=None,
            maximum_source_gap_seconds=None,
            source_fps=None,
        )

    window_start = max(start_monotonic, end_monotonic - max_duration_seconds)
    # Same-package diagnostics intentionally inspect the buffer under its own lock.
    # No samples are mutated and no raw frames leave memory.
    with buffer._lock:
        track_samples = tuple(
            sample
            for sample in buffer._samples
            if sample.visual_track_id == visual_track_id
        )
        candidates = tuple(
            sample
            for sample in track_samples
            if window_start <= sample.observed_at_monotonic <= end_monotonic
        )

    if len(candidates) < minimum_source_frames:
        return ActiveSpeakerVisualWindowDiagnostic(
            reason_code="visual_window_too_few_source_frames",
            candidate_count=len(candidates),
            track_sample_count=len(track_samples),
            start_gap_seconds=None,
            end_gap_seconds=None,
            maximum_source_gap_seconds=None,
            source_fps=None,
        )

    times = np.asarray(
        [sample.observed_at_monotonic for sample in candidates], dtype=np.float64
    )
    start_gap = float(times[0] - window_start)
    end_gap = float(end_monotonic - times[-1])
    gaps = np.diff(times)
    maximum_gap = float(np.max(gaps)) if gaps.size else 0.0
    span = float(times[-1] - times[0])
    source_fps = (len(candidates) - 1) / span if span > 0 else None

    if start_gap > maximum_edge_gap_seconds:
        reason = "visual_window_start_edge_gap"
    elif end_gap > maximum_edge_gap_seconds:
        reason = "visual_window_end_edge_gap"
    elif maximum_gap > maximum_source_gap_seconds:
        reason = "visual_window_internal_gap"
    elif span <= 0:
        reason = "visual_window_zero_source_span"
    elif source_fps is None or not math.isfinite(source_fps):
        reason = "visual_window_invalid_source_fps"
    elif not 5.0 <= source_fps <= 60.0:
        reason = "visual_window_source_fps_out_of_range"
    else:
        reason = "visual_window_rejected_unknown_gate"

    return ActiveSpeakerVisualWindowDiagnostic(
        reason_code=reason,
        candidate_count=len(candidates),
        track_sample_count=len(track_samples),
        start_gap_seconds=start_gap,
        end_gap_seconds=end_gap,
        maximum_source_gap_seconds=maximum_gap,
        source_fps=source_fps,
    )
