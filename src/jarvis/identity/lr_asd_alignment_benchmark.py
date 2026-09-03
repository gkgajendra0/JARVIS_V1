from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.active_speaker import ActiveSpeakerState, ActiveSpeakerVisualBuffer
from jarvis.identity.active_speaker_benchmark import (
    _drain_audio,
    _establish_owner_lock,
    _NoOpWakeDetector,
    _shifted_visual_window,
    _TraceLrAsdProvider,
)
from jarvis.identity.lr_asd_turn_gate_benchmark import _slice_turn
from jarvis.identity.owner_context import build_default_owner_context_observer
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture, SpeakerTurnAudio
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime
from jarvis.voice.observed_audio import ObservedSessionAudioInput

_DEFAULT_PHASE_SECONDS = 6.0
_DEFAULT_SETTLE_SECONDS = 0.50
_DEFAULT_WINDOW_SECONDS = 1.0
_DEFAULT_STEP_SECONDS = 0.20
_DEFAULT_THRESHOLD = 0.50
_DEFAULT_TRAILING_FRAMES = 5
_DEFAULT_OWNER_WAIT_SECONDS = 15.0
_DEFAULT_OFFSETS_MS = tuple(range(-1000, 1001, 100))


@dataclass(frozen=True, slots=True)
class PhaseCapture:
    name: str
    turn: SpeakerTurnAudio
    started_at_monotonic: float
    ended_at_monotonic: float


@dataclass(frozen=True, slots=True)
class PhaseAudioProof:
    name: str
    captured_seconds: float
    rms_dbfs: float
    speech_seconds: float
    speech_fraction: float
    speech_segments: int
    max_vad_probability: float | None
    vad_reason: str


@dataclass(frozen=True, slots=True)
class OffsetPhaseScore:
    offset_ms: int
    phase: str
    state: str
    mean_score: float | None
    median_score: float | None
    activity_fraction: float | None
    trace_frames: int
    inference_ms: float | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OffsetComparison:
    offset_ms: int
    phone: OffsetPhaseScore
    owner: OffsetPhaseScore
    median_separation: float | None


@dataclass(frozen=True, slots=True)
class SlidingSummary:
    phase: str
    offset_ms: int
    scored_windows: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    active_fraction: float | None


@dataclass(frozen=True, slots=True)
class PhaseEvidence:
    proof: PhaseAudioProof
    offsets: tuple[OffsetPhaseScore, ...]
    zero_sliding: SlidingSummary


def _parse_offsets(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "offsets must be comma-separated integers"
        ) from exc
    if not parsed:
        raise argparse.ArgumentTypeError("at least one AV offset is required")
    if 0 not in parsed:
        raise argparse.ArgumentTypeError("AV offset sweep must include 0 ms")
    if any(abs(item) > 2_000 for item in parsed):
        raise argparse.ArgumentTypeError("AV offset magnitude must not exceed 2000 ms")
    return tuple(sorted(set(parsed)))


def _rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return float("-inf")
    normalized = samples.astype(np.float64, copy=False) / 32768.0
    rms = float(np.sqrt(np.mean(np.square(normalized))))
    if not math.isfinite(rms) or rms <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(rms)


def _trace_activity_fraction(
    trace: tuple[float, ...],
    *,
    threshold: float,
) -> float | None:
    if not trace:
        return None
    return sum(value >= threshold for value in trace) / len(trace)


def _best_offset(comparisons: list[OffsetComparison]) -> OffsetComparison | None:
    usable = [
        item
        for item in comparisons
        if item.median_separation is not None
        and item.phone.state == ActiveSpeakerState.SCORED.value
        and item.owner.state == ActiveSpeakerState.SCORED.value
    ]
    if not usable:
        return None
    return max(
        usable,
        key=lambda item: (
            item.median_separation,
            -(item.phone.median_score or 0.0),
            -abs(item.offset_ms),
        ),
    )


def _window_end_times(
    *,
    start_monotonic: float,
    end_monotonic: float,
    settle_seconds: float,
    window_seconds: float,
    step_seconds: float,
) -> tuple[float, ...]:
    first_end = start_monotonic + settle_seconds + window_seconds
    last_end = end_monotonic - settle_seconds
    if first_end > last_end + 1e-9:
        return ()
    values: list[float] = []
    end_time = first_end
    while end_time <= last_end + 1e-9:
        values.append(end_time)
        end_time += step_seconds
    return tuple(values)


