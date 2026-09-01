"""Shadow-only LR-ASD acceptance using one synchronized physical AV source.

Run one labeled scenario at a time while keeping the owner visible. The paired
GStreamer source owns Pocket3 video and its physically paired microphone so the
visual window and speech region share one capture clock. Results remain diagnostic:
active-speaker confirmation, speaker-template admission, trust, and authority are
never promoted by this runner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from dataclasses import asdict

from jarvis.config import JarvisConfig
from jarvis.identity.active_speaker import (
    ActiveSpeakerState,
    ActiveSpeakerVisualBuffer,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.owner_context import build_default_owner_context_observer
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.logging_config import configure_logging
from jarvis.sensors.gstreamer_av import (
    GStreamerPairedAVConfig,
    GStreamerPairedAVSource,
)
from jarvis.sensors.models import AVSourceDescriptor
from jarvis.sensors.windows_discovery import discover_windows_av_sources
from jarvis.vision.service import build_default_vision_service


def _select_source(
    sources: tuple[AVSourceDescriptor, ...],
    source_id: str | None,
) -> AVSourceDescriptor:
    if source_id is not None:
        matches = [source for source in sources if source.source_id == source_id]
        if len(matches) != 1:
            raise RuntimeError(f"AV source not found: {source_id}")
        return matches[0]
    if len(sources) != 1:
        raise RuntimeError(
            "exactly one paired AV source is required unless --source-id is supplied"
        )
    return sources[0]


def _insufficient(
    *,
    label: str,
    source: AVSourceDescriptor,
    pipeline_clock: str | None,
    reason: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": label,
        "source_id": source.source_id,
        "display_name": source.display_name,
        "pipeline_clock": pipeline_clock,
        "state": ActiveSpeakerState.INSUFFICIENT.value,
        "active_speaker_confirmed": False,
        "prototype_admission": False,
        "reason": reason,
    }
    if extra:
        payload.update(extra)
    return payload


async def _run(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    config = JarvisConfig.from_environment()
    configure_logging(config.log_level)
    if config.active_speaker_model_path is None:
        raise RuntimeError(
            "JARVIS_LR_ASD_MODEL_PATH is required for the paired active-speaker runner"
        )

    source = _select_source(discover_windows_av_sources(), args.source_id)
    capture = GStreamerPairedAVSource(
        source,
        GStreamerPairedAVConfig(audio_rate=16_000),
    )
    turn_capture = InMemorySpeakerTurnCapture(
        max_turn_seconds=max(args.duration + 1.0, 2.0)
    )
    turn_lock = threading.RLock()

    def on_audio(
        data: bytes,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
        observed_at_monotonic: float,
    ) -> None:
        with turn_lock:
            turn_capture.push_frame(
                data,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
                observed_at_monotonic=observed_at_monotonic,
            )

    capture.set_audio_frame_tap(on_audio)
    visual_buffer = ActiveSpeakerVisualBuffer(
        max_seconds=args.warmup + args.duration + 2.0
    )
    owner_observer = build_default_owner_context_observer()
    owner_state = owner_observer.state
    provider = LrAsdActiveSpeakerProvider(config.active_speaker_model_path)
    speech_detector = LiveKitSileroSpeechRegionDetector()
    vision_service = build_default_vision_service(
        head_model_path=config.vision_head_model_path,
        evidence_observer=owner_observer,
        frame_pair_tap=visual_buffer.observe,
        camera_source=capture,
    )

    started = False
    try:
        print(
            f"Warmup {args.warmup:.1f}s: stay visible to Pocket3; "
            "no score is being collected yet.",
            flush=True,
        )
        await asyncio.to_thread(vision_service.start)
        started = True
        await asyncio.sleep(args.warmup)
        pipeline_clock = capture.pipeline_clock_name
        if pipeline_clock != "GstAudioSrcClock":
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason="paired_av_audio_clock_not_selected",
                ),
                2,
            )
        if not owner_state.has_fresh_live_owner_candidate():
            snapshot = owner_state.snapshot()
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason=(
                        snapshot.invalidation_reason
                        or "no_fresh_live_owner_candidate_after_warmup"
                    ),
                ),
                2,
            )

        print(
            f"CAPTURE {args.duration:.1f}s [{args.label}]: "
            "perform only this scenario now.",
            flush=True,
        )
        with turn_lock:
            turn_capture.clear()
        await asyncio.sleep(args.duration)
        with turn_lock:
            turn = turn_capture.snapshot_recent_audio()
        if turn is None:
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason="paired_audio_turn_empty",
                ),
                2,
            )

        region = await speech_detector.extract(turn)
        if region.turn is None:
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason=region.reason,
                    extra={
                        "captured_seconds": round(turn.duration_seconds, 3),
                        "max_vad_probability": region.max_vad_probability,
                    },
                ),
                2,
            )
        speech_turn = region.turn
        quality = await asyncio.to_thread(
            assess_speaker_segment,
            speech_turn.samples,
            sample_rate=speech_turn.sample_rate,
        )
        if not quality.accepted:
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason="speaker_quality_rejected",
                    extra={
                        "captured_seconds": round(turn.duration_seconds, 3),
                        "speech_seconds": round(speech_turn.duration_seconds, 3),
                        "rms_dbfs": quality.rms_dbfs,
                        "quality_reason_codes": list(quality.reason_codes),
                        "speech_region_reason": region.reason,
                        "max_vad_probability": region.max_vad_probability,
                    },
                ),
                2,
            )

        context_snapshot = owner_state.snapshot()
        assessment = context_snapshot.assessment
        if assessment is None or not owner_state.has_fresh_live_owner_candidate():
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason=(
                        context_snapshot.invalidation_reason
                        or "no_fresh_live_owner_context_at_assessment"
                    ),
                ),
                2,
            )

        visual = visual_buffer.build_window(
            visual_track_id=assessment.visual_track_id,
            start_monotonic=speech_turn.start_monotonic or 0.0,
            end_monotonic=speech_turn.end_monotonic or 0.0,
        )
        if visual is None:
            return (
                _insufficient(
                    label=args.label,
                    source=source,
                    pipeline_clock=pipeline_clock,
                    reason="paired_visual_window_insufficient",
                    extra={
                        "visual_track_id": assessment.visual_track_id,
                        "captured_seconds": round(turn.duration_seconds, 3),
                        "speech_seconds": round(speech_turn.duration_seconds, 3),
                    },
                ),
                2,
            )

        result = await asyncio.to_thread(
            provider.assess,
            speech_turn,
            visual,
            audio_turn_id=f"paired-live:{args.label}:{time.time_ns()}",
            windows_session_id=assessment.session_id,
        )
        payload: dict[str, object] = {
            "label": args.label,
            "source_id": source.source_id,
            "display_name": source.display_name,
            "pipeline_clock": pipeline_clock,
            "state": result.state.value,
            "windows_session_id": result.windows_session_id,
            "visual_track_id": result.visual_track_id,
            "captured_seconds": round(turn.duration_seconds, 3),
            "speech_seconds": round(speech_turn.duration_seconds, 3),
            "speech_region_reason": region.reason,
            "speech_segments": region.segment_count,
            "max_vad_probability": region.max_vad_probability,
            "rms_dbfs": quality.rms_dbfs,
            "quality_reason_codes": list(quality.reason_codes),
            "visual_source_frames": visual.source_sample_count,
            "visual_unique_frames": visual.unique_source_frames,
            "visual_source_fps": round(visual.source_fps, 3),
            "visual_maximum_gap_ms": round(
                visual.maximum_source_gap_seconds * 1000,
                3,
            ),
            "assessment": asdict(result),
            "active_speaker_confirmed": False,
            "prototype_admission": False,
            "note": (
                "Shadow score only. No threshold, trust, authority, or speaker-template "
                "promotion is enabled."
            ),
        }
        return payload, 0 if result.state is ActiveSpeakerState.SCORED else 2
    finally:
        if started:
            await asyncio.to_thread(vision_service.stop)
        visual_buffer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label",
        required=True,
        help="Scenario label, e.g. owner-speaking or tv-speaking",
    )
    parser.add_argument("--source-id")
    parser.add_argument("--warmup", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=6.0)
    args = parser.parse_args()
    if args.warmup <= 0 or args.duration <= 0:
        raise ValueError("warmup and duration must be positive")

    payload, exit_code = asyncio.run(_run(args))
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
