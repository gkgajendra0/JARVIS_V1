from __future__ import annotations

import argparse

import numpy as np
import pytest

from jarvis.identity.active_speaker import ActiveSpeakerState
from jarvis.identity.lr_asd_alignment_benchmark import (
    OffsetComparison,
    OffsetPhaseScore,
    _best_offset,
    _parse_offsets,
    _rms_dbfs,
    _trace_activity_fraction,
    _window_end_times,
)


def _phase_score(offset_ms: int, phase: str, median: float) -> OffsetPhaseScore:
    return OffsetPhaseScore(
        offset_ms=offset_ms,
        phase=phase,
        state=ActiveSpeakerState.SCORED.value,
        mean_score=median,
        median_score=median,
        activity_fraction=median,
        trace_frames=25,
        inference_ms=50.0,
        reason_codes=(),
    )


def test_parse_offsets_sorts_deduplicates_and_requires_zero() -> None:
    assert _parse_offsets("100,0,-100,100") == (-100, 0, 100)

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_offsets("100,200")


def test_rms_dbfs_reports_silence_and_known_half_scale() -> None:
    silence = np.zeros(480, dtype=np.int16)
    half_scale = np.full(480, 16384, dtype=np.int16)

    assert _rms_dbfs(silence) == float("-inf")
    assert abs(_rms_dbfs(half_scale) - (-6.0206)) < 0.001


def test_trace_activity_fraction_uses_threshold() -> None:
    assert _trace_activity_fraction((), threshold=0.5) is None
    assert _trace_activity_fraction((0.1, 0.5, 0.9, 0.2), threshold=0.5) == 0.5


def test_best_offset_maximizes_owner_phone_median_separation() -> None:
    comparisons = [
        OffsetComparison(
            offset_ms=0,
            phone=_phase_score(0, "PHONE_ONLY", 0.10),
            owner=_phase_score(0, "OWNER_ONLY", 0.40),
            median_separation=0.30,
        ),
        OffsetComparison(
            offset_ms=200,
            phone=_phase_score(200, "PHONE_ONLY", 0.05),
            owner=_phase_score(200, "OWNER_ONLY", 0.85),
            median_separation=0.80,
        ),
    ]

    best = _best_offset(comparisons)

    assert best is not None
    assert best.offset_ms == 200


def test_window_end_times_excludes_unsettled_prefix_and_tail() -> None:
    values = _window_end_times(
        start_monotonic=10.0,
        end_monotonic=13.0,
        settle_seconds=0.5,
        window_seconds=1.0,
        step_seconds=0.5,
    )

    assert values == (11.5, 12.0, 12.5)
