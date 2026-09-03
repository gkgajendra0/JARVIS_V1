from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.firered_pvad_official import (
    FIRERED_PVAD_FILTER_ALPHA,
    FIRERED_PVAD_MIN_SILENCE_SECONDS,
    FIRERED_PVAD_MIN_SPEECH_SECONDS,
    FIRERED_PVAD_PLUGIN_COMMIT,
    FireRedOfficialParityUnavailable,
    FireRedOfficialParityVad,
)
from jarvis.identity.owner_lane_benchmark import (
    _capture,
    _consume_frames,
    _NoOpWakeDetector,
    _phase_windows,
    _score_phase,
)
from jarvis.identity.personalized_vad_assets import (
    FIRERED_PVAD_MODEL_ID,
    FIRERED_PVAD_MODEL_REVISION,
    FIRERED_PVAD_ONNX_SHA256,
    PersonalizedVadAssetError,
    ensure_personalized_vad_assets,
)
from jarvis.identity.personalized_vad_benchmark import (
    _active_fraction_after,
    _format_optional,
    _summarize_phase,
    _transition_ms,
)
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder
from jarvis.identity.speaker_shadow import (
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_REFERENCE_SECONDS = 4.0
_DEFAULT_CAPTURE_SECONDS = 5.0
_DIAGNOSTIC_THRESHOLD = 0.5
_ONSET_FRAMES = int(FIRERED_PVAD_MIN_SPEECH_SECONDS / 0.01)
_OFFSET_FRAMES = int(FIRERED_PVAD_MIN_SILENCE_SECONDS / 0.01)


async def run_official_parity_benchmark(
    *,
    asset_dir: Path | None,
    reference_seconds: float,
    capture_seconds: float,
    with_vision: bool,
) -> int:
    if sys.platform != "win32":
        print("This real-machine FireRed pVAD benchmark currently targets Windows.")
        return 2
    if reference_seconds < 3.0:
        raise ValueError("reference_seconds must be at least 3 seconds")
    if capture_seconds < 3.0:
        raise ValueError("capture_seconds must be at least 3 seconds")

    config = JarvisConfig.from_environment()
    assets = ensure_personalized_vad_assets(asset_dir)
    try:
        owner_observer = build_default_enrolled_speaker_observer()
    except SpeakerShadowRuntimeError as exc:
        raise RuntimeError(f"CAM++ OWNER observer is required: {exc}") from exc

    print("JARVIS Step 3 FireRed pVAD official-parity benchmark")
    print("----------------------------------------------------")
    print("BENCHMARK ONLY: production wake/Gemini/barge-in are unchanged.")
    print("This run mirrors the official FireRed pVAD plugin lifecycle.")
    print("Security/identity continues to own the unfiltered canonical mixed PCM.")
    print("The temporary ECAPA target embedding and captured audio remain memory-only.")
    print(f"candidate = {FIRERED_PVAD_MODEL_ID}")
    print(f"model_revision = {FIRERED_PVAD_MODEL_REVISION}")
    print(f"pvad_onnx_sha256 = {FIRERED_PVAD_ONNX_SHA256}")
    print(f"official_plugin_commit = {FIRERED_PVAD_PLUGIN_COMMIT}")
    print("official_resampler = LiveKit AudioResampler QUICK")
    print(f"official_filter_alpha = {FIRERED_PVAD_FILTER_ALPHA:.1f}")
    print(f"official_min_speech_ms = {FIRERED_PVAD_MIN_SPEECH_SECONDS * 1000:.0f}")
    print(f"official_min_silence_ms = {FIRERED_PVAD_MIN_SILENCE_SECONDS * 1000:.0f}")
    print(f"diagnostic_activity_threshold = {_DIAGNOSTIC_THRESHOLD:.3f}")
    print("model_frame_ms = 10")

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
    reference_samples: np.ndarray | None = None
    captures: list[tuple[str, np.ndarray, int]] = []
    target_embedding: np.ndarray | None = None

    try:
        if vision_service is not None:
            await asyncio.to_thread(vision_service.start)
            vision_started = True
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-pvad-official-parity-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        reference_samples, reference_rate = await _capture(
            recorder,
            label="S_OWNER_REFERENCE_WARMUP",
            instructions=(
                "Phone/TV silent. Speak naturally for the whole capture. FireRed will first "
                "process this with its default speaker state, then update the temporary "
                "speaker embedding without resetting recurrent state."
            ),
            duration_seconds=reference_seconds,
        )

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
            if sample_rate != reference_rate:
                raise RuntimeError(
                    "canonical sample rate changed between pVAD captures"
                )
            captures.append((label, samples, sample_rate))

        print("\nCapture sanity / existing CAM++ shadow")
        await asyncio.to_thread(
            _score_phase,
            owner_observer,
            "S_OWNER_REFERENCE_WARMUP",
            reference_samples,
            reference_rate,
        )
        for label, samples, sample_rate in captures:
            await asyncio.to_thread(
                _score_phase,
                owner_observer,
                label,
                samples,
                sample_rate,
            )

        build_started = time.perf_counter()
        candidate = await asyncio.to_thread(FireRedOfficialParityVad, assets)
        model_build_ms = (time.perf_counter() - build_started) * 1000.0

        phases = _phase_windows(captures)
        combined = np.concatenate([samples for _, samples, _ in captures])
        run = await asyncio.to_thread(
            candidate.run_official_lifecycle,
            reference_samples,
            reference_sample_rate=reference_rate,
            samples=combined,
            sample_rate=reference_rate,
        )
        target_embedding = run.target_embedding
        target_norm = float(np.linalg.norm(target_embedding))

        required = (
            "B1_PHONE_ONLY",
            "G_OWNER_PLUS_PHONE",
            "B2_PHONE_ONLY",
            "A_OWNER_ONLY",
        )
        filtered_stats = {
            name: _summarize_phase(
                run.filtered_probabilities,
                frame_seconds=run.frame_seconds,
                phase=phases[name],
                threshold=_DIAGNOSTIC_THRESHOLD,
            )
            for name in required
        }
        raw_stats = {
            name: _summarize_phase(
                run.raw_probabilities,
                frame_seconds=run.frame_seconds,
                phase=phases[name],
                threshold=_DIAGNOSTIC_THRESHOLD,
            )
            for name in required
        }

        g_phase = phases["G_OWNER_PLUS_PHONE"]
        b2_phase = phases["B2_PHONE_ONLY"]
        a_phase = phases["A_OWNER_ONLY"]
        owner_onset_g_ms = _transition_ms(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            boundary_seconds=g_phase.start_seconds,
            phase_end_seconds=g_phase.end_seconds,
            threshold=_DIAGNOSTIC_THRESHOLD,
            consecutive_frames=_ONSET_FRAMES,
            above=True,
        )
        owner_offset_b2_ms = _transition_ms(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            boundary_seconds=b2_phase.start_seconds,
            phase_end_seconds=b2_phase.end_seconds,
            threshold=_DIAGNOSTIC_THRESHOLD,
            consecutive_frames=_OFFSET_FRAMES,
            above=False,
        )
        owner_reacquire_a_ms = _transition_ms(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            boundary_seconds=a_phase.start_seconds,
            phase_end_seconds=a_phase.end_seconds,
            threshold=_DIAGNOSTIC_THRESHOLD,
            consecutive_frames=_ONSET_FRAMES,
            above=True,
        )
        b2_after_025 = _active_fraction_after(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            phase=b2_phase,
            threshold=_DIAGNOSTIC_THRESHOLD,
            offset_seconds=0.25,
        )
        b2_after_050 = _active_fraction_after(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            phase=b2_phase,
            threshold=_DIAGNOSTIC_THRESHOLD,
            offset_seconds=0.50,
        )
        b2_after_100 = _active_fraction_after(
            run.filtered_probabilities,
            frame_seconds=run.frame_seconds,
            phase=b2_phase,
            threshold=_DIAGNOSTIC_THRESHOLD,
            offset_seconds=1.00,
        )

        print("\nFireRed official-parity target-speaker evidence")
        print(f"  model_build_ms = {model_build_ms:.1f}")
        print(
            f"  first-utterance warmup = {run.warmup_frames} frame(s) | "
            f"processing={run.warmup_processing_seconds * 1000.0:.1f} ms"
        )
        print(
            f"  ECAPA target embedding = dim={target_embedding.shape[1]} | "
            f"norm={target_norm:.4f} | {run.embedding_ms:.1f} ms"
        )
        print("  FILTERED probabilities (official ExpFilter output):")
        for name in required:
            item = filtered_stats[name]
            print(
                f"    {name}: frames={item.frame_count} | mean={item.mean:.4f} | "
                f"median={item.median:.4f} | p95={item.p95:.4f} | max={item.maximum:.4f} | "
                f"active_fraction={item.active_fraction:.3f}"
            )
        print("  RAW ONNX probabilities (diagnostic only):")
        for name in required:
            item = raw_stats[name]
            print(
                f"    {name}: mean={item.mean:.4f} | median={item.median:.4f} | "
                f"p95={item.p95:.4f} | active_fraction={item.active_fraction:.3f}"
            )

        print("\nOfficial-plugin transition semantics")
        print(
            "  OWNER onset during G = "
            + ("n/a" if owner_onset_g_ms is None else f"{owner_onset_g_ms:.0f} ms")
        )
        print(
            "  OWNER inactive while phone continues in B2 = "
            + ("n/a" if owner_offset_b2_ms is None else f"{owner_offset_b2_ms:.0f} ms")
        )
        print(
            "  OWNER reacquire after phone stops = "
            + (
                "n/a"
                if owner_reacquire_a_ms is None
                else f"{owner_reacquire_a_ms:.0f} ms"
            )
        )
        print(
            "  B2 filtered active_fraction after 0.25/0.50/1.00s = "
            f"{_format_optional(b2_after_025)} / {_format_optional(b2_after_050)} / "
            f"{_format_optional(b2_after_100)}"
        )

        latency = np.asarray(run.frame_latencies_ms, dtype=np.float64)
        median_ms = float(np.median(latency)) if latency.size else 0.0
        p95_ms = float(np.percentile(latency, 95)) if latency.size else 0.0
        max_ms = float(np.max(latency)) if latency.size else 0.0
        print("\nPerformance")
        print(
            f"  pVAD processing={run.processing_seconds * 1000.0:.1f} ms | "
            f"RTF={run.realtime_factor:.3f}"
        )
        print(f"  frame_ms median={median_ms:.3f} p95={p95_ms:.3f} max={max_ms:.3f}")

        print("\nBenchmark disposition")
        print("  official_plugin_source_modified = False")
        print("  target_embedding_persisted = False")
        print("  production_turn_gate_enabled = False")
        print("  Gemini_activity_detection_changed = False")
        print("  security_stream_filtered = False")
        print("  pVAD_threshold_promoted = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        print("STEP_3_PERSONALIZED_VAD_OFFICIAL_PARITY = EVIDENCE_CAPTURE_COMPLETE")
        print(
            "If phone-only remains comparable to or stronger than OWNER conditions under "
            "official lifecycle semantics, reject FireRed pVAD for JARVIS turn ownership."
        )
        return 0
    finally:
        if target_embedding is not None:
            target_embedding.fill(0.0)
        if reference_samples is not None:
            reference_samples.fill(0)
            del reference_samples
        for _, samples, _ in captures:
            samples.fill(0)
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
            "Benchmark FireRed pVAD using the official plugin lifecycle on canonical "
            "JARVIS PCM."
        )
    )
    parser.add_argument("--asset-dir", type=Path, default=None)
    parser.add_argument(
        "--reference-seconds",
        type=float,
        default=_DEFAULT_REFERENCE_SECONDS,
    )
    parser.add_argument(
        "--capture-seconds",
        type=float,
        default=_DEFAULT_CAPTURE_SECONDS,
    )
    parser.add_argument("--without-vision", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        exit_code = asyncio.run(
            run_official_parity_benchmark(
                asset_dir=args.asset_dir,
                reference_seconds=args.reference_seconds,
                capture_seconds=args.capture_seconds,
                with_vision=not args.without_vision,
            )
        )
    except (PersonalizedVadAssetError, FireRedOfficialParityUnavailable) as exc:
        raise SystemExit(str(exc)) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
