from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.owner_lane_benchmark import (
    _capture,
    _consume_frames,
    _live_inactive_ms,
    _live_onset_ms,
    _live_overlap_ms,
    _NoOpWakeDetector,
    _phase_windows,
    _run_persistent_stream,
    _score_phase,
)
from jarvis.identity.owner_lane_transition_benchmark import (
    _acoustic_inactive_ms,
    _active_fraction_after,
    _phase_mask,
)
from jarvis.identity.sortformer_assets import (
    SORTFORMER_MODEL_ID,
    SORTFORMER_MODEL_REVISION,
    SORTFORMER_MODEL_SHA256,
    SortformerAssetError,
    ensure_sortformer_model,
)
from jarvis.identity.sortformer_lane import LanePhase, summarize_phase
from jarvis.identity.sortformer_native import (
    NVIDIA_SORTFORMER_LOW_LATENCY,
    NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY,
    NativeSortformerDiarizer,
    SortformerGeometry,
    SortformerNativeError,
)
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder
from jarvis.identity.speaker_shadow import (
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_CAPTURE_SECONDS = 5.0
_DEFAULT_PUSH_SECONDS = 0.08
_DEFAULT_THRESHOLD = 0.5
_DEFAULT_INACTIVE_FRAMES = 3


@dataclass(frozen=True, slots=True)
class _Candidate:
    name: str
    geometry: SortformerGeometry | None
    input_buffer_ms: int


@dataclass(frozen=True, slots=True)
class _CandidateResult:
    name: str
    input_buffer_ms: int
    phone_lane: int
    owner_lane: int
    phone_lane_stable: bool
    owner_phone_lanes_distinct: bool
    overlap_concurrent_fraction: float
    owner_residual_total: float
    owner_residual_after_1s: float | None
    owner_residual_after_2s: float | None
    owner_residual_after_3s: float | None
    acoustic_owner_inactive_ms: float | None
    live_owner_inactive_ms: float | None
    overlap_visible_ms: float | None
    owner_reacquire_ms: float | None
    processing_ms: float
    realtime_factor: float
    push_median_ms: float
    push_p95_ms: float
    push_max_ms: float
    live_updates: int
    structural_pass: bool


_CANDIDATES = (
    _Candidate("default_streaming_1p60s", None, 1600),
    _Candidate(
        NVIDIA_SORTFORMER_LOW_LATENCY.name,
        NVIDIA_SORTFORMER_LOW_LATENCY,
        1040,
    ),
    _Candidate(
        NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY.name,
        NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY,
        320,
    ),
)


async def _capture_sequence(
    recorder: InMemorySegmentRecorder,
    *,
    capture_seconds: float,
) -> list[tuple[str, np.ndarray, int]]:
    scenarios = (
        (
            "B1_PHONE_ONLY",
            "Stay completely silent. Play continuous human speech from the phone at normal room volume.",
        ),
        (
            "G_OWNER_PLUS_PHONE",
            "Keep the SAME phone speech continuous and speak yourself at the same time for most of the capture.",
        ),
        (
            "B2_PHONE_ONLY",
            "Stop speaking yourself but KEEP the same phone speech continuous for the whole capture.",
        ),
        (
            "A_OWNER_ONLY",
            "Stop the phone completely. Speak naturally yourself for the whole capture.",
        ),
    )
    captures: list[tuple[str, np.ndarray, int]] = []
    for label, instructions in scenarios:
        samples, sample_rate = await _capture(
            recorder,
            label=label,
            instructions=instructions,
            duration_seconds=capture_seconds,
        )
        if captures and sample_rate != captures[0][2]:
            raise RuntimeError("canonical sample rate changed between captures")
        captures.append((label, samples, sample_rate))
    return captures


def _format_optional(value: float | None, *, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.3f}{suffix}"


def _evaluate_candidate(
    candidate: _Candidate,
    *,
    model_path: Path,
    library_path: Path | None,
    combined: np.ndarray,
    sample_rate: int,
    phases: dict[str, LanePhase],
    push_seconds: float,
    threshold: float,
    inactive_frames: int,
) -> _CandidateResult:
    with NativeSortformerDiarizer(
        model_path,
        library_path=library_path,
        gpu=0,
        preset="streaming",
        geometry=candidate.geometry,
    ) as diarizer:
        final_snapshot, updates, latencies, elapsed = _run_persistent_stream(
            diarizer,
            combined,
            sample_rate=sample_rate,
            push_seconds=push_seconds,
        )

    if final_snapshot.frame_start != 0:
        raise RuntimeError(
            f"{candidate.name} exceeded Sortformer probability retention horizon"
        )

    required = (
        "B1_PHONE_ONLY",
        "G_OWNER_PLUS_PHONE",
        "B2_PHONE_ONLY",
        "A_OWNER_ONLY",
    )
    stats = {
        name: summarize_phase(
            final_snapshot.probabilities,
            seconds_per_frame=final_snapshot.seconds_per_frame,
            phase=phases[name],
            threshold=threshold,
        )
        for name in required
    }
    phone_lane = stats["B1_PHONE_ONLY"].dominant_lane
    owner_lane = stats["A_OWNER_ONLY"].dominant_lane
    phone_lane_stable = stats["B2_PHONE_ONLY"].dominant_lane == phone_lane
    owner_phone_lanes_distinct = owner_lane != phone_lane

    g_phase = phases["G_OWNER_PLUS_PHONE"]
    g_mask = _phase_mask(
        final_snapshot.frame_count,
        seconds_per_frame=final_snapshot.seconds_per_frame,
        phase=g_phase,
    )
    g_selected = final_snapshot.probabilities[g_mask]
    overlap_concurrent_fraction = float(
        np.mean(
            (g_selected[:, owner_lane] >= threshold)
            & (g_selected[:, phone_lane] >= threshold)
        )
    )

    b2_phase = phases["B2_PHONE_ONLY"]
    owner_residual_total = stats["B2_PHONE_ONLY"].active_fractions[owner_lane]
    owner_residual_after_1s = _active_fraction_after(
        final_snapshot.probabilities,
        lane=owner_lane,
        seconds_per_frame=final_snapshot.seconds_per_frame,
        phase=b2_phase,
        threshold=threshold,
        start_offset_seconds=1.0,
    )
    owner_residual_after_2s = _active_fraction_after(
        final_snapshot.probabilities,
        lane=owner_lane,
        seconds_per_frame=final_snapshot.seconds_per_frame,
        phase=b2_phase,
        threshold=threshold,
        start_offset_seconds=2.0,
    )
    owner_residual_after_3s = _active_fraction_after(
        final_snapshot.probabilities,
        lane=owner_lane,
        seconds_per_frame=final_snapshot.seconds_per_frame,
        phase=b2_phase,
        threshold=threshold,
        start_offset_seconds=3.0,
    )
    acoustic_owner_inactive_ms = _acoustic_inactive_ms(
        final_snapshot.probabilities,
        lane=owner_lane,
        seconds_per_frame=final_snapshot.seconds_per_frame,
        boundary_seconds=g_phase.end_seconds,
        threshold=threshold,
        consecutive_frames=inactive_frames,
    )
    live_owner_inactive_ms = _live_inactive_ms(
        updates,
        lane=owner_lane,
        boundary_seconds=g_phase.end_seconds,
        threshold=threshold,
        consecutive_frames=inactive_frames,
    )
    overlap_visible_ms = _live_overlap_ms(
        updates,
        owner_lane=owner_lane,
        phone_lane=phone_lane,
        phase=g_phase,
        threshold=threshold,
    )
    owner_reacquire_ms = _live_onset_ms(
        updates,
        lane=owner_lane,
        phase=phases["A_OWNER_ONLY"],
        threshold=threshold,
    )

    push_array = np.asarray(latencies, dtype=np.float64)
    push_median_ms = float(np.median(push_array)) if push_array.size else 0.0
    push_p95_ms = float(np.percentile(push_array, 95)) if push_array.size else 0.0
    push_max_ms = float(np.max(push_array)) if push_array.size else 0.0
    audio_seconds = float(combined.size / sample_rate)
    structural_pass = (
        phone_lane_stable
        and owner_phone_lanes_distinct
        and stats["B1_PHONE_ONLY"].active_fractions[phone_lane] >= 0.5
        and stats["A_OWNER_ONLY"].active_fractions[owner_lane] >= 0.5
        and overlap_concurrent_fraction > 0.0
        and acoustic_owner_inactive_ms is not None
        and owner_reacquire_ms is not None
    )

    return _CandidateResult(
        name=candidate.name,
        input_buffer_ms=candidate.input_buffer_ms,
        phone_lane=phone_lane,
        owner_lane=owner_lane,
        phone_lane_stable=phone_lane_stable,
        owner_phone_lanes_distinct=owner_phone_lanes_distinct,
        overlap_concurrent_fraction=overlap_concurrent_fraction,
        owner_residual_total=owner_residual_total,
        owner_residual_after_1s=owner_residual_after_1s,
        owner_residual_after_2s=owner_residual_after_2s,
        owner_residual_after_3s=owner_residual_after_3s,
        acoustic_owner_inactive_ms=acoustic_owner_inactive_ms,
        live_owner_inactive_ms=live_owner_inactive_ms,
        overlap_visible_ms=overlap_visible_ms,
        owner_reacquire_ms=owner_reacquire_ms,
        processing_ms=elapsed * 1000.0,
        realtime_factor=elapsed / audio_seconds,
        push_median_ms=push_median_ms,
        push_p95_ms=push_p95_ms,
        push_max_ms=push_max_ms,
        live_updates=len(updates),
        structural_pass=structural_pass,
    )


def _print_result(result: _CandidateResult) -> None:
    print(f"\n[{result.name}]")
    print(f"  published input buffer = {result.input_buffer_ms} ms")
    print(f"  phone lane / OWNER lane = {result.phone_lane} / {result.owner_lane}")
    print(f"  phone_lane_stable = {result.phone_lane_stable}")
    print(f"  owner_phone_lanes_distinct = {result.owner_phone_lanes_distinct}")
    print(f"  overlap_concurrent_fraction = {result.overlap_concurrent_fraction:.3f}")
    print(f"  B2 OWNER-active whole = {result.owner_residual_total:.3f}")
    print(
        "  B2 OWNER-active after 1s / 2s / 3s = "
        f"{_format_optional(result.owner_residual_after_1s)} / "
        f"{_format_optional(result.owner_residual_after_2s)} / "
        f"{_format_optional(result.owner_residual_after_3s)}"
    )
    print(
        "  acoustic OWNER inactive after G = "
        + _format_optional(result.acoustic_owner_inactive_ms, suffix=" ms")
    )
    print(
        "  LIVE OWNER inactive after G = "
        + _format_optional(result.live_owner_inactive_ms, suffix=" ms")
    )
    print(
        "  live overlap visible after G starts = "
        + _format_optional(result.overlap_visible_ms, suffix=" ms")
    )
    print(
        "  live OWNER reacquire after phone stops = "
        + _format_optional(result.owner_reacquire_ms, suffix=" ms")
    )
    print(
        f"  processing={result.processing_ms:.1f} ms | RTF={result.realtime_factor:.3f} | "
        f"live_updates={result.live_updates}"
    )
    print(
        f"  push_ms median={result.push_median_ms:.1f} p95={result.push_p95_ms:.1f} "
        f"max={result.push_max_ms:.1f}"
    )
    print(f"  structural_pass = {result.structural_pass}")


async def run_geometry_benchmark(
    *,
    model_path: Path | None,
    library_path: Path | None,
    capture_seconds: float,
    push_seconds: float,
    threshold: float,
    inactive_frames: int,
    with_vision: bool,
) -> int:
    if sys.platform != "win32":
        print("This real-machine geometry benchmark currently targets Windows.")
        return 2
    if capture_seconds < 3.0:
        raise ValueError("capture_seconds must be at least 3 seconds")
    if push_seconds <= 0.0:
        raise ValueError("push_seconds must be positive")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be in (0,1)")
    if inactive_frames < 2:
        raise ValueError("inactive_frames must be at least 2")

    config = JarvisConfig.from_environment()
    model_path = ensure_sortformer_model(model_path)
    try:
        owner_observer = build_default_enrolled_speaker_observer()
    except SpeakerShadowRuntimeError as exc:
        raise RuntimeError(f"CAM++ OWNER observer is required: {exc}") from exc

    print("JARVIS Step 3B.13 Sortformer geometry owner-lane bake-off")
    print("--------------------------------------------------------")
    print("BENCHMARK ONLY: production Gemini/barge-in/trust/authority are unchanged.")
    print("One B1/G/B2/A capture is replayed through all geometries.")
    print("Raw audio remains memory-only and is discarded on exit.")
    print(f"model_id = {SORTFORMER_MODEL_ID}")
    print(f"model_revision = {SORTFORMER_MODEL_REVISION}")
    print(f"model_sha256 = {SORTFORMER_MODEL_SHA256}")
    print(f"diagnostic_activity_threshold = {threshold:.3f}")
    print(f"audio_push_window_ms = {push_seconds * 1000.0:.0f}")
    print("candidates = default 1.60s | NVIDIA low 1.04s | NVIDIA ultra-low 0.32s")

    vision_service = None
    if with_vision:
        vision_service = build_default_vision_service(
            head_model_path=config.vision_head_model_path,
        )
        print("Vision contention probe = enabled")
    else:
        print("Vision contention probe = disabled")

    runtime = MediaDevicesConversationRuntime(
        _NoOpWakeDetector(),  # type: ignore[arg-type]
        input_device_name=config.audio_input_device,
        output_device_name=config.audio_output_device,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=max(1.0, config.audio_ring_buffer_seconds),
    )
    session_input = SessionAudioInput(capacity_frames=5_000)
    recorder = InMemorySegmentRecorder()
    consumer_task: asyncio.Task[None] | None = None
    vision_started = False
    captures: list[tuple[str, np.ndarray, int]] = []
    try:
        if vision_service is not None:
            await asyncio.to_thread(vision_service.start)
            vision_started = True
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-owner-lane-geometry-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        captures = await _capture_sequence(
            recorder,
            capture_seconds=capture_seconds,
        )
        print("\nCapture sanity / CAM++ shadow")
        for label, samples, sample_rate in captures:
            await asyncio.to_thread(
                _score_phase,
                owner_observer,
                label,
                samples,
                sample_rate,
            )

        phases = _phase_windows(captures)
        combined = np.concatenate([samples for _, samples, _ in captures])
        sample_rate = captures[0][2]

        results: list[_CandidateResult] = []
        for candidate in _CANDIDATES:
            print(f"\nRunning {candidate.name}...")
            result = await asyncio.to_thread(
                _evaluate_candidate,
                candidate,
                model_path=model_path,
                library_path=library_path,
                combined=combined,
                sample_rate=sample_rate,
                phases=phases,
                push_seconds=push_seconds,
                threshold=threshold,
                inactive_frames=inactive_frames,
            )
            results.append(result)
            _print_result(result)

        print("\nComparison summary")
        for result in results:
            live = (
                "n/a"
                if result.live_owner_inactive_ms is None
                else f"{result.live_owner_inactive_ms:.0f} ms"
            )
            print(
                f"  {result.name}: structural={result.structural_pass} | "
                f"live_OWNER_inactive={live} | overlap={result.overlap_concurrent_fraction:.3f} | "
                f"RTF={result.realtime_factor:.3f}"
            )
        valid = [
            result
            for result in results
            if result.structural_pass and result.live_owner_inactive_ms is not None
        ]
        if valid:
            fastest = min(valid, key=lambda item: float(item.live_owner_inactive_ms))
            print(f"  fastest_structural_candidate = {fastest.name}")
            print(
                "  candidate_selection_promoted = False (human review + production-shadow gate required)"
            )
        else:
            print("  fastest_structural_candidate = none")

        print("\nSafety disposition")
        print("  production_turn_gate_enabled = False")
        print("  Gemini_activity_detection_changed = False")
        print("  CAM++_threshold_promoted = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        if valid:
            print("STEP_3B13_SORTFORMER_GEOMETRY_BAKEOFF = EVIDENCE_COMPLETE")
            return 0
        print("STEP_3B13_SORTFORMER_GEOMETRY_BAKEOFF = NO_STRUCTURAL_CANDIDATE")
        return 1
    finally:
        for _, samples, _ in captures:
            del samples
        captures.clear()
        recorder.clear()
        runtime.deactivate_session()
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        await runtime.aclose()
        if vision_started and vision_service is not None:
            await asyncio.to_thread(vision_service.stop)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare published Sortformer streaming geometries on one canonical "
            "B1/G/B2/A capture without changing production turn-taking."
        )
    )
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--dll", type=Path, default=None)
    parser.add_argument(
        "--capture-seconds", type=float, default=_DEFAULT_CAPTURE_SECONDS
    )
    parser.add_argument("--push-seconds", type=float, default=_DEFAULT_PUSH_SECONDS)
    parser.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD)
    parser.add_argument("--inactive-frames", type=int, default=_DEFAULT_INACTIVE_FRAMES)
    parser.add_argument(
        "--without-vision",
        action="store_true",
        help="Skip RF-DETR Vision contention during this benchmark.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        code = asyncio.run(
            run_geometry_benchmark(
                model_path=args.model,
                library_path=args.dll,
                capture_seconds=args.capture_seconds,
                push_seconds=args.push_seconds,
                threshold=args.threshold,
                inactive_frames=args.inactive_frames,
                with_vision=not args.without_vision,
            )
        )
    except (
        SortformerAssetError,
        SortformerNativeError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"Sortformer geometry bake-off failed: {exc}")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
