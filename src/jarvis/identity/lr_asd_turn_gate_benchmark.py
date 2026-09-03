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
from jarvis.identity.active_speaker import (
    ActiveSpeakerState,
    ActiveSpeakerVisualBuffer,
    ActiveSpeakerVisualWindow,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.active_speaker_benchmark import (
    _NoOpWakeDetector,
    _drain_audio,
    _establish_owner_lock,
)
from jarvis.identity.owner_context import build_default_owner_context_observer
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture, SpeakerTurnAudio
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime
from jarvis.voice.observed_audio import ObservedSessionAudioInput

_DEFAULT_PHASE_SECONDS = 4.0
_DEFAULT_WINDOW_SECONDS = 1.0
_DEFAULT_STEP_SECONDS = 0.20
_DEFAULT_THRESHOLD = 0.50
_DEFAULT_TRAILING_FRAMES = 5
_DEFAULT_STABLE_WINDOWS = 2
_DEFAULT_OWNER_WAIT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class SlidingObservation:
    window_end_monotonic: float
    phase: str
    state: str
    trailing_score: float | None
    mean_score: float | None
    median_score: float | None
    inference_ms: float | None
    visual_frames: int
    source_fps: float | None
    reason_codes: tuple[str, ...]


class _TraceProvider(LrAsdActiveSpeakerProvider):
    def __init__(self, model_path: str | Path, *, device: str | None = None) -> None:
        super().__init__(model_path, device=device)
        self._trace = np.empty(0, dtype=np.float32)

    def assess_with_trace(
        self,
        turn: SpeakerTurnAudio,
        visual: ActiveSpeakerVisualWindow,
        *,
        audio_turn_id: str,
        windows_session_id: str,
    ) -> tuple[Any, tuple[float, ...]]:
        self._trace = np.empty(0, dtype=np.float32)
        assessment = super().assess(
            turn,
            visual,
            audio_turn_id=audio_turn_id,
            windows_session_id=windows_session_id,
        )
        return assessment, tuple(float(value) for value in self._trace)

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
        self._trace = values.copy()
        return values


def _slice_turn(
    turn: SpeakerTurnAudio,
    *,
    start_monotonic: float,
    end_monotonic: float,
) -> SpeakerTurnAudio | None:
    if turn.start_monotonic is None or turn.end_monotonic is None:
        return None
    start = max(turn.start_monotonic, start_monotonic)
    end = min(turn.end_monotonic, end_monotonic)
    if end <= start:
        return None
    start_index = max(0, round((start - turn.start_monotonic) * turn.sample_rate))
    end_index = min(
        turn.samples.size,
        round((end - turn.start_monotonic) * turn.sample_rate),
    )
    if end_index <= start_index:
        return None
    samples = np.ascontiguousarray(turn.samples[start_index:end_index], dtype=np.int16)
    if samples.size == 0:
        return None
    actual_start = turn.start_monotonic + start_index / turn.sample_rate
    actual_end = turn.start_monotonic + end_index / turn.sample_rate
    return SpeakerTurnAudio(
        samples=samples,
        sample_rate=turn.sample_rate,
        start_monotonic=actual_start,
        end_monotonic=actual_end,
    )


def _phase_for_time(
    value: float,
    *,
    b1_end: float,
    g_end: float,
    b2_end: float,
) -> str:
    if value < b1_end:
        return "B1_PHONE_ONLY"
    if value < g_end:
        return "G_OWNER_PLUS_PHONE"
    if value < b2_end:
        return "B2_PHONE_ONLY"
    return "A_OWNER_ONLY"


def _stable_transition_delay_ms(
    observations: list[SlidingObservation],
    *,
    boundary_monotonic: float,
    threshold: float,
    active: bool,
    stable_windows: int,
) -> float | None:
    run: list[SlidingObservation] = []
    for item in observations:
        if item.window_end_monotonic < boundary_monotonic:
            continue
        score = item.trailing_score
        if score is None:
            run.clear()
            continue
        matches = score >= threshold if active else score < threshold
        if not matches:
            run.clear()
            continue
        run.append(item)
        if len(run) < stable_windows:
            continue
        decision = run[-1]
        inference_seconds = (decision.inference_ms or 0.0) / 1000.0
        return max(
            0.0,
            (decision.window_end_monotonic + inference_seconds - boundary_monotonic)
            * 1000.0,
        )
    return None


def _active_fraction(
    observations: list[SlidingObservation],
    *,
    phase: str,
    threshold: float,
) -> float | None:
    scores = [
        item.trailing_score
        for item in observations
        if item.phase == phase and item.trailing_score is not None
    ]
    if not scores:
        return None
    return sum(score >= threshold for score in scores) / len(scores)


async def _countdown() -> None:
    for value in (3, 2, 1):
        print(f"  {value}...", flush=True)
        await asyncio.sleep(1.0)


async def run_lr_asd_turn_gate_benchmark(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        print("This real-machine LR-ASD turn-gate benchmark currently targets Windows.")
        return 2
    for name, value in (
        ("phase-seconds", args.phase_seconds),
        ("window-seconds", args.window_seconds),
        ("step-seconds", args.step_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if args.window_seconds < 1.0:
        raise ValueError("LR-ASD benchmark window must be at least 1.0 second")
    if args.step_seconds > args.window_seconds:
        raise ValueError("step-seconds must not exceed window-seconds")
    if not 1 <= args.trailing_frames <= 25:
        raise ValueError("trailing-frames must be in [1, 25]")
    if not 1 <= args.stable_windows <= 5:
        raise ValueError("stable-windows must be in [1, 5]")
    if not 0.0 < args.threshold < 1.0:
        raise ValueError("diagnostic threshold must be in (0, 1)")

    config = JarvisConfig.from_environment()
    if not config.vision_enabled:
        raise RuntimeError("LR-ASD turn-gate benchmark requires JARVIS Vision")
    model_path = args.model or config.active_speaker_model_path
    if model_path is None:
        raise RuntimeError("No LR-ASD model configured; run jarvis-setup first")

    total_seconds = args.phase_seconds * 4.0
    owner_observer = build_default_owner_context_observer()
    owner_state = owner_observer.state
    visual_buffer = ActiveSpeakerVisualBuffer(max_seconds=total_seconds + 6.0)
    vision_service = build_default_vision_service(
        head_model_path=config.vision_head_model_path,
        evidence_observer=owner_observer,
        frame_pair_tap=visual_buffer.observe,
    )
    provider = _TraceProvider(model_path, device=args.device)
    turn_capture = InMemorySpeakerTurnCapture(max_turn_seconds=total_seconds + 4.0)

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
    turn: SpeakerTurnAudio | None = None

    print("JARVIS Step 3 LR-ASD sliding OWNER-speaking gate benchmark")
    print("---------------------------------------------------------")
    print("BENCHMARK ONLY: production Gemini/barge-in/trust/authority are unchanged.")
    print(
        "One canonical Pocket3 audio stream + the existing timestamped OWNER head track."
    )
    print("No raw audio/video/crops are written to disk.")
    print(f"window_seconds = {args.window_seconds:.2f}")
    print(f"step_seconds = {args.step_seconds:.2f}")
    print(f"diagnostic_activity_threshold = {args.threshold:.3f}")
    print(f"trailing_frames = {args.trailing_frames}")
    print(f"stable_windows = {args.stable_windows}")
    print("deployment_threshold_selected = False")
    print("production_turn_gate_enabled = False")

    try:
        await asyncio.to_thread(vision_service.start)
        vision_started = True
        await audio.start()
        consumer_task = asyncio.create_task(
            _drain_audio(session_input),
            name="jarvis-lr-asd-turn-gate-audio-drain",
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
        print("Continuous sequence instructions:")
        print("  1. Start continuous human speech on the phone and stay SILENT.")
        print("  2. First cue: keep phone playing and START speaking yourself.")
        print("  3. Second cue: STOP yourself; keep the SAME phone speech playing.")
        print("  4. Third cue: STOP phone and START speaking yourself.")
        print("  Keep your face visible to Pocket3 for the whole sequence.")
        command = await asyncio.to_thread(input, "Phone ready? Press Enter to begin > ")
        if command.strip().casefold() in {"q", "quit", "exit"}:
            return 130

        print("  Get ready. Do not change state yet.")
        await _countdown()
        turn_capture.clear()
        b1_start = time.monotonic()
        print(
            f"  >>> B1 PHONE ONLY — STAY SILENT ({args.phase_seconds:.1f}s) <<<",
            flush=True,
        )
        await asyncio.sleep(args.phase_seconds)

        b1_end = time.monotonic()
        print(
            f"  >>> G START SPEAKING — KEEP PHONE ({args.phase_seconds:.1f}s) <<<",
            flush=True,
        )
        await asyncio.sleep(args.phase_seconds)

        g_end = time.monotonic()
        print(
            f"  >>> B2 STOP SPEAKING — KEEP PHONE ({args.phase_seconds:.1f}s) <<<",
            flush=True,
        )
        await asyncio.sleep(args.phase_seconds)

        b2_end = time.monotonic()
        print(
            f"  >>> A STOP PHONE + START SPEAKING ({args.phase_seconds:.1f}s) <<<",
            flush=True,
        )
        await asyncio.sleep(args.phase_seconds)
        print("  >>> STOP <<<", flush=True)
        capture_end = time.monotonic()

        turn = turn_capture.snapshot_recent_audio(clear=True)
        if turn is None or turn.start_monotonic is None or turn.end_monotonic is None:
            raise RuntimeError("canonical continuous LR-ASD audio capture was empty")

        print("\nScoring 1-second sliding audiovisual windows...")
        observations: list[SlidingObservation] = []
        first_end = max(
            turn.start_monotonic + args.window_seconds,
            b1_start + args.window_seconds,
        )
        last_end = min(turn.end_monotonic, capture_end)
        end_time = first_end
        while end_time <= last_end + 1e-6:
            window_start = end_time - args.window_seconds
            phase = _phase_for_time(
                end_time,
                b1_end=b1_end,
                g_end=g_end,
                b2_end=b2_end,
            )
            audio_window = _slice_turn(
                turn,
                start_monotonic=window_start,
                end_monotonic=end_time,
            )
            visual = visual_buffer.build_window(
                visual_track_id=owner_track_id,
                start_monotonic=window_start,
                end_monotonic=end_time,
                max_duration_seconds=args.window_seconds,
            )
            if audio_window is None or visual is None:
                observations.append(
                    SlidingObservation(
                        window_end_monotonic=end_time,
                        phase=phase,
                        state=ActiveSpeakerState.INSUFFICIENT.value,
                        trailing_score=None,
                        mean_score=None,
                        median_score=None,
                        inference_ms=None,
                        visual_frames=0 if visual is None else len(visual.frames),
                        source_fps=None if visual is None else visual.source_fps,
                        reason_codes=("sliding_audio_or_visual_window_insufficient",),
                    )
                )
                end_time += args.step_seconds
                continue

            started = time.perf_counter()
            assessment, trace = await asyncio.to_thread(
                provider.assess_with_trace,
                audio_window,
                visual,
                audio_turn_id=f"lr-asd-gate-{uuid.uuid4()}",
                windows_session_id=windows_session_id,
            )
            inference_ms = (time.perf_counter() - started) * 1000.0
            trailing_score: float | None = None
            if assessment.state == ActiveSpeakerState.SCORED and trace:
                tail = trace[-min(args.trailing_frames, len(trace)) :]
                trailing_score = float(statistics.median(tail))
            observations.append(
                SlidingObservation(
                    window_end_monotonic=end_time,
                    phase=phase,
                    state=assessment.state.value,
                    trailing_score=trailing_score,
                    mean_score=assessment.mean_score,
                    median_score=assessment.median_score,
                    inference_ms=inference_ms,
                    visual_frames=assessment.visual_frames,
                    source_fps=visual.source_fps,
                    reason_codes=assessment.reason_codes,
                )
            )
            end_time += args.step_seconds

        scored = [item for item in observations if item.trailing_score is not None]
        inference_values = [
            item.inference_ms for item in scored if item.inference_ms is not None
        ]

        print("\nSliding phase evidence")
        for phase in (
            "B1_PHONE_ONLY",
            "G_OWNER_PLUS_PHONE",
            "B2_PHONE_ONLY",
            "A_OWNER_ONLY",
        ):
            phase_scores = [
                item.trailing_score
                for item in observations
                if item.phase == phase and item.trailing_score is not None
            ]
            if not phase_scores:
                print(f"  {phase}: scored_windows=0")
                continue
            active_fraction = _active_fraction(
                observations,
                phase=phase,
                threshold=args.threshold,
            )
            print(
                f"  {phase}: scored_windows={len(phase_scores)} | "
                f"mean={statistics.mean(phase_scores):.4f} | "
                f"median={statistics.median(phase_scores):.4f} | "
                f"min={min(phase_scores):.4f} | max={max(phase_scores):.4f} | "
                f"active_fraction={active_fraction:.3f}"
            )

        owner_onset_ms = _stable_transition_delay_ms(
            observations,
            boundary_monotonic=b1_end,
            threshold=args.threshold,
            active=True,
            stable_windows=args.stable_windows,
        )
        owner_inactive_ms = _stable_transition_delay_ms(
            observations,
            boundary_monotonic=g_end,
            threshold=args.threshold,
            active=False,
            stable_windows=args.stable_windows,
        )
        owner_reacquire_ms = _stable_transition_delay_ms(
            observations,
            boundary_monotonic=b2_end,
            threshold=args.threshold,
            active=True,
            stable_windows=args.stable_windows,
        )

        print("\nProjected live transition availability")
        print(
            "  OWNER onset after B1->G = "
            + ("n/a" if owner_onset_ms is None else f"{owner_onset_ms:.0f} ms")
        )
        print(
            "  OWNER inactive while phone continues after G->B2 = "
            + ("n/a" if owner_inactive_ms is None else f"{owner_inactive_ms:.0f} ms")
        )
        print(
            "  OWNER reacquire after phone stops B2->A = "
            + ("n/a" if owner_reacquire_ms is None else f"{owner_reacquire_ms:.0f} ms")
        )
        print(
            "  NOTE: projected availability = sliding window end time + measured "
            "LR-ASD inference; production scheduler overhead is not included."
        )

        print("\nPerformance")
        print(f"  total_windows = {len(observations)} | scored = {len(scored)}")
        if inference_values:
            ordered = sorted(inference_values)
            p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
            print(
                f"  inference_ms median={statistics.median(ordered):.1f} | "
                f"p95={ordered[p95_index]:.1f} | max={max(ordered):.1f}"
            )

        b1_fraction = _active_fraction(
            observations,
            phase="B1_PHONE_ONLY",
            threshold=args.threshold,
        )
        g_fraction = _active_fraction(
            observations,
            phase="G_OWNER_PLUS_PHONE",
            threshold=args.threshold,
        )
        b2_fraction = _active_fraction(
            observations,
            phase="B2_PHONE_ONLY",
            threshold=args.threshold,
        )
        a_fraction = _active_fraction(
            observations,
            phase="A_OWNER_ONLY",
            threshold=args.threshold,
        )
        structural_pass = bool(
            b1_fraction is not None
            and g_fraction is not None
            and b2_fraction is not None
            and a_fraction is not None
            and b1_fraction <= 0.25
            and g_fraction >= 0.60
            and b2_fraction <= 0.25
            and a_fraction >= 0.60
            and owner_inactive_ms is not None
            and owner_reacquire_ms is not None
        )

        print("\nSafety disposition")
        print("  production_turn_gate_enabled = False")
        print("  LR_ASD_threshold_promoted = False")
        print("  Gemini_activity_detection_changed = False")
        print("  security_stream_filtered = False")
        print("  T2_or_authority_effect = False")
        print("  raw_audio_saved = False")
        print("  raw_video_saved = False")
        print(
            "STEP_3_LR_ASD_SLIDING_TURN_GATE = "
            + ("STRUCTURAL_PASS" if structural_pass else "NEEDS_REVIEW")
        )
        return 0
    finally:
        if turn is not None:
            turn.samples.fill(0)
        turn_capture.clear()
        visual_buffer.clear()
        audio.deactivate_session()
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        await audio.aclose()
        if vision_started:
            await asyncio.to_thread(vision_service.stop)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark LR-ASD as a one-second sliding visible-OWNER-speaking gate "
            "for competing phone/TV speech."
        )
    )
    parser.add_argument("--phase-seconds", type=float, default=_DEFAULT_PHASE_SECONDS)
    parser.add_argument("--window-seconds", type=float, default=_DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--step-seconds", type=float, default=_DEFAULT_STEP_SECONDS)
    parser.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD)
    parser.add_argument("--trailing-frames", type=int, default=_DEFAULT_TRAILING_FRAMES)
    parser.add_argument("--stable-windows", type=int, default=_DEFAULT_STABLE_WINDOWS)
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
        raise SystemExit(asyncio.run(run_lr_asd_turn_gate_benchmark(args)))
    except KeyboardInterrupt:
        print(
            "\nLR-ASD sliding turn-gate benchmark stopped; no raw media was persisted."
        )
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