async def _capture_phase(
    turn_capture: InMemorySpeakerTurnCapture,
    *,
    name: str,
    seconds: float,
) -> PhaseCapture:
    turn_capture.clear()
    started = time.monotonic()
    print(f"  >>> {name} ({seconds:.1f}s) <<<", flush=True)
    await asyncio.sleep(seconds)
    ended = time.monotonic()
    captured = turn_capture.snapshot_recent_audio(clear=True)
    if captured is None:
        raise RuntimeError(f"{name} canonical audio capture was empty")
    phase_turn = _slice_turn(
        captured,
        start_monotonic=started,
        end_monotonic=ended,
    )
    if phase_turn is None:
        raise RuntimeError(f"{name} canonical audio interval could not be sliced")
    return PhaseCapture(
        name=name,
        turn=phase_turn,
        started_at_monotonic=started,
        ended_at_monotonic=ended,
    )


async def _audio_proof(
    capture: PhaseCapture,
    detector: LiveKitSileroSpeechRegionDetector,
) -> PhaseAudioProof:
    region = await detector.extract(capture.turn)
    speech_seconds = 0.0 if region.turn is None else region.turn.duration_seconds
    captured_seconds = capture.turn.duration_seconds
    return PhaseAudioProof(
        name=capture.name,
        captured_seconds=captured_seconds,
        rms_dbfs=_rms_dbfs(capture.turn.samples),
        speech_seconds=speech_seconds,
        speech_fraction=(
            0.0 if captured_seconds <= 0 else speech_seconds / captured_seconds
        ),
        speech_segments=region.segment_count,
        max_vad_probability=region.max_vad_probability,
        vad_reason=region.reason,
    )


async def _score_phase_offset(
    provider: _TraceLrAsdProvider,
    visual_buffer: ActiveSpeakerVisualBuffer,
    capture: PhaseCapture,
    *,
    visual_track_id: int,
    windows_session_id: str,
    offset_ms: int,
    threshold: float,
    analysis_margin_seconds: float,
) -> OffsetPhaseScore:
    start = capture.started_at_monotonic + analysis_margin_seconds
    end = capture.ended_at_monotonic - analysis_margin_seconds
    analysis_turn = _slice_turn(
        capture.turn,
        start_monotonic=start,
        end_monotonic=end,
    )
    if analysis_turn is None:
        return OffsetPhaseScore(
            offset_ms=offset_ms,
            phase=capture.name,
            state=ActiveSpeakerState.INSUFFICIENT.value,
            mean_score=None,
            median_score=None,
            activity_fraction=None,
            trace_frames=0,
            inference_ms=None,
            reason_codes=("settled_audio_window_insufficient",),
        )
    visual = _shifted_visual_window(
        visual_buffer,
        visual_track_id=visual_track_id,
        start_monotonic=start,
        end_monotonic=end,
        offset_seconds=offset_ms / 1000.0,
    )
    if visual is None:
        return OffsetPhaseScore(
            offset_ms=offset_ms,
            phase=capture.name,
            state=ActiveSpeakerState.INSUFFICIENT.value,
            mean_score=None,
            median_score=None,
            activity_fraction=None,
            trace_frames=0,
            inference_ms=None,
            reason_codes=("shifted_visual_window_insufficient",),
        )
    started = time.perf_counter()
    assessment, trace = await asyncio.to_thread(
        provider.assess_with_trace,
        analysis_turn,
        visual,
        audio_turn_id=f"lr-asd-align-{uuid.uuid4()}",
        windows_session_id=windows_session_id,
    )
    inference_ms = (time.perf_counter() - started) * 1000.0
    return OffsetPhaseScore(
        offset_ms=offset_ms,
        phase=capture.name,
        state=assessment.state.value,
        mean_score=assessment.mean_score,
        median_score=assessment.median_score,
        activity_fraction=_trace_activity_fraction(trace, threshold=threshold),
        trace_frames=len(trace),
        inference_ms=inference_ms,
        reason_codes=assessment.reason_codes,
    )


