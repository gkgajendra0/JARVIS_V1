"""Production JARVIS voice-runtime assembly.

Conversation audio uses LiveKit MediaDevices/WebRTC AEC at 48 kHz. The paired
GStreamer sensor path is retained independently for synchronized raw Pocket3
video/audio evidence used by Step-3 active-speaker diagnostics.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from jarvis.config import JarvisConfig
from jarvis.identity.active_speaker import (
    ActiveSpeakerVisualBuffer,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.owner_context import (
    OwnerContextState,
    build_default_owner_context_observer,
)
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.logging_config import configure_logging
from jarvis.sensors.gstreamer_av import (
    GStreamerPairedAVConfig,
    GStreamerPairedAVSource,
)
from jarvis.sensors.windows_discovery import discover_windows_av_sources
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime
from jarvis.voice.runtime import VoiceRuntimeController
from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor

LOGGER = logging.getLogger(__name__)


def build_production_voice_runtime(config: JarvisConfig) -> VoiceRuntimeController:
    """Build the validated full-duplex runtime without custom echo/barge-in gates."""
    if config.wake_model_path is None:
        raise RuntimeError("JARVIS_WAKE_MODEL_PATH is required for Step-2 wake mode")
    if config.speaker_shadow_enabled and not config.vision_enabled:
        raise RuntimeError(
            "JARVIS_SPEAKER_SHADOW_ENABLED requires JARVIS_VISION_ENABLED because "
            "speaker prototype admission must be bound to independent live-owner context"
        )
    if config.active_speaker_shadow_enabled and not config.speaker_shadow_enabled:
        raise RuntimeError(
            "JARVIS_ACTIVE_SPEAKER_SHADOW_ENABLED requires "
            "JARVIS_SPEAKER_SHADOW_ENABLED"
        )
    if config.active_speaker_shadow_enabled and config.active_speaker_model_path is None:
        raise RuntimeError(
            "JARVIS_LR_ASD_MODEL_PATH is required when active-speaker shadow is enabled"
        )

    predictor = load_livekit_predictor(Path(config.wake_model_path))
    detector = LiveKitWakeDetector(
        predictor,
        threshold=config.wake_threshold,
        debounce_seconds=config.wake_debounce_seconds,
    )

    # Conversation audio is always the proven LiveKit MediaDevices path. The
    # selected output must accept 48 kHz; the runtime fails closed otherwise.
    audio = MediaDevicesConversationRuntime(
        detector,
        input_device_name=config.audio_input_device,
        output_device_name=config.audio_output_device,
        pre_roll_seconds=config.audio_pre_roll_seconds,
        ring_buffer_seconds=config.audio_ring_buffer_seconds,
    )

    owner_context_state: OwnerContextState | None = None
    evidence_observer = None
    if config.speaker_shadow_enabled:
        evidence_observer = build_default_owner_context_observer()
        owner_context_state = evidence_observer.state

    active_speaker_visual_buffer: ActiveSpeakerVisualBuffer | None = None
    active_speaker_provider: LrAsdActiveSpeakerProvider | None = None
    active_speaker_audio_capture: InMemorySpeakerTurnCapture | None = None
    active_speaker_av_source: GStreamerPairedAVSource | None = None
    speech_region_detector: LiveKitSileroSpeechRegionDetector | None = None

    if config.active_speaker_shadow_enabled:
        assert config.active_speaker_model_path is not None
        discovered_sources = discover_windows_av_sources()
        if len(discovered_sources) != 1:
            raise RuntimeError(
                "active-speaker shadow requires exactly one physically paired Windows AV "
                f"source; discovered {len(discovered_sources)}"
            )

        active_speaker_audio_capture = InMemorySpeakerTurnCapture(
            max_turn_seconds=config.max_utterance_seconds
        )
        # Raw synchronized sensor evidence only. Conversation playback/AEC is
        # intentionally NOT routed through this graph anymore.
        active_speaker_av_source = GStreamerPairedAVSource(
            discovered_sources[0],
            GStreamerPairedAVConfig(audio_rate=48_000),
        )

        def on_paired_raw_audio(
            data: bytes,
            sample_rate: int,
            num_channels: int,
            samples_per_channel: int,
            observed_at_monotonic: float,
        ) -> None:
            assert active_speaker_audio_capture is not None
            active_speaker_audio_capture.push_frame(
                data,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
                observed_at_monotonic=observed_at_monotonic,
            )

        active_speaker_av_source.set_audio_frame_tap(on_paired_raw_audio)
        active_speaker_visual_buffer = ActiveSpeakerVisualBuffer(
            max_seconds=config.max_utterance_seconds + 1.0
        )
        active_speaker_provider = LrAsdActiveSpeakerProvider(
            config.active_speaker_model_path
        )
        speech_region_detector = LiveKitSileroSpeechRegionDetector()

    vision_service = (
        build_default_vision_service(
            head_model_path=config.vision_head_model_path,
            evidence_observer=evidence_observer,
            frame_pair_tap=(
                active_speaker_visual_buffer.observe
                if active_speaker_visual_buffer is not None
                else None
            ),
            camera_source=active_speaker_av_source,
        )
        if config.vision_enabled
        else None
    )

    if config.audio_output_wasapi_device is not None:
        LOGGER.info(
            "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE is no longer used for conversation "
            "playback; JARVIS_AUDIO_OUTPUT_DEVICE selects the LiveKit MediaDevices "
            "48 kHz render endpoint"
        )

    return VoiceRuntimeController(
        config,
        audio,
        vision_service=vision_service,
        owner_context_state=owner_context_state,
        active_speaker_visual_buffer=active_speaker_visual_buffer,
        active_speaker_provider=active_speaker_provider,
        active_speaker_audio_capture=active_speaker_audio_capture,
        active_speaker_av_source=active_speaker_av_source,
        speech_region_detector=speech_region_detector,
    )


async def _run_from_environment() -> None:
    config = JarvisConfig.from_environment()
    configure_logging(config.log_level)
    runtime = build_production_voice_runtime(config)
    await runtime.run()


def main() -> None:
    try:
        asyncio.run(_run_from_environment())
    except KeyboardInterrupt:
        LOGGER.info("JARVIS voice runtime stopped")


if __name__ == "__main__":
    main()
