from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.sortformer_assets import (
    SORTFORMER_MODEL_ID,
    SORTFORMER_MODEL_REVISION,
    SORTFORMER_MODEL_SHA256,
    SortformerAssetError,
    ensure_sortformer_model,
)
from jarvis.identity.sortformer_lane import (
    LanePhase,
    OwnerLaneAnalysis,
    analyze_owner_lane_sequence,
)
from jarvis.identity.sortformer_live import NativeSortformerLiveStream, SortformerLiveSnapshot
from jarvis.identity.sortformer_native import NativeSortformerDiarizer, SortformerNativeError
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder, segment_metrics
from jarvis.identity.speaker_shadow import (
    EnrolledSpeakerShadowObserver,
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


@dataclass(frozen=True, slots=True)
class _LiveUpdate:
    audio_seconds: float
    snapshot: SortformerLiveSnapshot


class _NoOpWakeDetector:
    def enable(self) -> None:
        return None

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer

    def feed(self, frame) -> None:
        del frame

    async def aclose(self) -> None:
        return None


async def _consume_frames(
    source: SessionAudioInput,
    recorder: InMemorySegmentRecorder,
) -> None:
    async for frame in source:
        recorder.accept_frame(frame)


async def _capture(
    recorder: InMemorySegmentRecorder,
    *,
    label: str,
    instructions: str,
    duration_seconds: float,
) -> tuple[np.ndarray, int]:
    await asyncio.to_thread(input, f"\n[{label}] {instructions}\nPress Enter when ready... ")
    print("  3...")
    await asyncio.sleep(0.35)
    print("  2...")
    await asyncio.sleep(0.35)
    print("  1...")
    await asyncio.sleep(0.35)
    print(f"  >>> CAPTURE {duration_seconds:.1f}s <<<")
    recorder.start()
    try:
        await asyncio.sleep(duration_seconds)
        samples, sample_rate = recorder.stop()
    except BaseException:
        recorder.clear()
        raise
    print("  >>> STOP <<<")
    return samples, sample_rate


def _format_optional_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def _score_phase(
    observer: EnrolledSpeakerShadowObserver,
    label: str,
    samples: np.ndarray,
    sample_rate: int,
) -> None:
    metrics = segment_metrics(samples, sample_rate)
    score = observer.score(samples, sample_rate=sample_rate)
    cosine = "n/a" if score.max_reference_cosine is None else f"{score.max_reference_cosine:.4f}"
    print(
        f"  {label}: audio={metrics.duration_seconds:.2f}s | RMS={metrics.rms_dbfs:.1f} dBFS | "
        f"CAM++={cosine} ({score.state}, {score.embedding_ms:.1f} ms)"
    )


def _phase_windows(
    captures: list[tuple[str, np.ndarray, int]],
) -> dict[str, LanePhase]:
    cursor = 0.0
    phases: dict[str, LanePhase] = {}
    for label, samples, sample_rate in captures:
        duration = float(samples.size / sample_rate)
        phases[label] = LanePhase(label, cursor, cursor + duration)
        cursor += duration
    return phases


def _global_frame_indexes(snapshot: SortformerLiveSnapshot) -> np.ndarray:
    return np.arange(snapshot.frame_start, snapshot.frame_count, dtype=np.int64)


def _live_onset_ms(
    updates: list[_LiveUpdate],
    *,
    lane: int,
    phase: LanePhase,
    threshold: float,
    consecutive_frames: int = 2,
) -> float | None:
    for update in updates:
        if update.audio_seconds < phase.start_seconds:
            continue
        snapshot = update.snapshot
        indexes = _global_frame_indexes(snapshot)
        if indexes.size == 0:
            continue
        centers = (indexes.astype(np.float64) + 0.5) * snapshot.seconds_per_frame
        mask = (centers >= phase.start_seconds) & (centers < phase.end_seconds)
        active = snapshot.probabilities[:, lane] >= threshold
        positions = np.flatnonzero(mask)
        if positions.size < consecutive_frames:
            continue
        for end in range(consecutive_frames - 1, positions.size):
            window = positions[end - consecutive_frames + 1 : end + 1]
            if bool(np.all(active[window])):
                return max(0.0, (update.audio_seconds - phase.start_seconds) * 1000.0)
    return None


def _live_inactive_ms(
    updates: list[_LiveUpdate],
    *,
    lane: int,
    boundary_seconds: float,
    threshold: float,
    consecutive_frames: int,
) -> float | None:
    for update in updates:
        if update.audio_seconds < boundary_seconds:
            continue
        snapshot = update.snapshot
        indexes = _global_frame_indexes(snapshot)
        if indexes.size == 0:
            continue
        centers = (indexes.astype(np.float64) + 0.5) * snapshot.seconds_per_frame
        positions = np.flatnonzero(centers >= boundary_seconds)
        if positions.size < consecutive_frames:
            continue
        latest = positions[-consecutive_frames:]
        if bool(np.all(snapshot.probabilities[latest, lane] < threshold)):
            return max(0.0, (update.audio_seconds - boundary_seconds) * 1000.0)
    return None


def _live_overlap_ms(
    updates: list[_LiveUpdate],
    *,
    owner_lane: int,
    phone_lane: int,
    phase: LanePhase,
    threshold: float,
) -> float | None:
    for update in updates:
        if update.audio_seconds < phase.start_seconds:
            continue
        snapshot = update.snapshot
        indexes = _global_frame_indexes(snapshot)
        if indexes.size == 0:
            continue
        centers = (indexes.astype(np.float64) + 0.5) * snapshot.seconds_per_frame
        mask = (centers >= phase.start_seconds) & (centers < phase.end_seconds)
        concurrent = (
            (snapshot.probabilities[:, owner_lane] >= threshold)
            & (snapshot.probabilities[:, phone_lane] >= threshold)
            & mask
        )
        if bool(np.any(concurrent)):
            return max(0.0, (update.audio_seconds - phase.start_seconds) * 1000.0)
    return None


def _print_lane_analysis(
    analysis: OwnerLaneAnalysis,
    *,
    phases: dict[str, LanePhase],
    updates: list[_LiveUpdate],
    threshold: float,
    inactive_frames: int,
) -> None:
    print("\nPersistent lane analysis")
    print(f"  OWNER lane = {analysis.owner_lane}")
    print(f"  phone lane = {analysis.phone_lane}")
    for name, stats in analysis.phase_stats.items():
        means = ", ".join(f"{value:.3f}" for value in stats.mean_probabilities)
        active = ", ".join(f"{value:.3f}" for value in stats.active_fractions)
        print(
            f"  {name}: dominant={stats.dominant_lane} | frames={stats.frame_count} | "
            f"mean=[{means}] | active_fraction=[{active}]"
        )
    print(f"  owner_lane_reacquired = {analysis.owner_lane_reacquired}")
    print(f"  phone_lane_stable = {analysis.phone_lane_stable}")
    print(f"  owner_phone_lanes_distinct = {analysis.owner_phone_lanes_distinct}")
    print(f"  overlap_concurrent_fraction = {analysis.overlap_concurrent_fraction:.3f}")

    owner_lane = analysis.owner_lane
    phone_lane = analysis.phone_lane
    print("\nLive update availability")
    print(
        "  initial OWNER acquisition = "
        + _format_optional_ms(
            _live_onset_ms(
                updates,
                lane=owner_lane,
                phase=phases["A1_OWNER_ONLY"],
                threshold=threshold,
            )
        )
    )
    print(
        "  OWNER inactive after A1->phone = "
        + _format_optional_ms(
            _live_inactive_ms(
                updates,
                lane=owner_lane,
                boundary_seconds=phases["A1_OWNER_ONLY"].end_seconds,
                threshold=threshold,
                consecutive_frames=inactive_frames,
            )
        )
    )
    print(
        "  overlap visible after G starts = "
        + _format_optional_ms(
            _live_overlap_ms(
                updates,
                owner_lane=owner_lane,
                phone_lane=phone_lane,
                phase=phases["G_OWNER_PLUS_PHONE"],
                threshold=threshold,
            )
        )
    )
    print(
        "  OWNER inactive while phone continues after G = "
        + _format_optional_ms(
            _live_inactive_ms(
                updates,
                lane=owner_lane,
                boundary_seconds=phases["G_OWNER_PLUS_PHONE"].end_seconds,
                threshold=threshold,
                consecutive_frames=inactive_frames,
            )
        )
    )
    print(
        "  OWNER re-acquisition after B2->A2 = "
        + _format_optional_ms(
            _live_onset_ms(
                updates,
                lane=owner_lane,
                phase=phases["A2_OWNER_ONLY"],
                threshold=threshold,
            )
        )
    )


def _run_persistent_stream(
    diarizer: NativeSortformerDiarizer,
    samples: np.ndarray,
    *,
    sample_rate: int,
    push_seconds: float,
) -> tuple[SortformerLiveSnapshot, list[_LiveUpdate], tuple[float, ...], float]:
    push_size = max(1, round(sample_rate * push_seconds))
    updates: list[_LiveUpdate] = []
    latencies: list[float] = []
    started = time.perf_counter()
    with NativeSortformerLiveStream(diarizer) as stream:
        last_frame_count = -1
        for offset in range(0, samples.size, push_size):
            result = stream.push(samples[offset : offset + push_size], sample_rate=sample_rate)
            latencies.append(result.push_latency_ms)
            if result.snapshot.frame_count != last_frame_count:
                updates.append(
                    _LiveUpdate(
                        audio_seconds=result.audio_seconds_total,
                        snapshot=result.snapshot,
                    )
                )
                last_frame_count = result.snapshot.frame_count
        final_snapshot = stream.finish()
        if not updates or final_snapshot.frame_count != updates[-1].snapshot.frame_count:
            updates.append(
                _LiveUpdate(
                    audio_seconds=stream.audio_seconds_total,
                    snapshot=final_snapshot,
                )
            )
    elapsed = time.perf_counter() - started
    return final_snapshot, updates, tuple(latencies), elapsed


async def run_owner_lane_benchmark(
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
        print("This real-machine persistent OWNER-lane benchmark currently targets Windows.")
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

    print("JARVIS Step 3B.13 persistent Sortformer OWNER-lane benchmark")
    print("----------------------------------------------------------")
    print("BENCHMARK ONLY: Gemini, wake, barge-in, trust, and authority are unchanged.")
    print("Five captures are replayed through ONE persistent Sortformer stream.")
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
            name="jarvis-owner-lane-benchmark-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        scenarios = (
            (
                "A1_OWNER_ONLY",
                "Phone/TV silent. Speak naturally for the whole capture.",
            ),
            (
                "B1_PHONE_ONLY",
                "Stay silent. Play continuous human speech from the phone at normal room volume.",
            ),
            (
                "G_OWNER_PLUS_PHONE",
                "Keep phone speech continuous and speak yourself at the same time for most of the capture.",
            ),
            (
                "B2_PHONE_ONLY",
                "Stop speaking yourself but KEEP the same phone speech continuous for the whole capture.",
            ),
            (
                "A2_OWNER_ONLY",
                "Stop the phone. Speak naturally yourself again for the whole capture.",
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
            raise RuntimeError("benchmark unexpectedly exceeded Sortformer probability retention horizon")
        availability = np.full(final_snapshot.frame_count, np.nan, dtype=np.float64)
        previous = 0
        for update in updates:
            snapshot = update.snapshot
            first = max(previous, snapshot.frame_start)
            for frame_index in range(first, snapshot.frame_count):
                if frame_index < availability.size and not np.isfinite(availability[frame_index]):
                    availability[frame_index] = update.audio_seconds
            previous = max(previous, snapshot.frame_count)
        availability[~np.isfinite(availability)] = audio_seconds

        analysis = analyze_owner_lane_sequence(
            final_snapshot.probabilities,
            availability,
            seconds_per_frame=final_snapshot.seconds_per_frame,
            phases=phases,
            threshold=threshold,
            inactive_consecutive_frames=inactive_frames,
        )
        _print_lane_analysis(
            analysis,
            phases=phases,
            updates=updates,
            threshold=threshold,
            inactive_frames=inactive_frames,
        )

        push_array = np.asarray(latencies, dtype=np.float64)
        median_ms = float(np.median(push_array)) if push_array.size else 0.0
        p95_ms = float(np.percentile(push_array, 95)) if push_array.size else 0.0
        max_ms = float(np.max(push_array)) if push_array.size else 0.0
        print("\nPerformance")
        print(f"  continuous_audio = {audio_seconds:.2f}s")
        print(f"  processing = {elapsed * 1000.0:.1f} ms | RTF={elapsed / audio_seconds:.3f}")
        print(
            f"  push_ms median={median_ms:.1f} p95={p95_ms:.1f} max={max_ms:.1f} | "
            f"live_updates={len(updates)}"
        )

        print("\nAcceptance summary")
        print(f"  owner_lane_reacquired = {analysis.owner_lane_reacquired}")
        print(f"  phone_lane_stable = {analysis.phone_lane_stable}")
        print(f"  owner_phone_lanes_distinct = {analysis.owner_phone_lanes_distinct}")
        print(f"  overlap_concurrent_fraction = {analysis.overlap_concurrent_fraction:.3f}")
        print("  production_turn_gate_enabled = False")
        print("  CAM++_threshold_promoted = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        if analysis.functional_pass:
            print("STEP_3B13_PERSISTENT_OWNER_LANE = FUNCTIONAL_PASS")
            print("Decision latency still requires human review before production turn gating.")
            return 0
        print("STEP_3B13_PERSISTENT_OWNER_LANE = FAIL")
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
            "Benchmark persistent Sortformer lane stability and live transition latency on "
            "canonical JARVIS PCM without changing production turn-taking."
        )
    )
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--dll", type=Path, default=None)
    parser.add_argument("--capture-seconds", type=float, default=_DEFAULT_CAPTURE_SECONDS)
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
            run_owner_lane_benchmark(
                model_path=args.model,
                library_path=args.dll,
                capture_seconds=args.capture_seconds,
                push_seconds=args.push_seconds,
                threshold=args.threshold,
                inactive_frames=args.inactive_frames,
                with_vision=not args.without_vision,
            )
        )
    except (SortformerAssetError, SortformerNativeError, ValueError, RuntimeError) as exc:
        print(f"persistent OWNER-lane benchmark failed: {exc}")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
