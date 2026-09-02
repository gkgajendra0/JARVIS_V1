from __future__ import annotations

import argparse
import asyncio
import statistics
import sys

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder, segment_metrics
from jarvis.identity.speaker_shadow import (
    EnrolledSpeakerShadowObserver,
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.conversation_focus import (
    ConversationFocusUnavailable,
    build_hush_focus_processor,
    process_canonical_pcm,
)
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_CAPTURE_SECONDS = 6.0
_DEFAULT_STRENGTHS = (0.5, 1.0)


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


def _score_owner(
    observer: EnrolledSpeakerShadowObserver,
    samples: np.ndarray,
    sample_rate: int,
) -> tuple[str, float | None, float]:
    result = observer.score(samples, sample_rate=sample_rate)
    return result.state, result.max_reference_cosine, result.embedding_ms


def _format_score(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.4f}"


def _analyze_capture(
    observer: EnrolledSpeakerShadowObserver,
    *,
    label: str,
    samples: np.ndarray,
    sample_rate: int,
    strengths: tuple[float, ...],
) -> None:
    raw_metrics = segment_metrics(samples, sample_rate)
    raw_state, raw_score, raw_embedding_ms = _score_owner(
        observer,
        samples,
        sample_rate,
    )
    print(f"\n{label}")
    print(
        f"  raw: audio={raw_metrics.duration_seconds:.2f}s | "
        f"RMS={raw_metrics.rms_dbfs:.1f} dBFS | peak={raw_metrics.peak_dbfs:.1f} dBFS | "
        f"CAM++={_format_score(raw_score)} ({raw_state}, {raw_embedding_ms:.1f} ms)"
    )

    for strength in strengths:
        processor = build_hush_focus_processor(strength=strength)
        run = process_canonical_pcm(
            samples,
            sample_rate=sample_rate,
            processor=processor,
        )
        focused_metrics = segment_metrics(run.samples, sample_rate)
        focused_state, focused_score, focused_embedding_ms = _score_owner(
            observer,
            run.samples,
            sample_rate,
        )
        latencies = run.frame_latencies_ms
        median_ms = statistics.median(latencies) if latencies else 0.0
        p95_ms = float(np.percentile(latencies, 95)) if latencies else 0.0
        rms_delta = focused_metrics.rms_dbfs - raw_metrics.rms_dbfs
        score_delta = (
            focused_score - raw_score
            if focused_score is not None and raw_score is not None
            else None
        )
        score_delta_text = "n/a" if score_delta is None else f"{score_delta:+.4f}"
        print(
            f"  hush strength={strength:.2f}: RMS={focused_metrics.rms_dbfs:.1f} dBFS "
            f"(delta={rms_delta:+.1f} dB) | peak={focused_metrics.peak_dbfs:.1f} dBFS | "
            f"CAM++={_format_score(focused_score)} ({focused_state}, "
            f"delta={score_delta_text}, {focused_embedding_ms:.1f} ms)"
        )
        print(
            f"    focus processing={run.processing_seconds * 1000.0:.1f} ms | "
            f"RTF={run.realtime_factor:.3f} | frame_ms median={median_ms:.3f} "
            f"p95={p95_ms:.3f}"
        )
        del run


async def run_conversation_focus_benchmark(
    *,
    capture_seconds: float,
    strengths: tuple[float, ...],
    with_vision: bool,
) -> int:
    if sys.platform != "win32":
        print(
            "This real-machine conversation-focus benchmark currently targets Windows."
        )
        return 2
    if capture_seconds < 3.0:
        raise ValueError("capture_seconds must be at least 3 seconds")
    if not strengths:
        raise ValueError("at least one Hush strength is required")
    if any(not 0.0 <= strength <= 1.0 for strength in strengths):
        raise ValueError("Hush strengths must be in [0, 1]")

    config = JarvisConfig.from_environment()
    print("JARVIS Step 3 conversation-focus competing-speech benchmark")
    print("---------------------------------------------------------")
    print("BENCHMARK ONLY: production wake/Gemini audio is unchanged.")
    print("Security/identity continues to own the unfiltered canonical mixed PCM.")
    print("Captured raw/focused audio stays in memory and is discarded on exit.")
    print("candidate = livekit-plugins-hush==0.3.3")
    print(f"strengths = {', '.join(f'{item:.2f}' for item in strengths)}")

    try:
        observer = build_default_enrolled_speaker_observer()
    except SpeakerShadowRuntimeError as exc:
        raise RuntimeError(
            f"CAM++ OWNER observer is required for this benchmark: {exc}"
        ) from exc

    vision_service = None
    if with_vision:
        vision_service = build_default_vision_service(
            head_model_path=config.vision_head_model_path,
        )
        print("Vision contention probe = enabled")
    else:
        print("Vision contention probe = disabled")

    # Fail early before opening hardware if the optional candidate is unavailable.
    probe = build_hush_focus_processor(strength=strengths[0])
    probe._close()

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
    captures: dict[str, tuple[np.ndarray, int]] = {}
    try:
        if vision_service is not None:
            await asyncio.to_thread(vision_service.start)
            vision_started = True
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-conversation-focus-benchmark-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        captures["A_OWNER_ONLY"] = await _capture(
            recorder,
            label="A OWNER ONLY",
            instructions=(
                "Keep phone/TV/other voices silent. Speak naturally for the whole capture."
            ),
            duration_seconds=capture_seconds,
        )
        captures["B_PHONE_ONLY"] = await _capture(
            recorder,
            label="B PHONE ONLY",
            instructions=(
                "Stay completely silent. Play continuous human speech from the phone at "
                "the same room position/volume you used when JARVIS could not answer."
            ),
            duration_seconds=capture_seconds,
        )
        captures["G_OWNER_PLUS_PHONE"] = await _capture(
            recorder,
            label="G OWNER + PHONE",
            instructions=(
                "Keep the same phone speech continuous and speak naturally yourself for "
                "most of the capture. Do not alternate; overlap the voices."
            ),
            duration_seconds=capture_seconds,
        )

        for label, (samples, sample_rate) in captures.items():
            await asyncio.to_thread(
                _analyze_capture,
                observer,
                label=label,
                samples=samples,
                sample_rate=sample_rate,
                strengths=strengths,
            )

        print("\nBenchmark disposition")
        print("  production_focus_enabled = False")
        print("  Gemini_activity_detection_changed = False")
        print("  security_stream_filtered = False")
        print("  authority_effect = False")
        print("  raw_audio_saved = False")
        print("STEP_3_CONVERSATION_FOCUS_BENCHMARK = EVIDENCE_CAPTURE_COMPLETE")
        print(
            "Do not select Hush from vendor claims alone; compare OWNER preservation, "
            "phone attenuation, overlap behavior, and latency from this machine output."
        )
        return 0
    finally:
        for samples, _ in captures.values():
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
            "Benchmark a separate local competing-speech focus branch on canonical "
            "JARVIS PCM without changing production conversation or security evidence."
        )
    )
    parser.add_argument(
        "--capture-seconds",
        type=float,
        default=_DEFAULT_CAPTURE_SECONDS,
    )
    parser.add_argument(
        "--strength",
        action="append",
        type=float,
        default=None,
        help="Repeat to test one or more Hush wet strengths in [0,1].",
    )
    parser.add_argument(
        "--without-vision",
        action="store_true",
        help="Skip normal RF-DETR Vision contention during the benchmark.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    strengths = tuple(args.strength) if args.strength else _DEFAULT_STRENGTHS
    try:
        code = asyncio.run(
            run_conversation_focus_benchmark(
                capture_seconds=args.capture_seconds,
                strengths=strengths,
                with_vision=not args.without_vision,
            )
        )
    except (ConversationFocusUnavailable, ValueError, RuntimeError) as exc:
        print(f"conversation-focus benchmark failed: {exc}")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