async def _score_sliding_summary(
    provider: _TraceLrAsdProvider,
    visual_buffer: ActiveSpeakerVisualBuffer,
    capture: PhaseCapture,
    *,
    visual_track_id: int,
    windows_session_id: str,
    offset_ms: int,
    threshold: float,
    trailing_frames: int,
    analysis_margin_seconds: float,
    window_seconds: float,
    step_seconds: float,
) -> SlidingSummary:
    scores: list[float] = []
    for end_time in _window_end_times(
        start_monotonic=capture.started_at_monotonic,
        end_monotonic=capture.ended_at_monotonic,
        settle_seconds=analysis_margin_seconds,
        window_seconds=window_seconds,
        step_seconds=step_seconds,
    ):
        start_time = end_time - window_seconds
        audio_window = _slice_turn(
            capture.turn,
            start_monotonic=start_time,
            end_monotonic=end_time,
        )
        visual = _shifted_visual_window(
            visual_buffer,
            visual_track_id=visual_track_id,
            start_monotonic=start_time,
            end_monotonic=end_time,
            offset_seconds=offset_ms / 1000.0,
        )
        if audio_window is None or visual is None:
            continue
        assessment, trace = await asyncio.to_thread(
            provider.assess_with_trace,
            audio_window,
            visual,
            audio_turn_id=f"lr-asd-align-slide-{uuid.uuid4()}",
            windows_session_id=windows_session_id,
        )
        if assessment.state != ActiveSpeakerState.SCORED or not trace:
            continue
        tail = trace[-min(trailing_frames, len(trace)) :]
        scores.append(float(statistics.median(tail)))

    if not scores:
        return SlidingSummary(
            phase=capture.name,
            offset_ms=offset_ms,
            scored_windows=0,
            mean=None,
            median=None,
            minimum=None,
            maximum=None,
            active_fraction=None,
        )
    return SlidingSummary(
        phase=capture.name,
        offset_ms=offset_ms,
        scored_windows=len(scores),
        mean=statistics.mean(scores),
        median=statistics.median(scores),
        minimum=min(scores),
        maximum=max(scores),
        active_fraction=sum(score >= threshold for score in scores) / len(scores),
    )


async def _score_phase_immediately(
    provider: _TraceLrAsdProvider,
    visual_buffer: ActiveSpeakerVisualBuffer,
    speech_detector: LiveKitSileroSpeechRegionDetector,
    capture: PhaseCapture,
    *,
    visual_track_id: int,
    windows_session_id: str,
    offsets_ms: tuple[int, ...],
    threshold: float,
    trailing_frames: int,
    analysis_margin_seconds: float,
    window_seconds: float,
    step_seconds: float,
) -> PhaseEvidence:
    print(f"  Scoring {capture.name} immediately while its Vision evidence is fresh...")
    offsets: list[OffsetPhaseScore] = []
    for offset_ms in offsets_ms:
        score = await _score_phase_offset(
            provider,
            visual_buffer,
            capture,
            visual_track_id=visual_track_id,
            windows_session_id=windows_session_id,
            offset_ms=offset_ms,
            threshold=threshold,
            analysis_margin_seconds=analysis_margin_seconds,
        )
        offsets.append(score)
        if score.state == ActiveSpeakerState.SCORED.value:
            print(
                f"    {offset_ms:+5d} ms | median={_format_score(score.median_score)} | "
                f"activity={_format_score(score.activity_fraction)}"
            )
        else:
            reasons = ",".join(score.reason_codes) if score.reason_codes else "none"
            print(f"    {offset_ms:+5d} ms | {score.state} | reasons={reasons}")

    zero_sliding = await _score_sliding_summary(
        provider,
        visual_buffer,
        capture,
        visual_track_id=visual_track_id,
        windows_session_id=windows_session_id,
        offset_ms=0,
        threshold=threshold,
        trailing_frames=trailing_frames,
        analysis_margin_seconds=analysis_margin_seconds,
        window_seconds=window_seconds,
        step_seconds=step_seconds,
    )
    proof = await _audio_proof(capture, speech_detector)
    return PhaseEvidence(
        proof=proof,
        offsets=tuple(offsets),
        zero_sliding=zero_sliding,
    )


