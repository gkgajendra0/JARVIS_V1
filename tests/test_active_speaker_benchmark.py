from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.identity.active_speaker import (
    ActiveSpeakerState,
    ActiveSpeakerVisualWindow,
)
from jarvis.identity.active_speaker_benchmark import (
    SCENARIOS,
    OffsetObservation,
    ScenarioExpectation,
    ScenarioObservation,
    _parse_offsets,
    _shifted_visual_window,
    _threshold_samples,
    _wait_for_expected_owner,
)


def _offset(offset_ms: int, *scores: float) -> OffsetObservation:
    return OffsetObservation(
        offset_ms=offset_ms,
        state=ActiveSpeakerState.SCORED.value,
        reason_codes=(),
        frame_scores=tuple(scores),
        mean_score=float(np.mean(scores)) if scores else None,
        median_score=float(np.median(scores)) if scores else None,
        minimum_score=min(scores) if scores else None,
        maximum_score=max(scores) if scores else None,
        visual_frames=len(scores),
        unique_visual_frames=len(scores),
        source_fps=25.0,
        maximum_source_gap_seconds=0.04,
        inference_wall_ms=1.0,
        cuda_kernel_ms=None,
        gpu_baseline_allocated_bytes=None,
        gpu_peak_allocated_bytes=None,
        gpu_peak_delta_bytes=None,
        process_cpu_seconds=0.01,
        process_rss_before_bytes=100,
        process_rss_after_bytes=100,
    )


def _scenario(
    key: str,
    expectation: ScenarioExpectation,
    *offsets: OffsetObservation,
) -> ScenarioObservation:
    return ScenarioObservation(
        key=key,
        name=f"scenario-{key}",
        expectation=expectation,
        status="scored",
        captured_seconds=4.0,
        speech_seconds=3.0,
        speech_segments=1,
        max_vad_probability=0.9,
        quality_accepted=True,
        quality_reason_codes=(),
        owner_track_id=7,
        windows_session_id="wts:1",
        owner_context_fresh_after=True,
        owner_context_invalidation_after=None,
        offsets=tuple(offsets),
        notes=(),
    )


def test_scenario_contract_matches_step_3b11_acceptance() -> None:
    expected = {
        "A": ScenarioExpectation.POSITIVE,
        "B": ScenarioExpectation.NEGATIVE,
        "C": ScenarioExpectation.NEGATIVE,
        "D": ScenarioExpectation.NEGATIVE,
        "E": ScenarioExpectation.POSITIVE,
        "F": ScenarioExpectation.NEGATIVE,
        "G": ScenarioExpectation.AMBIGUOUS,
        "H": ScenarioExpectation.INSUFFICIENT,
    }

    assert {scenario.key: scenario.expectation for scenario in SCENARIOS} == expected


def test_offset_parser_requires_zero_and_bounds_extremes() -> None:
    assert _parse_offsets("300,0,-300,100") == (-300, 0, 100, 300)

    with pytest.raises(Exception, match="include 0"):
        _parse_offsets("-100,100")
    with pytest.raises(Exception, match="1000"):
        _parse_offsets("0,1001")


@pytest.mark.asyncio
async def test_wait_for_expected_owner_recovers_only_same_track_and_session() -> None:
    class FakeState:
        def __init__(self) -> None:
            self.calls = 0

        def snapshot(self) -> SimpleNamespace:
            self.calls += 1
            assessment = None
            if self.calls >= 2:
                assessment = SimpleNamespace(visual_track_id=7, session_id="wts:1")
            return SimpleNamespace(assessment=assessment, invalidation_reason=None)

        def has_fresh_live_owner_candidate(self) -> bool:
            return self.calls >= 2

    state = FakeState()
    assert await _wait_for_expected_owner(  # type: ignore[arg-type]
        state,
        owner_track_id=7,
        windows_session_id="wts:1",
        timeout_seconds=0.5,
    )


@pytest.mark.asyncio
async def test_wait_for_expected_owner_rejects_replacement_track() -> None:
    class FakeState:
        def snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(
                assessment=SimpleNamespace(visual_track_id=8, session_id="wts:1"),
                invalidation_reason=None,
            )

        def has_fresh_live_owner_candidate(self) -> bool:
            return True

    state = FakeState()
    assert not await _wait_for_expected_owner(  # type: ignore[arg-type]
        state,
        owner_track_id=7,
        windows_session_id="wts:1",
        timeout_seconds=0.02,
    )


def test_shifted_visual_window_uses_shifted_source_but_returns_audio_timeline() -> None:
    class FakeVisualBuffer:
        requested: tuple[float, float] | None = None

        def build_window(
            self,
            *,
            visual_track_id: int,
            start_monotonic: float,
            end_monotonic: float,
        ) -> ActiveSpeakerVisualWindow:
            assert visual_track_id == 7
            self.requested = (start_monotonic, end_monotonic)
            return ActiveSpeakerVisualWindow(
                visual_track_id=7,
                start_monotonic=start_monotonic,
                end_monotonic=end_monotonic,
                frames=np.zeros((25, 112, 112), dtype=np.uint8),
                source_sample_count=25,
                unique_source_frames=25,
                source_fps=25.0,
                maximum_source_gap_seconds=0.04,
            )

    buffer = FakeVisualBuffer()
    window = _shifted_visual_window(  # type: ignore[arg-type]
        buffer,
        visual_track_id=7,
        start_monotonic=10.0,
        end_monotonic=11.0,
        offset_seconds=0.2,
    )

    assert buffer.requested == pytest.approx((10.2, 11.2))
    assert window is not None
    assert window.start_monotonic == pytest.approx(10.0)
    assert window.end_monotonic == pytest.approx(11.0)


def test_threshold_samples_use_only_zero_offset_binary_scenarios() -> None:
    observations = [
        _scenario(
            "A",
            ScenarioExpectation.POSITIVE,
            _offset(0, 0.8, 0.9),
            _offset(100, 0.4, 0.5),
        ),
        _scenario(
            "B",
            ScenarioExpectation.NEGATIVE,
            _offset(0, 0.1, 0.2),
        ),
        _scenario(
            "E",
            ScenarioExpectation.POSITIVE,
            _offset(100, 0.9, 0.95),
        ),
        _scenario(
            "G",
            ScenarioExpectation.AMBIGUOUS,
            _offset(0, 0.5, 0.6),
        ),
        _scenario(
            "H",
            ScenarioExpectation.INSUFFICIENT,
            _offset(0, 0.7, 0.8),
        ),
    ]

    labels, scores, weights, scenarios = _threshold_samples(observations)

    assert scenarios == ["A", "B"]
    assert labels == [1, 1, 0, 0]
    assert scores == pytest.approx([0.8, 0.9, 0.1, 0.2])
    assert weights == pytest.approx([0.5, 0.5, 0.5, 0.5])
