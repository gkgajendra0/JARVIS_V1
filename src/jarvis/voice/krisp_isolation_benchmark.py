from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.identity.owner_lane_benchmark import (
    _capture,
    _consume_frames,
    _NoOpWakeDetector,
    _score_phase,
)
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder, segment_metrics
from jarvis.identity.speaker_shadow import (
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.krisp_cloud_isolation import (
    KrispCloudIsolationRunner,
    KrispCloudIsolationUnavailable,
)
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_OWNER_PRIME_SECONDS = 4.0
_DEFAULT_CAPTURE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _PhaseComparison:
    label: str
    raw_rms_dbfs: float
    isolated_rms_dbfs: float
    rms_delta_db: float
    raw_campp: float | None
    isolated_campp: float | None
    campp_delta: float | None


def _slice_like(
    output: np.ndarray,
    captures: list[tuple[str, np.ndarray, int]],
) -> list[tuple[str, np.ndarray, int]]:
    result: list[tuple[str, np.ndarray, int]] = []
    cursor = 0
    for label, raw, sample_rate in captures:
        end = cursor + raw.size
        if end > output.size:
            raise RuntimeError(
                f"isolated output ended inside phase {label}: {output.size} < {end}"
            )
        result.append((label, np.ascontiguousarray(output[cursor:end]), sample_rate))
        cursor = end
    return result


def _comparison(observer, raw, isolated, *, label: str, sample_rate: int) -> _PhaseComparison:
    raw_metrics = segment_metrics(raw, sample_rate)
    isolated_metrics = segment_metrics(isolated, sample_rate)
    raw_score = observer.score(raw, sample_rate=sample_rate)
    isolated_score = observer.score(isolated, sample_rate=sample_rate)
    raw_campp = raw_score.max_reference_cosine
    isolated_campp = isolated_score.max_reference_cosine
    campp_delta = (
        None
        if raw_campp is None or isolated_campp is None
        else isolated_campp - raw_campp
    )
    return _PhaseComparison(
        label=label,
        raw_rms_dbfs=raw_metrics.rms_dbfs,
        isolated_rms_dbfs=isolated_metrics.rms_dbfs,
        rms_delta_db=isolated_metrics.rms_dbfs - raw_metrics.rms_dbfs,
        raw_campp=raw_campp,
        isolated_campp=isolated_campp,
        campp_delta=campp_delta,
    )


def _fmt_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.4f}"