def _print_audio_proof(proof: PhaseAudioProof) -> None:
    max_vad = (
        "n/a"
        if proof.max_vad_probability is None
        else f"{proof.max_vad_probability:.3f}"
    )
    print(
        f"  {proof.name}: captured={proof.captured_seconds:.2f}s | "
        f"rms={proof.rms_dbfs:.1f} dBFS | speech={proof.speech_seconds:.2f}s | "
        f"speech_fraction={proof.speech_fraction:.3f} | segments={proof.speech_segments} | "
        f"max_vad={max_vad} | {proof.vad_reason}"
    )


def _format_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _print_sliding(summary: SlidingSummary) -> None:
    print(
        f"  {summary.phase}@{summary.offset_ms:+d}ms: "
        f"windows={summary.scored_windows} | mean={_format_score(summary.mean)} | "
        f"median={_format_score(summary.median)} | min={_format_score(summary.minimum)} | "
        f"max={_format_score(summary.maximum)} | "
        f"active_fraction={_format_score(summary.active_fraction)}"
    )


def _offset_by_value(evidence: PhaseEvidence, offset_ms: int) -> OffsetPhaseScore:
    return next(item for item in evidence.offsets if item.offset_ms == offset_ms)


async def run_alignment_benchmark(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        print("This real-machine LR-ASD alignment benchmark currently targets Windows.")
        return 2
    for name, value in (
        ("phase-seconds", args.phase_seconds),
        ("settle-seconds", args.settle_seconds),
        ("window-seconds", args.window_seconds),
        ("step-seconds", args.step_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if args.window_seconds < 1.0:
        raise ValueError("LR-ASD alignment window must be at least 1.0 second")
    if args.step_seconds > args.window_seconds:
        raise ValueError("step-seconds must not exceed window-seconds")
    if not 1 <= args.trailing_frames <= 25:
        raise ValueError("trailing-frames must be in [1, 25]")
    if not 0.0 < args.threshold < 1.0:
        raise ValueError("diagnostic threshold must be in (0, 1)")

    maximum_offset_seconds = max(abs(value) for value in args.offsets_ms) / 1000.0
    analysis_margin_seconds = max(args.settle_seconds, maximum_offset_seconds)
    if args.phase_seconds <= 2 * analysis_margin_seconds + args.window_seconds:
        raise ValueError(
            "phase-seconds must exceed twice the AV analysis margin plus window-seconds"
        )

    config = JarvisConfig.from_environment()
    if not config.vision_enabled:
        raise RuntimeError("LR-ASD alignment benchmark requires JARVIS Vision")
    model_path = args.model or config.active_speaker_model_path
    if model_path is None:
        raise RuntimeError("No LR-ASD model configured; run jarvis-setup first")

    owner_observer = build_default_owner_context_observer()
    owner_state = owner_observer.state
    visual_buffer = ActiveSpeakerVisualBuffer(
        max_seconds=max(20.0, args.phase_seconds + 2 * maximum_offset_seconds + 4.0)
    )
    vision_service = build_default_vision_service(
        head_model_path=config.vision_head_model_path,
        evidence_observer=owner_observer,
        frame_pair_tap=visual_buffer.observe,
    )
    provider = _TraceLrAsdProvider(model_path, device=args.device)
    speech_detector = LiveKitSileroSpeechRegionDetector()
    turn_capture = InMemorySpeakerTurnCapture(max_turn_seconds=args.phase_seconds + 3.0)

    def on_audio_frame(frame: Any, observed_at_monotonic: float) -> None:
        turn_capture.push_frame(
            frame.data,
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=frame.samples_per_channel,
            observed_at_monotonic=observed_at_monotonic,
        )

    session_input = ObservedSessionAudioInput(on_audio_frame, capacity_frames=4_000)
    audio = MediaDevicesConversationRuntime(
        _NoOpWakeDetector(),  # type: ignore[arg-type]
        input_device_name=args.input_device or config.audio_input_device,
        output_device_name=args.output_device or config.audio_output_device,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=max(1.0, config.audio_ring_buffer_seconds),
    )

    consumer_task: asyncio.Task[None] | None = None
    vision_started = False
    audio_started = False
    phone_capture: PhaseCapture | None = None
    owner_capture: PhaseCapture | None = None
    phone_evidence: PhaseEvidence | None = None
    owner_evidence: PhaseEvidence | None = None

    print("JARVIS Step 3 LR-ASD AV-alignment diagnostic")
    print("-----------------------------------------------")
    print("DIAGNOSTIC ONLY: no threshold, prototype, T2, or authority change is made.")
    print(
        "Uses canonical LiveKit/WebRTC-processed Pocket3 PCM + existing Vision track."
    )
    print("Each phase is scored immediately before the operator changes scene state.")
    print("No raw audio/video/crops are persisted.")
    print(f"phase_seconds = {args.phase_seconds:.2f}")
    print(f"analysis_margin_seconds = {analysis_margin_seconds:.2f}")
    print(f"offsets_ms = {','.join(str(value) for value in args.offsets_ms)}")
    print(f"diagnostic_activity_threshold = {args.threshold:.3f}")

    try:
        await asyncio.to_thread(vision_service.start)
        vision_started = True
        await audio.start()
        audio_started = True
        consumer_task = asyncio.create_task(
            _drain_audio(session_input),
            name="jarvis-lr-asd-alignment-audio-drain",
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
        print()

        command = await asyncio.to_thread(
            input,
            (
                "Start continuous human speech on the phone, stay SILENT with your face "
                "visible, then press Enter (q to stop): "
            ),
        )
        if command.strip().casefold() in {"q", "quit", "exit"}:
            return 130
        phone_capture = await _capture_phase(
            turn_capture,
            name="PHONE_ONLY",
            seconds=args.phase_seconds,
        )
        phone_evidence = await _score_phase_immediately(
            provider,
            visual_buffer,
            speech_detector,
            phone_capture,
            visual_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            offsets_ms=args.offsets_ms,
            threshold=args.threshold,
            trailing_frames=args.trailing_frames,
            analysis_margin_seconds=analysis_margin_seconds,
            window_seconds=args.window_seconds,
            step_seconds=args.step_seconds,
        )
        phone_capture.turn.samples.fill(0)
        print("  PHONE_ONLY derived evidence retained; raw phase PCM cleared.")

        command = await asyncio.to_thread(
            input,
            (
                "STOP the phone. Stay visible and quiet. Press Enter when the room is "
                "quiet; then speak continuously only after the OWNER_ONLY cue: "
            ),
        )
        if command.strip().casefold() in {"q", "quit", "exit"}:
            return 130
        for value in (3, 2, 1):
            print(f"  {value}...", flush=True)
            await asyncio.sleep(1.0)
        owner_capture = await _capture_phase(
            turn_capture,
            name="OWNER_ONLY",
            seconds=args.phase_seconds,
        )
        print("  >>> STOP <<<", flush=True)
        owner_evidence = await _score_phase_immediately(
            provider,
            visual_buffer,
            speech_detector,
            owner_capture,
            visual_track_id=owner_track_id,
            windows_session_id=windows_session_id,
            offsets_ms=args.offsets_ms,
            threshold=args.threshold,
            trailing_frames=args.trailing_frames,
            analysis_margin_seconds=analysis_margin_seconds,
            window_seconds=args.window_seconds,
            step_seconds=args.step_seconds,
        )
        owner_capture.turn.samples.fill(0)
        print("  OWNER_ONLY derived evidence retained; raw phase PCM cleared.")

        print("\nCanonical phase audio proof")
        _print_audio_proof(phone_evidence.proof)
        _print_audio_proof(owner_evidence.proof)

        print("\nFull-phase AV offset comparison")
        comparisons: list[OffsetComparison] = []
        for offset_ms in args.offsets_ms:
            phone_score = _offset_by_value(phone_evidence, offset_ms)
            owner_score = _offset_by_value(owner_evidence, offset_ms)
            separation = (
                None
                if phone_score.median_score is None or owner_score.median_score is None
                else owner_score.median_score - phone_score.median_score
            )
            comparison = OffsetComparison(
                offset_ms=offset_ms,
                phone=phone_score,
                owner=owner_score,
                median_separation=separation,
            )
            comparisons.append(comparison)
            phone_reason = (
                ""
                if phone_score.state == ActiveSpeakerState.SCORED.value
                else f" [{','.join(phone_score.reason_codes) or 'no_reason'}]"
            )
            owner_reason = (
                ""
                if owner_score.state == ActiveSpeakerState.SCORED.value
                else f" [{','.join(owner_score.reason_codes) or 'no_reason'}]"
            )
            print(
                f"  {offset_ms:+5d} ms | phone med={_format_score(phone_score.median_score)}"
                f"{phone_reason} | owner med={_format_score(owner_score.median_score)}"
                f"{owner_reason} | separation={_format_score(separation)}"
            )

        best = _best_offset(comparisons)
        zero = next(item for item in comparisons if item.offset_ms == 0)
        print("\nAlignment summary")
        print(
            f"  zero_offset: phone_median={_format_score(zero.phone.median_score)} | "
            f"owner_median={_format_score(zero.owner.median_score)} | "
            f"separation={_format_score(zero.median_separation)}"
        )
        if best is None:
            print("  best_diagnostic_offset = n/a (insufficient scored evidence)")
        else:
            print(
                f"  best_diagnostic_offset = {best.offset_ms:+d} ms | "
                f"phone_median={_format_score(best.phone.median_score)} | "
                f"owner_median={_format_score(best.owner.median_score)} | "
                f"separation={_format_score(best.median_separation)}"
            )
        print(
            "  NOTE: best_diagnostic_offset is evidence only, not a production correction."
        )

        print("\nSettled 1-second gate evidence at canonical 0 ms")
        _print_sliding(phone_evidence.zero_sliding)
        _print_sliding(owner_evidence.zero_sliding)

        structural_candidate = bool(
            phone_evidence.proof.speech_fraction >= 0.20
            and owner_evidence.proof.speech_fraction >= 0.20
            and phone_evidence.zero_sliding.active_fraction is not None
            and owner_evidence.zero_sliding.active_fraction is not None
            and phone_evidence.zero_sliding.active_fraction <= 0.25
            and owner_evidence.zero_sliding.active_fraction >= 0.60
        )

        print("\nSafety disposition")
        print("  production_turn_gate_enabled = False")
        print("  LR_ASD_threshold_promoted = False")
        print("  AV_offset_promoted = False")
        print("  prototype_admission = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        print("  raw_video_saved = False")
        print(
            "STEP_3_LR_ASD_ALIGNMENT = "
            + ("DIAGNOSTIC_CANDIDATE" if structural_candidate else "NEEDS_REVIEW")
        )
        return 0
    finally:
        for capture in (phone_capture, owner_capture):
            if capture is not None:
                capture.turn.samples.fill(0)
        turn_capture.clear()
        visual_buffer.clear()
        if audio_started:
            audio.deactivate_session()
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        if audio_started:
            await audio.aclose()
        if vision_started:
            await asyncio.to_thread(vision_service.stop)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose LR-ASD canonical audio/vision alignment using isolated phone-only "
            "and OWNER-only phases plus an in-memory AV offset sweep."
        )
    )
    parser.add_argument("--phase-seconds", type=float, default=_DEFAULT_PHASE_SECONDS)
    parser.add_argument("--settle-seconds", type=float, default=_DEFAULT_SETTLE_SECONDS)
    parser.add_argument("--window-seconds", type=float, default=_DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--step-seconds", type=float, default=_DEFAULT_STEP_SECONDS)
    parser.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD)
    parser.add_argument("--trailing-frames", type=int, default=_DEFAULT_TRAILING_FRAMES)
    parser.add_argument(
        "--offsets-ms",
        type=_parse_offsets,
        default=_DEFAULT_OFFSETS_MS,
        help="Comma-separated visual-source offsets; must include 0 ms.",
    )
    parser.add_argument(
        "--owner-wait-seconds",
        type=float,
        default=_DEFAULT_OWNER_WAIT_SECONDS,
    )
    parser.add_argument("--device", default=None)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--input-device", default=None)
    parser.add_argument("--output-device", default=None)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        raise SystemExit(asyncio.run(run_alignment_benchmark(args)))
    except KeyboardInterrupt:
        print("\nLR-ASD alignment benchmark stopped; no raw media was persisted.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
