from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.overlap import OverlapEvidence, interpret_sortformer_probabilities
from jarvis.identity.sortformer_assets import (
    SORTFORMER_MODEL_ID,
    SORTFORMER_MODEL_REVISION,
    SORTFORMER_MODEL_SHA256,
    SortformerAssetError,
    ensure_sortformer_model,
)
from jarvis.identity.sortformer_native import NativeSortformerDiarizer, SortformerNativeError
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder, segment_metrics
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_CAPTURE_SECONDS = 6.0
_DEFAULT_PUSH_SECONDS = 0.32
_DEFAULT_THRESHOLD = 0.5


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
    await asyncio.to_thread(
        input,
        f"\n[{label}] {instructions}\nPress Enter when ready... ",
    )
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


def _process_rss_mib() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)


def _process_gpu_memory_mib() -> float | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    total = 0.0
    matched = False
    current_pid = os.getpid()
    for raw_line in result.stdout.splitlines():
        fields = [item.strip() for item in raw_line.split(",")]
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
            memory = float(fields[1])
        except ValueError:
            continue
        if pid == current_pid:
            matched = True
            total += memory
    return total if matched else 0.0


def _format_optional(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.1f}{suffix}"


def _summarize_evidence(label: str, evidence: OverlapEvidence) -> None:
    print(
        f"  {label}: state={evidence.state.value} | frames={evidence.frame_count} | "
        f"speech={evidence.speech_frames} | overlap={evidence.overlap_frames} | "
        f"longest_overlap_run={evidence.longest_overlap_run} | "
        f"peak_active={evidence.active_speaker_peak} | "
        f"overlap_fraction={evidence.overlap_fraction:.3f} | "
        f"stable_runs={evidence.stable_speaker_runs or 'none'} | "
        f"reasons={','.join(evidence.reason_codes) or 'none'}"
    )


def _analyze_capture(
    diarizer: NativeSortformerDiarizer,
    *,
    label: str,
    samples: np.ndarray,
    sample_rate: int,
    push_seconds: float,
    threshold: float,
) -> OverlapEvidence:
    metrics = segment_metrics(samples, sample_rate)
    gpu_before = _process_gpu_memory_mib()
    rss_before = _process_rss_mib()
    run = diarizer.run_streaming(
        samples,
        sample_rate=sample_rate,
        push_seconds=push_seconds,
    )
    gpu_after = _process_gpu_memory_mib()
    rss_after = _process_rss_mib()
    evidence = interpret_sortformer_probabilities(
        run.probabilities,
        threshold=threshold,
    )

    push = np.asarray(run.push_latencies_ms, dtype=np.float64)
    push_median = float(np.median(push)) if push.size else 0.0
    push_p95 = float(np.percentile(push, 95)) if push.size else 0.0
    push_max = float(push.max()) if push.size else 0.0

    print(f"\n{label} telemetry")
    print(
        f"  audio={metrics.duration_seconds:.2f}s | RMS={metrics.rms_dbfs:.1f} dBFS | "
        f"peak={metrics.peak_dbfs:.1f} dBFS | clipped={metrics.clipping_ratio * 100:.3f}%"
    )
    print(
        f"  inference={run.inference_seconds * 1000.0:.1f} ms | "
        f"RTF={run.realtime_factor:.3f} | output_frames={run.frame_count} | "
        f"frame_step={run.seconds_per_frame:.3f}s"
    )
    print(
        f"  push_ms median={push_median:.1f} p95={push_p95:.1f} max={push_max:.1f} | "
        f"push_window={push_seconds * 1000.0:.0f} ms"
    )
    print(
        "  process GPU MiB before/after="
        f"{_format_optional(gpu_before)}/{_format_optional(gpu_after)} | "
        f"RSS MiB before/after={_format_optional(rss_before)}/{_format_optional(rss_after)}"
    )
    _summarize_evidence(label, evidence)
    return evidence


