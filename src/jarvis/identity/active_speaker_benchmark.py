"""Step 3B.11 LR-ASD score-distribution bake-off on canonical JARVIS sensors."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.active_speaker import (
    LR_ASD_PROVIDER_ID,
    LR_ASD_SOURCE_COMMIT,
    ActiveSpeakerAssessment,
    ActiveSpeakerState,
    ActiveSpeakerVisualBuffer,
    ActiveSpeakerVisualWindow,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.owner_context import (
    OwnerContextState,
    build_default_owner_context_observer,
)
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture, SpeakerTurnAudio
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime
from jarvis.voice.observed_audio import ObservedSessionAudioInput
from jarvis.voice.scripted_speech import ScriptedSpeech, build_scripted_speech

_DEFAULT_SECONDS = 4.0
_DEFAULT_OWNER_WAIT_SECONDS = 15.0
_DEFAULT_OFFSET_MS = (-300, -200, -100, 0, 100, 200, 300)
_JARVIS_PLAYBACK_SCRIPT = "This is a JARVIS playback-only active speaker test."


class ScenarioExpectation(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    key: str
    name: str
    expectation: ScenarioExpectation
    instructions: str
    automatic_playback: bool = False


SCENARIOS = (
    ScenarioSpec(
        "A",
        "owner-visible-owner-speaks",
        ScenarioExpectation.POSITIVE,
        "OWNER stays visible and speaks naturally for the whole capture.",
    ),
    ScenarioSpec(
        "B",
        "owner-visible-off-camera-speech",
        ScenarioExpectation.NEGATIVE,
        "OWNER stays visible and silent while TV/off-camera speech is clearly audible.",
    ),
    ScenarioSpec(
        "C",
        "owner-visible-jarvis-playback-only",
        ScenarioExpectation.NEGATIVE,
        (
            "OWNER stays visible and silent. The harness will play JARVIS through "
            "the accepted output/AEC path."
        ),
        automatic_playback=True,
    ),
    ScenarioSpec(
        "D",
        "owner-visible-owner-replay",
        ScenarioExpectation.NEGATIVE,
        (
            "OWNER stays visible and silent while a recording of OWNER speech "
            "plays from another device."
        ),
    ),
    ScenarioSpec(
        "E",
        "owner-and-other-visible-owner-speaks",
        ScenarioExpectation.POSITIVE,
        (
            "OWNER and one other person are visible; OWNER speaks while the other "
            "person stays silent."
        ),
    ),
    ScenarioSpec(
        "F",
        "owner-and-other-visible-other-speaks",
        ScenarioExpectation.NEGATIVE,
        (
            "OWNER and one other person are visible; OWNER stays silent while the "
            "other person speaks."
        ),
    ),
    ScenarioSpec(
        "G",
        "overlapping-speech",
        ScenarioExpectation.AMBIGUOUS,
        (
            "OWNER speaks while another person/TV speech overlaps. This scenario "
            "must remain fail-closed."
        ),
    ),
    ScenarioSpec(
        "H",
        "temporary-owner-head-loss",
        ScenarioExpectation.INSUFFICIENT,
        (
            "OWNER speaks continuously; during the middle, hide/occlude the OWNER "
            "head for about 0.6-0.8s, then return."
        ),
    ),
)

_SCENARIO_BY_KEY = {scenario.key: scenario for scenario in SCENARIOS}
_BINARY_LABELS = {"A": 1, "B": 0, "C": 0, "D": 0, "E": 1, "F": 0}


@dataclass(frozen=True, slots=True)
class OffsetObservation:
    offset_ms: int
    state: str
    reason_codes: tuple[str, ...]
    frame_scores: tuple[float, ...]
    mean_score: float | None
    median_score: float | None
    minimum_score: float | None
    maximum_score: float | None
    visual_frames: int
    unique_visual_frames: int
    source_fps: float | None
    maximum_source_gap_seconds: float | None
    inference_wall_ms: float | None
    cuda_kernel_ms: float | None
    gpu_baseline_allocated_bytes: int | None
    gpu_peak_allocated_bytes: int | None
    gpu_peak_delta_bytes: int | None
    process_cpu_seconds: float | None
    process_rss_before_bytes: int | None
    process_rss_after_bytes: int | None


@dataclass(frozen=True, slots=True)
class ScenarioObservation:
    key: str
    name: str
    expectation: ScenarioExpectation
    status: str
    captured_seconds: float | None
    speech_seconds: float | None
    speech_segments: int
    max_vad_probability: float | None
    quality_accepted: bool | None
    quality_reason_codes: tuple[str, ...]
    owner_track_id: int | None
    windows_session_id: str | None
    owner_context_fresh_after: bool
    owner_context_invalidation_after: str | None
    offsets: tuple[OffsetObservation, ...]
    notes: tuple[str, ...]


class _NoOpWakeDetector:
    """Satisfy the audio runtime contract without opening a wake session."""

    def enable(self) -> None:
        return None

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer

    def feed(self, frame: Any) -> None:
        del frame

    async def aclose(self) -> None:
        return None


class _TraceLrAsdProvider(LrAsdActiveSpeakerProvider):
    """Benchmark-only instrumentation that captures the exact LR-ASD frame trace.

    Production inference remains untouched. The diagnostic subclass intercepts the
    already-computed multicontext probabilities instead of duplicating LR-ASD's
    frontend or model implementation.
    """

    def __init__(self, model_path: str | Path, *, device: str | None = None) -> None:
        super().__init__(model_path, device=device)
        self._captured_trace = np.empty(0, dtype=np.float32)

    def assess_with_trace(
        self,
        turn: SpeakerTurnAudio,
        visual: ActiveSpeakerVisualWindow,
        *,
        audio_turn_id: str,
        windows_session_id: str,
    ) -> tuple[ActiveSpeakerAssessment, tuple[float, ...]]:
        self._captured_trace = np.empty(0, dtype=np.float32)
        assessment = super().assess(
            turn,
            visual,
            audio_turn_id=audio_turn_id,
            windows_session_id=windows_session_id,
        )
        trace = tuple(float(value) for value in self._captured_trace)
        return assessment, trace

    def _multicontext_probabilities(
        self,
        features: np.ndarray,
        visual_frames: np.ndarray,
        *,
        source_fps: float,
    ) -> np.ndarray:
        values = super()._multicontext_probabilities(
            features,
            visual_frames,
            source_fps=source_fps,
        )
        self._captured_trace = values.copy()
        return values


def _parse_offsets(value: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "offsets must be comma-separated integers"
        ) from exc
    if not values:
        raise argparse.ArgumentTypeError("at least one offset is required")
    if 0 not in values:
        raise argparse.ArgumentTypeError("offset sweep must include 0 ms")
    if any(abs(item) > 1_000 for item in values):
        raise argparse.ArgumentTypeError("offset magnitude must not exceed 1000 ms")
    return tuple(sorted(set(values)))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Step 3B.11 LR-ASD A-H bake-off on canonical LiveKit PCM and "
            "the existing timestamped JARVIS Vision owner track."
        )
    )
    parser.add_argument("--seconds", type=float, default=_DEFAULT_SECONDS)
    parser.add_argument(
        "--offsets-ms",
        type=_parse_offsets,
        default=_DEFAULT_OFFSET_MS,
        help="Comma-separated AV visual-source offsets; must include 0.",
    )
    parser.add_argument(
        "--owner-wait-seconds",
        type=float,
        default=_DEFAULT_OWNER_WAIT_SECONDS,
    )
    parser.add_argument(
        "--device",
        default=None,
        help="LR-ASD torch device override, e.g. cuda or cpu.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="Override the configured pinned LR-ASD model path.",
    )
    parser.add_argument("--input-device", default=None)
    parser.add_argument("--output-device", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("step3b11_lr_asd_bakeoff.json"),
        help="Derived-score JSON only; raw audio/video is never written.",
    )
    return parser


def _require_benchmark_dependencies() -> None:
    missing: list[str] = []
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    if missing:
        raise RuntimeError(
            "Step 3B.11 benchmark dependencies are missing: "
            + ", ".join(missing)
            + ". Install with: pip install -e .[vision,active-speaker-benchmark]"
        )


def _shifted_visual_window(
    visual_buffer: ActiveSpeakerVisualBuffer,
    *,
    visual_track_id: int,
    start_monotonic: float,
    end_monotonic: float,
    offset_seconds: float,
) -> ActiveSpeakerVisualWindow | None:
    """Select shifted source frames, then map their interval back to audio time."""
    shifted = visual_buffer.build_window(
        visual_track_id=visual_track_id,
        start_monotonic=start_monotonic + offset_seconds,
        end_monotonic=end_monotonic + offset_seconds,
    )
    if shifted is None:
        return None
    return replace(
        shifted,
        start_monotonic=shifted.start_monotonic - offset_seconds,
        end_monotonic=shifted.end_monotonic - offset_seconds,
    )


def _empty_offset(offset_ms: int, reason: str) -> OffsetObservation:
    return OffsetObservation(
        offset_ms=offset_ms,
        state=ActiveSpeakerState.INSUFFICIENT.value,
        reason_codes=(reason,),
        frame_scores=(),
        mean_score=None,
        median_score=None,
        minimum_score=None,
        maximum_score=None,
        visual_frames=0,
        unique_visual_frames=0,
        source_fps=None,
        maximum_source_gap_seconds=None,
        inference_wall_ms=None,
        cuda_kernel_ms=None,
        gpu_baseline_allocated_bytes=None,
        gpu_peak_allocated_bytes=None,
        gpu_peak_delta_bytes=None,
        process_cpu_seconds=None,
        process_rss_before_bytes=None,
        process_rss_after_bytes=None,
    )


def _score_with_telemetry(
    provider: _TraceLrAsdProvider,
    turn: SpeakerTurnAudio,
    visual: ActiveSpeakerVisualWindow,
    *,
    audio_turn_id: str,
    windows_session_id: str,
    offset_ms: int,
) -> OffsetObservation:
    import psutil
    import torch

    process = psutil.Process()
    cpu_before = process.cpu_times()
    cpu_seconds_before = float(cpu_before.user + cpu_before.system)
    rss_before = int(process.memory_info().rss)

    cuda_kernel_ms: float | None = None
    gpu_baseline: int | None = None
    gpu_peak: int | None = None
    gpu_peak_delta: int | None = None
    start_event = None
    end_event = None
    if provider.device.type == "cuda":
        torch.cuda.synchronize(provider.device)
        gpu_baseline = int(torch.cuda.memory_allocated(provider.device))
        torch.cuda.reset_peak_memory_stats(provider.device)
        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        start_event.record()

    started = time.perf_counter()
    assessment, trace = provider.assess_with_trace(
        turn,
        visual,
        audio_turn_id=audio_turn_id,
        windows_session_id=windows_session_id,
    )

    if provider.device.type == "cuda":
        assert start_event is not None and end_event is not None
        end_event.record()
        torch.cuda.synchronize(provider.device)
        cuda_kernel_ms = float(start_event.elapsed_time(end_event))
        gpu_peak = int(torch.cuda.max_memory_allocated(provider.device))
        assert gpu_baseline is not None
        gpu_peak_delta = max(0, gpu_peak - gpu_baseline)

    wall_ms = (time.perf_counter() - started) * 1000.0
    cpu_after = process.cpu_times()
    cpu_seconds_after = float(cpu_after.user + cpu_after.system)
    rss_after = int(process.memory_info().rss)

    return OffsetObservation(
        offset_ms=offset_ms,
        state=assessment.state.value,
        reason_codes=assessment.reason_codes,
        frame_scores=trace,
        mean_score=assessment.mean_score,
        median_score=assessment.median_score,
        minimum_score=assessment.minimum_score,
        maximum_score=assessment.maximum_score,
        visual_frames=assessment.visual_frames,
        unique_visual_frames=assessment.unique_visual_frames,
        source_fps=visual.source_fps,
        maximum_source_gap_seconds=visual.maximum_source_gap_seconds,
        inference_wall_ms=wall_ms,
        cuda_kernel_ms=cuda_kernel_ms,
        gpu_baseline_allocated_bytes=gpu_baseline,
        gpu_peak_allocated_bytes=gpu_peak,
        gpu_peak_delta_bytes=gpu_peak_delta,
        process_cpu_seconds=max(0.0, cpu_seconds_after - cpu_seconds_before),
        process_rss_before_bytes=rss_before,
        process_rss_after_bytes=rss_after,
    )


async def _drain_audio(source: ObservedSessionAudioInput) -> None:
    async for _ in source:
        pass


async def _wait_for_live_owner(
    state: OwnerContextState,
    *,
    timeout_seconds: float,
) -> tuple[int, str] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = state.snapshot()
        assessment = snapshot.assessment
        if assessment is not None and state.has_fresh_live_owner_candidate():
            return assessment.visual_track_id, assessment.session_id
        await asyncio.sleep(0.1)
    return None


async def _wait_for_expected_owner(
    state: OwnerContextState,
    *,
    owner_track_id: int,
    windows_session_id: str,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = state.snapshot()
        assessment = snapshot.assessment
        if (
            assessment is not None
            and state.has_fresh_live_owner_candidate()
            and assessment.visual_track_id == owner_track_id
            and assessment.session_id == windows_session_id
        ):
            return True
        await asyncio.sleep(0.1)
    return False


async def _establish_owner_lock(
    state: OwnerContextState,
    vision_service: Any,
    *,
    timeout_seconds: float,
) -> tuple[int, str]:
    while True:
        command = await asyncio.to_thread(
            input,
            (
                "Stand alone, face Pocket3, and press Enter to establish the "
                "OWNER track (q to stop): "
            ),
        )
        if command.strip().casefold() in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        owner = await _wait_for_live_owner(state, timeout_seconds=timeout_seconds)
        if owner is None:
            snapshot = state.snapshot()
            print(
                "  OWNER context not ready: "
                f"{snapshot.invalidation_reason or 'no_live_owner_candidate'}"
            )
            continue
        locked = vision_service.lock_only_confirmed_person()
        if not locked.get("ok"):
            print(f"  Vision lock failed: {locked.get('reason', 'unknown')}")
            continue
        locked_track = int(locked["track_id"])
        if locked_track != owner[0]:
            print(
                f"  Lock/context mismatch: locked={locked_track}, "
                f"owner={owner[0]}; retrying."
            )
            vision_service.clear_target()
            continue
        return owner


async def _capture_scenario_audio(
    spec: ScenarioSpec,
    *,
    duration_seconds: float,
    turn_capture: InMemorySpeakerTurnCapture,
    scripted_speech: ScriptedSpeech | None,
    audio_output: Any,
) -> SpeakerTurnAudio | None:
    turn_capture.clear()
    print("  CAPTURING")
    started = time.monotonic()
    if spec.automatic_playback:
        if scripted_speech is None:
            raise RuntimeError("scripted JARVIS speech is unavailable")
        await asyncio.sleep(0.20)
        await scripted_speech.speak(audio_output, _JARVIS_PLAYBACK_SCRIPT)
    elapsed = time.monotonic() - started
    if elapsed < duration_seconds:
        await asyncio.sleep(duration_seconds - elapsed)
    return turn_capture.snapshot_recent_audio(clear=True)


async def _run_one_scenario(
    spec: ScenarioSpec,
    *,
    duration_seconds: float,
    offsets_ms: tuple[int, ...],
    owner_track_id: int,
    windows_session_id: str,
    owner_wait_seconds: float,
    owner_state: OwnerContextState,
    visual_buffer: ActiveSpeakerVisualBuffer,
    turn_capture: InMemorySpeakerTurnCapture,
    speech_detector: LiveKitSileroSpeechRegionDetector,
    provider: _TraceLrAsdProvider,
    scripted_speech: ScriptedSpeech | None,
    audio_output: Any,
) -> ScenarioObservation:
    print()
    print(f"{spec.key}. {spec.name}")
    print(f"  Expected: {spec.expectation.value.upper()}")
    print(f"  Setup: {spec.instructions}")
    command = await asyncio.to_thread(input, "  Enter=run, s=skip, q=finish > ")
    normalized = command.strip().casefold()
    if normalized in {"q", "quit", "exit"}:
        raise EOFError
    if normalized in {"s", "skip"}:
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="skipped",
            captured_seconds=None,
            speech_seconds=None,
            speech_segments=0,
            max_vad_probability=None,
            quality_accepted=None,
            quality_reason_codes=(),
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=owner_state.has_fresh_live_owner_candidate(),
            owner_context_invalidation_after=owner_state.snapshot().invalidation_reason,
            offsets=(),
            notes=("scenario_skipped_by_operator",),
        )

    before = owner_state.snapshot()
    assessment = before.assessment
    already_ready = bool(
        assessment is not None
        and owner_state.has_fresh_live_owner_candidate()
        and assessment.visual_track_id == owner_track_id
        and assessment.session_id == windows_session_id
    )
    if not already_ready:
        print(
            f"  Waiting up to {owner_wait_seconds:.1f}s for fresh locked OWNER context..."
        )
        already_ready = await _wait_for_expected_owner(
            owner_state,
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            timeout_seconds=owner_wait_seconds,
        )
        before = owner_state.snapshot()

    if not already_ready:
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="precondition_failed",
            captured_seconds=None,
            speech_seconds=None,
            speech_segments=0,
            max_vad_probability=None,
            quality_accepted=None,
            quality_reason_codes=(),
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=False,
            owner_context_invalidation_after=before.invalidation_reason,
            offsets=(),
            notes=("fresh_locked_owner_context_required_at_scenario_start",),
        )

    try:
        turn = await _capture_scenario_audio(
            spec,
            duration_seconds=duration_seconds,
            turn_capture=turn_capture,
            scripted_speech=scripted_speech,
            audio_output=audio_output,
        )
    except (RuntimeError, TimeoutError) as exc:
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="capture_failed",
            captured_seconds=None,
            speech_seconds=None,
            speech_segments=0,
            max_vad_probability=None,
            quality_accepted=None,
            quality_reason_codes=(),
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=owner_state.has_fresh_live_owner_candidate(),
            owner_context_invalidation_after=owner_state.snapshot().invalidation_reason,
            offsets=(),
            notes=(f"capture_failed:{type(exc).__name__}:{exc}",),
        )

    if turn is None:
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="capture_failed",
            captured_seconds=None,
            speech_seconds=None,
            speech_segments=0,
            max_vad_probability=None,
            quality_accepted=None,
            quality_reason_codes=(),
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=owner_state.has_fresh_live_owner_candidate(),
            owner_context_invalidation_after=owner_state.snapshot().invalidation_reason,
            offsets=(),
            notes=("canonical_audio_capture_empty",),
        )

    region = await speech_detector.extract(turn)
    after = owner_state.snapshot()
    owner_fresh_after = owner_state.has_fresh_live_owner_candidate()
    if region.turn is None:
        note = "canonical_silero_found_no_speech"
        if spec.key == "C":
            note = "jarvis_playback_removed_or_below_speech_gate"
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="no_speech",
            captured_seconds=turn.duration_seconds,
            speech_seconds=None,
            speech_segments=region.segment_count,
            max_vad_probability=region.max_vad_probability,
            quality_accepted=False,
            quality_reason_codes=(),
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=owner_fresh_after,
            owner_context_invalidation_after=after.invalidation_reason,
            offsets=(),
            notes=(note, region.reason),
        )

    analysis_turn = region.turn
    quality = await asyncio.to_thread(
        assess_speaker_segment,
        analysis_turn.samples,
        sample_rate=analysis_turn.sample_rate,
    )
    if not quality.accepted:
        return ScenarioObservation(
            key=spec.key,
            name=spec.name,
            expectation=spec.expectation,
            status="quality_rejected",
            captured_seconds=turn.duration_seconds,
            speech_seconds=analysis_turn.duration_seconds,
            speech_segments=region.segment_count,
            max_vad_probability=region.max_vad_probability,
            quality_accepted=False,
            quality_reason_codes=quality.reason_codes,
            owner_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            owner_context_fresh_after=owner_fresh_after,
            owner_context_invalidation_after=after.invalidation_reason,
            offsets=(),
            notes=(region.reason,),
        )

    max_positive_offset = max(0.0, max(offsets_ms) / 1000.0)
    if max_positive_offset:
        await asyncio.sleep(max_positive_offset + 0.20)

    assert analysis_turn.start_monotonic is not None
    assert analysis_turn.end_monotonic is not None
    offset_observations: list[OffsetObservation] = []
    for offset_ms in offsets_ms:
        visual = _shifted_visual_window(
            visual_buffer,
            visual_track_id=owner_track_id,
            start_monotonic=analysis_turn.start_monotonic,
            end_monotonic=analysis_turn.end_monotonic,
            offset_seconds=offset_ms / 1000.0,
        )
        if visual is None:
            offset_observations.append(
                _empty_offset(offset_ms, "active_speaker_visual_window_insufficient")
            )
            continue
        observation = await asyncio.to_thread(
            _score_with_telemetry,
            provider,
            analysis_turn,
            visual,
            audio_turn_id=f"3b11-{spec.key}-{uuid.uuid4()}",
            windows_session_id=windows_session_id,
            offset_ms=offset_ms,
        )
        offset_observations.append(observation)
        mean_text = (
            f"{observation.mean_score:.4f}"
            if observation.mean_score is not None
            else "n/a"
        )
        print(
            f"  offset {offset_ms:+d} ms | {observation.state} | "
            f"frames={len(observation.frame_scores)} | mean={mean_text} | "
            f"wall={observation.inference_wall_ms:.1f} ms"
        )

    zero = next((item for item in offset_observations if item.offset_ms == 0), None)
    status = "scored" if zero is not None and zero.state == "scored" else "insufficient"
    notes = [region.reason]
    if spec.expectation is ScenarioExpectation.AMBIGUOUS:
        notes.append("excluded_from_binary_threshold_analysis")
    if spec.expectation is ScenarioExpectation.INSUFFICIENT:
        notes.append("expected_to_fail_closed_on_visual_continuity")

    return ScenarioObservation(
        key=spec.key,
        name=spec.name,
        expectation=spec.expectation,
        status=status,
        captured_seconds=turn.duration_seconds,
        speech_seconds=analysis_turn.duration_seconds,
        speech_segments=region.segment_count,
        max_vad_probability=region.max_vad_probability,
        quality_accepted=True,
        quality_reason_codes=quality.reason_codes,
        owner_track_id=owner_track_id,
        windows_session_id=windows_session_id,
        owner_context_fresh_after=owner_fresh_after,
        owner_context_invalidation_after=after.invalidation_reason,
        offsets=tuple(offset_observations),
        notes=tuple(notes),
    )


def _threshold_samples(
    observations: list[ScenarioObservation],
) -> tuple[list[int], list[float], list[float], list[str]]:
    labels: list[int] = []
    scores: list[float] = []
    weights: list[float] = []
    scenarios_used: list[str] = []
    for observation in observations:
        label = _BINARY_LABELS.get(observation.key)
        if label is None:
            continue
        zero = next((item for item in observation.offsets if item.offset_ms == 0), None)
        if zero is None or zero.state != ActiveSpeakerState.SCORED.value:
            continue
        finite_scores = [value for value in zero.frame_scores if math.isfinite(value)]
        if not finite_scores:
            continue
        scenarios_used.append(observation.key)
        scenario_weight = 1.0 / len(finite_scores)
        labels.extend([label] * len(finite_scores))
        scores.extend(finite_scores)
        weights.extend([scenario_weight] * len(finite_scores))
    return labels, scores, weights, scenarios_used


def _threshold_analysis(observations: list[ScenarioObservation]) -> dict[str, Any]:
    from sklearn.metrics import precision_recall_curve

    labels, scores, weights, scenarios_used = _threshold_samples(observations)
    positive_scenarios = [key for key in scenarios_used if _BINARY_LABELS[key] == 1]
    negative_scenarios = [key for key in scenarios_used if _BINARY_LABELS[key] == 0]
    base: dict[str, Any] = {
        "method": "sklearn.metrics.precision_recall_curve",
        "zero_offset_only": True,
        "scenario_balanced_frame_weights": True,
        "scenarios_used": scenarios_used,
        "positive_scenarios": positive_scenarios,
        "negative_scenarios": negative_scenarios,
        "frame_samples": len(scores),
        "deployment_threshold_selected": False,
        "warning": (
            "Exploratory only: frame scores inside one capture are temporally "
            "correlated. A-H is the first real distribution, not deployment "
            "calibration."
        ),
    }
    if not positive_scenarios or not negative_scenarios:
        base["status"] = "insufficient_binary_scenarios"
        base["operating_points"] = []
        return base

    precision, recall, thresholds = precision_recall_curve(
        np.asarray(labels, dtype=np.int8),
        np.asarray(scores, dtype=np.float64),
        sample_weight=np.asarray(weights, dtype=np.float64),
    )
    points: list[dict[str, float]] = []
    best_f1: dict[str, float] | None = None
    precision_99: dict[str, float] | None = None
    for index, threshold in enumerate(thresholds):
        p = float(precision[index])
        r = float(recall[index])
        f1 = 0.0 if p + r <= 0 else 2.0 * p * r / (p + r)
        point = {
            "threshold": float(threshold),
            "precision": p,
            "recall": r,
            "f1": f1,
        }
        points.append(point)
        if best_f1 is None or point["f1"] > best_f1["f1"]:
            best_f1 = point
        if p >= 0.99 and r > 0 and (precision_99 is None or r > precision_99["recall"]):
            precision_99 = point

    base.update(
        {
            "status": "exploratory_curve_ready",
            "operating_points": points,
            "exploratory_best_f1": best_f1,
            "exploratory_precision_at_least_0_99": precision_99,
        }
    )
    return base


def _scenario_summary(observation: ScenarioObservation) -> str:
    zero = next((item for item in observation.offsets if item.offset_ms == 0), None)
    if zero is None or not zero.frame_scores:
        return f"{observation.key}: {observation.status}"
    values = list(zero.frame_scores)
    return (
        f"{observation.key}: n={len(values)} mean={statistics.mean(values):.4f} "
        f"median={statistics.median(values):.4f} min={min(values):.4f} "
        f"max={max(values):.4f}"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _build_report(
    *,
    provider: _TraceLrAsdProvider,
    offsets_ms: tuple[int, ...],
    observations: list[ScenarioObservation],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "step": "3B.11",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "provider_id": LR_ASD_PROVIDER_ID,
        "lr_asd_source_commit": LR_ASD_SOURCE_COMMIT,
        "device": str(provider.device),
        "offset_sweep_ms": list(offsets_ms),
        "scenarios": [asdict(item) for item in observations],
        "threshold_analysis": _threshold_analysis(observations),
        "safety": {
            "raw_audio_persisted": False,
            "raw_video_persisted": False,
            "face_crops_persisted": False,
            "active_speaker_confirmed": False,
            "prototype_admission_enabled": False,
            "t2_enabled": False,
            "deployment_threshold_selected": False,
        },
    }


async def run_active_speaker_benchmark(args: argparse.Namespace) -> int:
    _require_benchmark_dependencies()
    if not math.isfinite(args.seconds) or not 1.0 <= args.seconds <= 10.0:
        raise ValueError("seconds must be finite and in [1, 10]")
    if (
        not math.isfinite(args.owner_wait_seconds)
        or args.owner_wait_seconds <= 0
        or args.owner_wait_seconds > 60
    ):
        raise ValueError("owner-wait-seconds must be >0 and <=60")

    config = JarvisConfig.from_environment()
    if not config.vision_enabled:
        raise RuntimeError("Step 3B.11 benchmark requires JARVIS Vision to be enabled")
    model_path = args.model or config.active_speaker_model_path
    if model_path is None:
        raise RuntimeError("No LR-ASD model configured; run jarvis-setup first")

    os.environ.setdefault("JARVIS_VISION_PREVIEW", "true")
    owner_observer = build_default_owner_context_observer()
    owner_state = owner_observer.state
    max_offset_seconds = max(abs(value) for value in args.offsets_ms) / 1000.0
    visual_buffer = ActiveSpeakerVisualBuffer(
        max_seconds=max(12.0, args.seconds + max_offset_seconds + 2.0)
    )
    vision_service = build_default_vision_service(
        head_model_path=config.vision_head_model_path,
        evidence_observer=owner_observer,
        frame_pair_tap=visual_buffer.observe,
    )
    provider = _TraceLrAsdProvider(model_path, device=args.device)
    speech_detector = LiveKitSileroSpeechRegionDetector()
    turn_capture = InMemorySpeakerTurnCapture(
        max_turn_seconds=max(10.0, args.seconds + 4.0)
    )

    def on_audio_frame(frame: Any, observed_at_monotonic: float) -> None:
        turn_capture.push_frame(
            frame.data,
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=frame.samples_per_channel,
            observed_at_monotonic=observed_at_monotonic,
        )

    session_input = ObservedSessionAudioInput(on_audio_frame, capacity_frames=2_000)
    audio = MediaDevicesConversationRuntime(
        _NoOpWakeDetector(),  # type: ignore[arg-type]
        input_device_name=args.input_device or config.audio_input_device,
        output_device_name=args.output_device or config.audio_output_device,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=max(1.0, config.audio_ring_buffer_seconds),
    )
    consumer_task: asyncio.Task[None] | None = None
    scripted_speech: ScriptedSpeech | None = None
    observations: list[ScenarioObservation] = []
    vision_started = False

    print("JARVIS Step 3B.11 LR-ASD A-H bake-off")
    print("--------------------------------------")
    print(
        "DIAGNOSTIC ONLY: ACTIVE_OWNER_SPEAKER, prototype admission, and T2 stay OFF."
    )
    print("One Pocket3 microphone owner: LiveKit MediaDevices AEC/NS/HPF/AGC.")
    print("Vision uses the existing Pocket3 frame + locked OWNER track/head timeline.")
    print(
        "Raw audio/video/crops are memory-only; only derived scores/telemetry "
        "are saved."
    )
    print(f"AV offset sweep: {', '.join(f'{value:+d}ms' for value in args.offsets_ms)}")

    try:
        await asyncio.to_thread(vision_service.start)
        vision_started = True
        await audio.start()
        audio_output = audio.output
        if audio_output is None:
            raise RuntimeError("canonical LiveKit audio output did not start")
        consumer_task = asyncio.create_task(
            _drain_audio(session_input),
            name="jarvis-step3b11-audio-drain",
        )
        audio.activate_session(session_input)
        await asyncio.sleep(0.5)

        owner_track_id, windows_session_id = await _establish_owner_lock(
            owner_state,
            vision_service,
            timeout_seconds=args.owner_wait_seconds,
        )
        print(
            f"OWNER context established: session={windows_session_id}, "
            f"track={owner_track_id}."
        )

        for spec in SCENARIOS:
            if spec.automatic_playback and scripted_speech is None:
                scripted_speech = build_scripted_speech(config)
            try:
                observation = await _run_one_scenario(
                    spec,
                    duration_seconds=args.seconds,
                    offsets_ms=args.offsets_ms,
                    owner_track_id=owner_track_id,
                    windows_session_id=windows_session_id,
                    owner_wait_seconds=args.owner_wait_seconds,
                    owner_state=owner_state,
                    visual_buffer=visual_buffer,
                    turn_capture=turn_capture,
                    speech_detector=speech_detector,
                    provider=provider,
                    scripted_speech=scripted_speech,
                    audio_output=audio_output,
                )
            except EOFError:
                break
            observations.append(observation)
            print("  " + _scenario_summary(observation))
    finally:
        turn_capture.clear()
        visual_buffer.clear()
        audio.deactivate_session()
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        if scripted_speech is not None:
            await scripted_speech.aclose()
        await audio.aclose()
        if vision_started:
            await asyncio.to_thread(vision_service.stop)

    report = _build_report(
        provider=provider,
        offsets_ms=args.offsets_ms,
        observations=observations,
    )
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )

    print()
    print("ZERO-OFFSET DISTRIBUTIONS")
    for observation in observations:
        print("  " + _scenario_summary(observation))
    analysis = report["threshold_analysis"]
    print()
    print(f"Threshold analysis: {analysis['status']}")
    if analysis.get("exploratory_best_f1") is not None:
        candidate = analysis["exploratory_best_f1"]
        print(
            "Exploratory best-F1 point only: "
            f"threshold={candidate['threshold']:.4f}, "
            f"precision={candidate['precision']:.3f}, recall={candidate['recall']:.3f}"
        )
    print("DEPLOYMENT THRESHOLD SELECTED = FALSE")
    print("ACTIVE_OWNER_SPEAKER = DISABLED")
    print(f"Derived report: {output_path}")

    completed = {item.key for item in observations if item.status != "skipped"}
    required = {item.key for item in SCENARIOS}
    return 0 if completed == required else 2


def main() -> None:
    args = _build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(run_active_speaker_benchmark(args)))
    except KeyboardInterrupt:
        print("\nStep 3B.11 bake-off stopped; no raw biometric material was persisted.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
