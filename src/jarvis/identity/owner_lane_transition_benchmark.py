from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.owner_lane_benchmark import (
    _NoOpWakeDetector,
    _capture,
    _consume_frames,
    _live_inactive_ms,
    _live_onset_ms,
    _live_overlap_ms,
    _phase_windows,
    _run_persistent_stream,
    _score_phase,
)
from jarvis.identity.sortformer_assets import (
    SORTFORMER_MODEL_ID,
    SORTFORMER_MODEL_REVISION,
    SORTFORMER_MODEL_SHA256,
    SortformerAssetError,
    ensure_sortformer_model,
)
from jarvis.identity.sortformer_lane import LanePhase, LanePhaseStats, summarize_phase
from jarvis.identity.sortformer_native import (
    NativeSortformerDiarizer,
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
_DEFAULT_PUSH_SECONDS = 0.16
_DEFAULT_THRESHOLD = 0.5
_DEFAULT_INACTIVE_FRAMES = 3


def _phase_mask(
    frame_count: int,
    *,
    seconds_per_frame: float,
    phase: LanePhase,
    start_offset_seconds: float = 0.0,
) -> np.ndarray:
    centers = (np.arange(frame_count, dtype=np.float64) + 0.5) * seconds_per_frame
    start = phase.start_seconds + max(0.0, start_offset_seconds)
    return (centers >= start) & (centers < phase.end_seconds)


def _active_fraction_after(
    probabilities: np.ndarray,
    *,
    lane: int,
    seconds_per_frame: float,
    phase: LanePhase,
    threshold: float,
    start_offset_seconds: float,
) -> float | None:
    mask = _phase_mask(
        probabilities.shape[0],
        seconds_per_frame=seconds_per_frame,
        phase=phase,
        start_offset_seconds=start_offset_seconds,
    )
    selected = probabilities[mask, lane]
    if selected.size == 0:
        return None
    return float(np.mean(selected >= threshold))


def _acoustic_inactive_ms(
    probabilities: np.ndarray,
    *,
    lane: int,
    seconds_per_frame: float,
    boundary_seconds: float,
    threshold: float,
    consecutive_frames: int,
) -> float | None:
    if consecutive_frames < 1:
        raise ValueError("consecutive_frames must be positive")
    centers = (
        np.arange(probabilities.shape[0], dtype=np.float64) + 0.5
    ) * seconds_per_frame
    eligible = np.flatnonzero(centers >= boundary_seconds)
    if eligible.size < consecutive_frames:
        return None
    below = probabilities[:, lane] < threshold
    for end in range(consecutive_frames - 1, eligible.size):
        window = eligible[end - consecutive_frames + 1 : end + 1]
        if bool(np.all(below[window])):
            first_center = float(centers[int(window[0])])
            return max(0.0, (first_center - boundary_seconds) * 1000.0)
    return None


def _format_fraction(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def _print_phase_stats(stats: dict[str, LanePhaseStats]) -> None:
    for name, item in stats.items():
        means = ", ".join(f"{value:.3f}" for value in item.mean_probabilities)
        active = ", ".join(f"{value:.3f}" for value in item.active_fractions)
        print(
            f"  {name}: dominant={item.dominant_lane} | frames={item.frame_count} | "
            f"mean=[{means}] | active_fraction=[{active}]"
        )


async def run_transition_benchmark(
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
        print("This real-machine transition benchmark currently targets Windows.")
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

    print("JARVIS Step 3B.13 focused OWNER-lane transition benchmark")
    print("---------------------------------------------------------")
    print("BENCHMARK ONLY: Gemini, wake, barge-in, trust, and authority are unchanged.")
    print("Four captures are replayed through ONE persistent Sortformer stream.")
    print("A1 has been removed: phone anchors PHONE; final OWNER-only anchors OWNER.")
    print("Raw audio is memory-only and discarded when this process exits.")
    print(f"model_id = {SORTFORMER_MODEL_ID}")
    print(f"model_revision = {SORTFORMER_MODEL_REVISION}")
    print(f"model_sha256 = {SORTFORMER_MODEL_SHA256}")
    print(f"diagnostic_activity_threshold = {threshold:.3f}")
    print(f"push_window_ms = {push_seconds * 1000.0:.0f}")

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
            name="jarvis-owner-lane-transition-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

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
        audio_seconds = float(combined.size / sample_rate)

        with NativeSortformerDiarizer(
            model_path,
            library_path=library_path,
            gpu=0,
            preset="streaming",
        ) as diarizer:
            print(f"\nruntime_version = {diarizer.runtime_version}")
            print(f"native_library = {diarizer.library_path}")
            print(f"model_load_ms = {diarizer.model_load_seconds * 1000.0:.1f}")
            print(f"seconds_per_frame = {diarizer.seconds_per_frame:.3f}")
            final_snapshot, updates, latencies, elapsed = await asyncio.to_thread(
                _run_persistent_stream,
                diarizer,
                combined,
                sample_rate=sample_rate,
                push_seconds=push_seconds,
            )

        if final_snapshot.frame_start != 0:
            raise RuntimeError(
                "benchmark unexpectedly exceeded Sortformer probability retention horizon"
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
        owner_anchor_fraction = stats["A_OWNER_ONLY"].active_fractions[owner_lane]
        phone_anchor_fraction = stats["B1_PHONE_ONLY"].active_fractions[phone_lane]

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
        owner_residual_1s = _active_fraction_after(
            final_snapshot.probabilities,
            lane=owner_lane,
            seconds_per_frame=final_snapshot.seconds_per_frame,
            phase=b2_phase,
            threshold=threshold,
            start_offset_seconds=1.0,
        )
        owner_residual_2s = _active_fraction_after(
            final_snapshot.probabilities,
            lane=owner_lane,
            seconds_per_frame=final_snapshot.seconds_per_frame,
            phase=b2_phase,
            threshold=threshold,
            start_offset_seconds=2.0,
        )
        owner_residual_3s = _active_fraction_after(
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

        print("\nFocused persistent lane analysis")
        print(f"  phone lane = {phone_lane}")
        print(f"  OWNER lane = {owner_lane}")
        _print_phase_stats(stats)
        print(f"  phone_lane_stable = {phone_lane_stable}")
        print(f"  owner_phone_lanes_distinct = {owner_phone_lanes_distinct}")
        print(f"  phone_anchor_active_fraction = {phone_anchor_fraction:.3f}")
        print(f"  owner_anchor_active_fraction = {owner_anchor_fraction:.3f}")
        print(f"  overlap_concurrent_fraction = {overlap_concurrent_fraction:.3f}")

        print("\nOWNER decay during B2 phone-only")
        print(f"  whole B2 OWNER-active fraction = {owner_residual_total:.3f}")
        print(f"  after 1.0s = {_format_fraction(owner_residual_1s)}")
        print(f"  after 2.0s = {_format_fraction(owner_residual_2s)}")
        print(f"  after 3.0s = {_format_fraction(owner_residual_3s)}")
        print(
            "  acoustic OWNER inactive after G = "
            + _format_ms(acoustic_owner_inactive_ms)
        )

        print("\nLive update availability")
        print("  overlap visible after G starts = " + _format_ms(overlap_visible_ms))
        print(
            "  OWNER inactive while phone continues after G = "
            + _format_ms(live_owner_inactive_ms)
        )
        print(
            "  OWNER re-acquisition after phone stops = "
            + _format_ms(owner_reacquire_ms)
        )

        push_array = np.asarray(latencies, dtype=np.float64)
        median_ms = float(np.median(push_array)) if push_array.size else 0.0
        p95_ms = float(np.percentile(push_array, 95)) if push_array.size else 0.0
        max_ms = float(np.max(push_array)) if push_array.size else 0.0
        print("\nPerformance")
        print(f"  continuous_audio = {audio_seconds:.2f}s")
        print(
            f"  processing = {elapsed * 1000.0:.1f} ms | RTF={elapsed / audio_seconds:.3f}"
        )
        print(
            f"  push_ms median={median_ms:.1f} p95={p95_ms:.1f} max={max_ms:.1f} | "
            f"live_updates={len(updates)}"
        )

        structural_pass = (
            phone_lane_stable
            and owner_phone_lanes_distinct
            and phone_anchor_fraction >= 0.5
            and owner_anchor_fraction >= 0.5
            and overlap_concurrent_fraction > 0.0
            and acoustic_owner_inactive_ms is not None
            and owner_reacquire_ms is not None
        )

        print("\nAcceptance summary")
        print(f"  phone_lane_stable = {phone_lane_stable}")
        print(f"  owner_phone_lanes_distinct = {owner_phone_lanes_distinct}")
        print(f"  overlap_concurrent_fraction = {overlap_concurrent_fraction:.3f}")
        print(
            "  acoustic_owner_inactive_ms = "
            + _format_ms(acoustic_owner_inactive_ms)
        )
        print("  live_owner_inactive_ms = " + _format_ms(live_owner_inactive_ms))
        print("  production_turn_gate_enabled = False")
        print("  CAM++_threshold_promoted = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        if structural_pass:
            print("STEP_3B13_OWNER_LANE_TRANSITION = STRUCTURAL_PASS")
            print(
                "Live decision latency still requires human review before production turn gating."
            )
            return 0
        print("STEP_3B13_OWNER_LANE_TRANSITION = FAIL")
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
            "Measure persistent Sortformer OWNER-lane decay after OWNER+phone overlap "
            "without changing production turn-taking."
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
            run_transition_benchmark(
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
        print(f"focused OWNER-lane transition benchmark failed: {exc}")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