async def run_overlap_benchmark(
    *,
    model_path: Path | None,
    library_path: Path | None,
    capture_seconds: float,
    push_seconds: float,
    threshold: float,
    with_vision: bool,
) -> int:
    if sys.platform != "win32":
        print("This real-machine benchmark currently targets native Windows only.")
        return 2
    if capture_seconds < 3.0:
        raise ValueError("capture_seconds must be at least 3 seconds")

    config = JarvisConfig.from_environment()
    model_path = ensure_sortformer_model(model_path)
    print("JARVIS Step 3B.13 native overlap benchmark")
    print("------------------------------------------")
    print("Benchmark only: no production authority or threshold is changed.")
    print("Audio comes only from the accepted LiveKit MediaDevices/WebRTC path.")
    print("Raw audio is memory-only and is discarded when this process exits.")
    print(f"Sortformer model = {model_path}")
    print(f"model_id = {SORTFORMER_MODEL_ID}")
    print(f"model_revision = {SORTFORMER_MODEL_REVISION}")
    print(f"model_size_mib = {model_path.stat().st_size / (1024**2):.1f}")
    print(f"model_sha256 = {SORTFORMER_MODEL_SHA256}")
    print(f"diagnostic_activity_threshold = {threshold:.3f}")

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
    session_input = SessionAudioInput(capacity_frames=4_000)
    recorder = InMemorySegmentRecorder()
    consumer_task: asyncio.Task[None] | None = None
    vision_started = False
    try:
        if vision_service is not None:
            await asyncio.to_thread(vision_service.start)
            vision_started = True
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-overlap-benchmark-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        gpu_before_model = _process_gpu_memory_mib()
        rss_before_model = _process_rss_mib()
        with NativeSortformerDiarizer(
            model_path,
            library_path=library_path,
            gpu=0,
            preset="streaming",
        ) as diarizer:
            gpu_after_model = _process_gpu_memory_mib()
            rss_after_model = _process_rss_mib()
            print(f"runtime_version = {diarizer.runtime_version}")
            print(f"native_library = {diarizer.library_path}")
            print(f"model_load_ms = {diarizer.model_load_seconds * 1000.0:.1f}")
            print(f"num_speakers = {diarizer.num_speakers}")
            print(f"seconds_per_frame = {diarizer.seconds_per_frame:.3f}")
            print(
                "model load process GPU MiB="
                f"{_format_optional(gpu_before_model)} -> {_format_optional(gpu_after_model)} | "
                f"RSS MiB={_format_optional(rss_before_model)} -> "
                f"{_format_optional(rss_after_model)}"
            )

            captures: dict[str, tuple[np.ndarray, int]] = {}
            captures["A_OWNER_ONLY"] = await _capture(
                recorder,
                label="A OWNER ONLY",
                instructions=(
                    "Keep TV/other voices silent. Speak naturally for the whole capture."
                ),
                duration_seconds=capture_seconds,
            )
            captures["B_OTHER_ONLY"] = await _capture(
                recorder,
                label="B OTHER/TV ONLY",
                instructions=(
                    "Stay silent. Play clearly audible TV/phone speech or have another "
                    "person speak for the whole capture."
                ),
                duration_seconds=capture_seconds,
            )
            captures["G_OVERLAP"] = await _capture(
                recorder,
                label="G OVERLAP",
                instructions=(
                    "Speak naturally while the same TV/phone/other-person speech is also "
                    "audible for most of the capture."
                ),
                duration_seconds=capture_seconds,
            )

            evidence: dict[str, OverlapEvidence] = {}
            for label, (samples, sample_rate) in captures.items():
                try:
                    evidence[label] = await asyncio.to_thread(
                        _analyze_capture,
                        diarizer,
                        label=label,
                        samples=samples,
                        sample_rate=sample_rate,
                        push_seconds=push_seconds,
                        threshold=threshold,
                    )
                finally:
                    del samples
            captures.clear()

        a = evidence["A_OWNER_ONLY"]
        g = evidence["G_OVERLAP"]
        a_clean = a.state.value == "single_speaker"
        g_detected = g.state.value == "overlap_detected"
        print("\nAcceptance summary")
        print(f"  A clean single-speaker = {a_clean}")
        print(f"  G overlap detected = {g_detected}")
        print("  threshold_promoted = False")
        print("  authority_effect = False")
        print("  raw_audio_saved = False")
        if a_clean and g_detected:
            print("STEP_3B13_NATIVE_SORTFORMER_BENCHMARK = FUNCTIONAL_PASS")
            print(
                "Performance/UX still requires human review before production shadow integration."
            )
            return 0
        print("STEP_3B13_NATIVE_SORTFORMER_BENCHMARK = FAIL")
        return 1
    finally:
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
            "Benchmark native NeMo-Speech.cpp Sortformer overlap evidence on canonical "
            "JARVIS PCM without changing production authority."
        )
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help=(
            "Pinned Sortformer GGUF path. Omit to download/verify the managed JARVIS asset."
        ),
    )
    parser.add_argument(
        "--dll",
        type=Path,
        default=None,
        help="nemo_speech_asr_c.dll path (or set JARVIS_NEMO_SPEECH_DLL)",
    )
    parser.add_argument(
        "--capture-seconds",
        type=float,
        default=_DEFAULT_CAPTURE_SECONDS,
    )
    parser.add_argument(
        "--push-seconds",
        type=float,
        default=_DEFAULT_PUSH_SECONDS,
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        help="Diagnostic speaker-activity threshold only; never authority",
    )
    parser.add_argument(
        "--without-vision",
        action="store_true",
        help="Skip RF-DETR Vision contention during this benchmark",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        code = asyncio.run(
            run_overlap_benchmark(
                model_path=args.model,
                library_path=args.dll,
                capture_seconds=args.capture_seconds,
                push_seconds=args.push_seconds,
                threshold=args.threshold,
                with_vision=not args.without_vision,
            )
        )
    except (SortformerAssetError, SortformerNativeError, ValueError, RuntimeError) as exc:
        print(f"overlap benchmark failed: {exc}")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