async def run_krisp_isolation_benchmark(
    *,
    owner_prime_seconds: float,
    capture_seconds: float,
    with_vision: bool,
    suppression_level: int,
) -> int:
    if sys.platform != "win32":
        print("This real-machine Krisp benchmark currently targets Windows.")
        return 2
    if owner_prime_seconds < 3.0:
        raise ValueError("owner_prime_seconds must be at least 3 seconds")
    if capture_seconds < 3.0:
        raise ValueError("capture_seconds must be at least 3 seconds")

    config = JarvisConfig.from_environment()
    try:
        owner_observer = build_default_enrolled_speaker_observer()
    except SpeakerShadowRuntimeError as exc:
        raise RuntimeError(f"CAM++ OWNER observer is required: {exc}") from exc

    print("JARVIS Step 3 Krisp VIVA conversation-isolation benchmark")
    print("-----------------------------------------------------------")
    print("BENCHMARK ONLY: production wake/Gemini/barge-in are unchanged.")
    print("Canonical RAW PCM remains the security/identity source of truth.")
    print("A memory-only replay copy is sent through a temporary LiveKit Cloud room.")
    print("No captured benchmark audio is intentionally written to disk by JARVIS.")
    print("candidate = livekit-plugins-krisp 0.3.0 / voice_isolation")
    print(f"noise_suppression_level = {suppression_level}")
    print("cloud_auth = LiveKit room JWT")
    print("production_turn_gate_enabled = False")

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
    session_input = SessionAudioInput(capacity_frames=6_000)
    recorder = InMemorySegmentRecorder()
    consumer_task: asyncio.Task[None] | None = None
    vision_started = False
    captures: list[tuple[str, np.ndarray, int]] = []
    isolated_captures: list[tuple[str, np.ndarray, int]] = []

    try:
        if vision_service is not None:
            await asyncio.to_thread(vision_service.start)
            vision_started = True
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-krisp-isolation-benchmark-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.2)

        scenarios = (
            (
                "S_OWNER_PRIME",
                "Phone/TV completely silent. Speak naturally yourself for the whole capture. "
                "This primes the conversation before competing speech appears.",
                owner_prime_seconds,
            ),
            (
                "B1_PHONE_ONLY",
                "Stay completely silent. Play continuous human speech from the phone at normal room volume.",
                capture_seconds,
            ),
            (
                "G_OWNER_PLUS_PHONE",
                "Keep the SAME phone speech continuous and speak yourself at the same time for most of the capture.",
                capture_seconds,
            ),
            (
                "B2_PHONE_ONLY",
                "Stop speaking yourself but KEEP the same phone speech continuous for the whole capture.",
                capture_seconds,
            ),
            (
                "A_OWNER_ONLY",
                "Stop the phone completely. Speak naturally yourself for the whole capture.",
                capture_seconds,
            ),
        )
        expected_rate: int | None = None
        for label, instructions, seconds in scenarios:
            samples, sample_rate = await _capture(
                recorder,
                label=label,
                instructions=instructions,
                duration_seconds=seconds,
            )
            if expected_rate is None:
                expected_rate = sample_rate
            elif sample_rate != expected_rate:
                raise RuntimeError("canonical sample rate changed between Krisp captures")
            captures.append((label, samples, sample_rate))

        assert expected_rate is not None
        if expected_rate != 48_000:
            raise RuntimeError(
                f"Krisp benchmark expected canonical 48 kHz PCM, got {expected_rate} Hz"
            )

        print("\nRAW capture sanity / existing CAM++ shadow")
        for label, samples, sample_rate in captures:
            await asyncio.to_thread(
                _score_phase,
                owner_observer,
                label,
                samples,
                sample_rate,
            )

        combined = np.concatenate([samples for _, samples, _ in captures])
        runner = KrispCloudIsolationRunner(
            noise_suppression_level=suppression_level
        )
        print("\nReplaying the exact captured sequence through Krisp VIVA...")
        isolation = await runner.run(combined, sample_rate=expected_rate)
        isolated_captures = _slice_like(isolation.samples, captures)

        comparisons: list[_PhaseComparison] = []
        for (label, raw, sample_rate), (_, isolated, _) in zip(
            captures,
            isolated_captures,
            strict=True,
        ):
            comparisons.append(
                await asyncio.to_thread(
                    _comparison,
                    owner_observer,
                    raw,
                    isolated,
                    label=label,
                    sample_rate=sample_rate,
                )
            )

        print("\nRAW vs KRISP-ISOLATED evidence")
        print("  RMS delta: negative means Krisp attenuated that phase.")
        print("  CAM++ delta: positive means output moved toward enrolled OWNER voice.")
        for item in comparisons:
            print(
                f"  {item.label}: RMS {item.raw_rms_dbfs:.1f} -> "
                f"{item.isolated_rms_dbfs:.1f} dBFS ({item.rms_delta_db:+.1f} dB) | "
                f"CAM++ {_fmt_score(item.raw_campp)} -> "
                f"{_fmt_score(item.isolated_campp)} ({_fmt_delta(item.campp_delta)})"
            )

        by_label = {item.label: item for item in comparisons}
        print("\nDecision-focused deltas")
        for label in (
            "B1_PHONE_ONLY",
            "G_OWNER_PLUS_PHONE",
            "B2_PHONE_ONLY",
            "A_OWNER_ONLY",
        ):
            item = by_label[label]
            print(
                f"  {label}: attenuation={item.rms_delta_db:+.1f} dB | "
                f"CAM++ delta={_fmt_delta(item.campp_delta)}"
            )

        print("\nCloud benchmark performance")
        print(
            f"  input_audio={isolation.input_seconds:.2f}s | "
            f"isolated_output={isolation.output_seconds:.2f}s"
        )
        print(
            f"  end_to_end_wall={isolation.wall_seconds:.2f}s | "
            f"wall/audio={isolation.realtime_factor:.3f}"
        )
        print("  NOTE: wall time includes LiveKit Cloud transport + room setup, not just VIVA DSP.")

        print("\nSafety disposition")
        print("  security_stream_filtered = False")
        print("  production_turn_gate_enabled = False")
        print("  Gemini_activity_detection_changed = False")
        print("  cloud_audio_path_benchmark_only = True")
        print("  raw_audio_saved_by_jarvis = False")
        print("  CAM++_threshold_promoted = False")
        print("  T2_or_authority_effect = False")
        print("STEP_3_KRISP_VIVA_BENCHMARK = EVIDENCE_CAPTURE_COMPLETE")
        print(
            "Human review must require strong phone suppression with OWNER preservation "
            "before any production-shadow integration."
        )
        return 0
    finally:
        for _, samples, _ in isolated_captures:
            samples.fill(0)
        isolated_captures.clear()
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
            "Benchmark LiveKit Cloud-backed Krisp VIVA voice isolation against "
            "the accepted JARVIS canonical PCM path."
        )
    )
    parser.add_argument(
        "--owner-prime-seconds",
        type=float,
        default=_DEFAULT_OWNER_PRIME_SECONDS,
    )
    parser.add_argument(
        "--capture-seconds",
        type=float,
        default=_DEFAULT_CAPTURE_SECONDS,
    )
    parser.add_argument(
        "--suppression-level",
        type=int,
        default=75,
    )
    parser.add_argument("--without-vision", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        exit_code = asyncio.run(
            run_krisp_isolation_benchmark(
                owner_prime_seconds=args.owner_prime_seconds,
                capture_seconds=args.capture_seconds,
                with_vision=not args.without_vision,
                suppression_level=args.suppression_level,
            )
        )
    except KrispCloudIsolationUnavailable as exc:
        raise SystemExit(str(exc)) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
