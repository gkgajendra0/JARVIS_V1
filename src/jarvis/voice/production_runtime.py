"""Production JARVIS voice-runtime assembly.

Conversation audio uses LiveKit MediaDevices/WebRTC AEC at 48 kHz. Speaker
identity, overlap, and active-speaker diagnostics reuse the same canonical
timestamped user PCM. Identity diagnostics are parallel shadow observers and never
block normal conversation or grant authority.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from jarvis.config import JarvisConfig
from jarvis.identity.active_speaker import (
    ActiveSpeakerVisualBuffer,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.overlap_shadow import (
    NativeOverlapShadowObserver,
    build_default_overlap_shadow_observer,
)
from jarvis.identity.owner_context import (
    OwnerContextState,
    build_default_owner_context_observer,
)
from jarvis.identity.sortformer_assets import SortformerAssetError
from jarvis.identity.sortformer_native import SortformerNativeError
from jarvis.identity.speaker_shadow import (
    EnrolledSpeakerShadowObserver,
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.logging_config import configure_logging
from jarvis.preflight import StartupPreflightError, require_startup_preflight
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime
from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor

LOGGER = logging.getLogger(__name__)


def build_production_voice_runtime(
    config: JarvisConfig,
) -> CanonicalActiveSpeakerRuntimeController:
    """Build the production single-microphone-owner voice/vision runtime."""
    if config.wake_model_path is None:
        raise RuntimeError("wake model is required for Step-2 wake mode")
    if config.active_speaker_shadow_enabled and not config.speaker_shadow_enabled:
        raise RuntimeError("active-speaker shadow requires speaker shadow")
    if config.active_speaker_shadow_enabled and not config.vision_enabled:
        raise RuntimeError("active-speaker shadow requires vision")
    if (
        config.active_speaker_shadow_enabled
        and config.active_speaker_model_path is None
    ):
        raise RuntimeError(
            "LR-ASD model is required when active-speaker shadow is enabled"
        )

    predictor = load_livekit_predictor(Path(config.wake_model_path))
    detector = LiveKitWakeDetector(
        predictor,
        threshold=config.wake_threshold,
        debounce_seconds=config.wake_debounce_seconds,
    )

    # LiveKit MediaDevices is the only Pocket3 microphone owner. The selected
    # physical output must accept 48 kHz; the runtime fails closed otherwise.
    audio = MediaDevicesConversationRuntime(
        detector,
        input_device_name=config.audio_input_device,
        output_device_name=config.audio_output_device,
        pre_roll_seconds=config.audio_pre_roll_seconds,
        ring_buffer_seconds=config.audio_ring_buffer_seconds,
    )

    speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None
    if config.speaker_shadow_enabled:
        try:
            speaker_shadow_observer = build_default_enrolled_speaker_observer()
            LOGGER.info(
                "Enrolled CAM++ OWNER speaker shadow is loaded: %s prototypes; "
                "per-turn scoring is asynchronous and has no authority effect",
                speaker_shadow_observer.template.prototype_count,
            )
        except SpeakerShadowRuntimeError as exc:
            # Speaker shadow is diagnostic. Missing enrollment/model/dependency must
            # never make ordinary JARVIS conversation unavailable.
            LOGGER.warning(
                "Enrolled speaker shadow is unavailable and will stay disabled: %s",
                exc,
            )

    owner_context_state: OwnerContextState | None = None
    evidence_observer = None
    if config.vision_enabled and config.speaker_shadow_enabled:
        evidence_observer = build_default_owner_context_observer()
        owner_context_state = evidence_observer.state

    active_speaker_visual_buffer: ActiveSpeakerVisualBuffer | None = None
    active_speaker_provider: LrAsdActiveSpeakerProvider | None = None
    overlap_shadow_observer: NativeOverlapShadowObserver | None = None

    if config.active_speaker_shadow_enabled:
        assert config.active_speaker_model_path is not None
        active_speaker_visual_buffer = ActiveSpeakerVisualBuffer(
            max_seconds=config.max_utterance_seconds + 1.0
        )
        active_speaker_provider = LrAsdActiveSpeakerProvider(
            config.active_speaker_model_path
        )
        LOGGER.info(
            "Step-3 active-speaker diagnostics use one Pocket3 microphone owner: "
            "canonical LiveKit user PCM + timestamped Vision track/head frames"
        )
        try:
            overlap_shadow_observer = build_default_overlap_shadow_observer()
            LOGGER.info(
                "Native Sortformer overlap shadow is loaded: runtime=%s | "
                "model_load_ms=%.1f | per-turn scoring is asynchronous and has no "
                "authority effect",
                overlap_shadow_observer.runtime_version,
                overlap_shadow_observer.model_load_ms,
            )
        except (
            SortformerAssetError,
            SortformerNativeError,
            OSError,
            ValueError,
        ) as exc:
            # Step 3B.13 remains fail-open for conversation and fail-closed for
            # identity authority while the shadow integration is being accepted.
            LOGGER.warning(
                "Native Sortformer overlap shadow is unavailable and will stay disabled: %s",
                exc,
            )

    # Speaker identity needs clean voiced regions even when LR-ASD is disabled.
    # This detector runs only inside the already-background shadow turn task.
    speech_region_detector = (
        LiveKitSileroSpeechRegionDetector() if config.speaker_shadow_enabled else None
    )

    # Integrated desktop Vision is observable by default. The observer renders
    # the same canonical tracks/heads/target/follow/framing state JARVIS uses,
    # rather than opening a second camera path. An explicit environment value can
    # still disable the window for headless/quiet diagnostic runs.
    if config.vision_enabled:
        os.environ.setdefault("JARVIS_VISION_PREVIEW", "true")

    vision_service = (
        build_default_vision_service(
            head_model_path=config.vision_head_model_path,
            evidence_observer=evidence_observer,
            frame_pair_tap=(
                active_speaker_visual_buffer.observe
                if active_speaker_visual_buffer is not None
                else None
            ),
        )
        if config.vision_enabled
        else None
    )

    if config.audio_output_wasapi_device is not None:
        LOGGER.info(
            "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE is historical only; production uses "
            "JARVIS_AUDIO_OUTPUT_DEVICE through LiveKit MediaDevices"
        )

    return CanonicalActiveSpeakerRuntimeController(
        config,
        audio,
        vision_service=vision_service,
        owner_context_state=owner_context_state,
        active_speaker_visual_buffer=active_speaker_visual_buffer,
        active_speaker_provider=active_speaker_provider,
        speech_region_detector=speech_region_detector,
        speaker_shadow_observer=speaker_shadow_observer,
        overlap_shadow_observer=overlap_shadow_observer,
    )


async def _run_from_configuration() -> None:
    config = JarvisConfig.from_environment()
    configure_logging(config.log_level)
    require_startup_preflight(config)
    runtime = build_production_voice_runtime(config)
    await runtime.run()


def main() -> int:
    try:
        asyncio.run(_run_from_configuration())
        return 0
    except StartupPreflightError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        LOGGER.info("JARVIS voice runtime stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
