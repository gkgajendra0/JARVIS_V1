"""Production JARVIS voice-runtime assembly.

Conversation audio uses LiveKit MediaDevices/WebRTC AEC at 48 kHz. Speaker
identity and active-speaker diagnostics reuse the same canonical timestamped user
PCM. Speaker identity is a parallel shadow observer and never blocks normal
conversation or grants authority.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from jarvis.capabilities.runtime import build_default_capability_runtime
from jarvis.capabilities.self_awareness_reads import SelfAwarenessReadExecutor
from jarvis.capability_acquisition.runtime_context import (
    CapabilityRuntimeAcquisitionContextProvider,
)
from jarvis.capability_registry.runtime_composition import (
    build_package_managed_runtime_stack,
)
from jarvis.ai_provider import require_provider_api_key
from jarvis.config import JarvisConfig
from jarvis.health_adapters import (
    CapabilityExecutionHealthObserver,
    ProviderResilienceHealthObserver,
    VoiceBehaviorHealthObserver,
    record_capability_catalog_health,
    record_foundation_health,
    record_hands_availability_health,
    require_startup_preflight_with_health,
)
from jarvis.identity.active_speaker import (
    ActiveSpeakerVisualBuffer,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.owner_context import (
    OwnerContextState,
    build_default_owner_context_observer,
)
from jarvis.identity.owner_evidence import OwnerIdentityThresholds
from jarvis.identity.passive_liveness import PassiveLivenessThresholds
from jarvis.identity.speaker_shadow import (
    EnrolledSpeakerShadowObserver,
    SpeakerShadowRuntimeError,
    build_default_enrolled_speaker_observer,
)
from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
from jarvis.knowledge.research_providers import build_current_research_service
from jarvis.logging_config import configure_logging
from jarvis.memory.candidate_runtime import MemoryCandidateSessionRuntime
from jarvis.memory.extractors import build_memory_candidate_extractor
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_interpreters import build_memory_query_interpreter
from jarvis.memory.release_guard import build_memory_release_guard
from jarvis.memory.runtime import build_default_memory_runtime
from jarvis.preflight import StartupPreflightError, require_startup_preflight
from jarvis.promotion.release import (
    DeploymentMetadataStore,
    default_deployment_root,
    load_active_release_for_startup,
)
from jarvis.promotion.runtime_composition import PromotionRuntimeConfig
from jarvis.provider_model_lifecycle import reconcile_gemini_live_model
from jarvis.provider_resilience import ProviderFailureKind, ProviderResilienceState
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.vision.camera import (
    OpenCVCameraConfig,
    OpenCVCameraSource,
    SwitchableCameraSource,
)
from jarvis.vision.health_observers import (
    NativeTrackingHealthObserver,
    VisionFrameHealthTap,
    compose_frame_pair_taps,
)
from jarvis.vision.native_owner_tracking import (
    SourceGatedNativeTrackingObserver,
    build_default_native_owner_tracking_observer,
)
from jarvis.vision.service import build_default_vision_service
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.local_status_speech import build_local_status_speech
from jarvis.voice.media_devices_audio import (
    MediaDevicesAudioOutput,
    MediaDevicesConversationRuntime,
)
from jarvis.voice.provider_resilience import ProviderResilienceSessionObserver
from jarvis.voice.silent_audio_recovery import SilentRealtimeAudioRecovery
from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor
from jarvis.work.runtime import build_work_runtime

LOGGER = logging.getLogger(__name__)

_PROVIDER_MODEL_LIFECYCLE_POLL_SECONDS = 6 * 60 * 60
_NATIVE_TRACKING_EVIDENCE_MAX_GAP_SECONDS = 2.0
_POCKET3_STARTUP_LOCK_WAIT_SECONDS = 30.0


def _build_production_camera_source(config: JarvisConfig) -> SwitchableCameraSource:
    """Build named physical eyes with Lenovo fixed RGB as the default profile."""
    return SwitchableCameraSource(
        {
            "lenovo": OpenCVCameraSource(
                OpenCVCameraConfig(
                    device_index=config.vision_lenovo_device_index,
                    width=1920,
                    height=1080,
                    backend="dshow",
                    fps=30.0,
                    codec="MJPG",
                )
            ),
            "pocket3": OpenCVCameraSource(
                OpenCVCameraConfig(
                    device_index=config.vision_pocket3_device_index,
                    width=1280,
                    height=720,
                    backend="dshow",
                )
            ),
        },
        default_source=config.vision_default_camera,
    )


def build_production_voice_runtime(
    config: JarvisConfig,
    *,
    self_awareness: SelfAwarenessRuntime | None = None,
    provider_lifecycle_trigger: asyncio.Event | None = None,
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

    audio = MediaDevicesConversationRuntime(
        detector,
        input_device_name=config.audio_input_device,
        output_device_name=config.audio_output_device,
        pre_roll_seconds=config.audio_pre_roll_seconds,
        ring_buffer_seconds=config.audio_ring_buffer_seconds,
    )

    camera_source = (
        _build_production_camera_source(config) if config.vision_enabled else None
    )
    if camera_source is not None:
        LOGGER.info(
            "Physical vision cameras configured: default=%s Lenovo(index=%s, "
            "1920x1080 MJPG 30 FPS) Pocket3(index=%s, on-demand)",
            camera_source.active_source_name,
            config.vision_lenovo_device_index,
            config.vision_pocket3_device_index,
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
            LOGGER.warning(
                "Enrolled speaker shadow is unavailable and will stay disabled: %s",
                exc,
            )

    owner_context_state: OwnerContextState | None = None
    evidence_observer = None
    owner_context_required = config.vision_enabled and (
        config.speaker_shadow_enabled or config.pocket3_native_tracking_enabled
    )
    if owner_context_required:
        if config.pocket3_native_tracking_enabled:
            evidence_observer = build_default_owner_context_observer(
                identity_thresholds=OwnerIdentityThresholds(
                    max_inter_observation_gap_seconds=(
                        _NATIVE_TRACKING_EVIDENCE_MAX_GAP_SECONDS
                    )
                ),
                liveness_thresholds=PassiveLivenessThresholds(
                    max_inter_observation_gap_seconds=(
                        _NATIVE_TRACKING_EVIDENCE_MAX_GAP_SECONDS
                    )
                ),
            )
        else:
            evidence_observer = build_default_owner_context_observer()
        owner_context_state = evidence_observer.state

    tracking_observer = None
    if config.pocket3_native_tracking_enabled:
        assert owner_context_state is not None
        native_tracking_observer = build_default_native_owner_tracking_observer(
            owner_context=owner_context_state,
            ble_name=config.pocket3_ble_name,
            owner_evidence_max_age_seconds=(
                config.pocket3_owner_evidence_max_age_seconds
            ),
            subject_push_stale_seconds=config.pocket3_subject_push_stale_seconds,
            lock_pending_timeout_seconds=(config.pocket3_lock_pending_timeout_seconds),
            resend_cooldown_seconds=config.pocket3_resend_cooldown_seconds,
            locked_perception_fps=1.0,
        )
        observed_native_tracking = (
            NativeTrackingHealthObserver(native_tracking_observer, self_awareness)
            if self_awareness is not None
            else native_tracking_observer
        )
        assert camera_source is not None
        tracking_observer = SourceGatedNativeTrackingObserver(
            observed_native_tracking,
            active_source_provider=lambda: camera_source.active_source_name,
            required_source="pocket3",
            inactive_perception_fps=10.0,
        )
        LOGGER.info(
            "Pocket 3 native OWNER tracking is retained but dormant unless Pocket3 "
            "is the selected vision camera; Lenovo remains the normal fixed-camera path"
        )

    active_speaker_visual_buffer: ActiveSpeakerVisualBuffer | None = None
    active_speaker_provider: LrAsdActiveSpeakerProvider | None = None

    if config.active_speaker_shadow_enabled:
        assert config.active_speaker_model_path is not None
        active_speaker_visual_buffer = ActiveSpeakerVisualBuffer(
            max_seconds=config.max_utterance_seconds + 1.0
        )
        active_speaker_provider = LrAsdActiveSpeakerProvider(
            config.active_speaker_model_path
        )
        LOGGER.info(
            "Step-3 active-speaker diagnostics use the selected conversation microphone: "
            "canonical LiveKit user PCM + timestamped selected-camera Vision track/head frames"
        )

    speech_region_detector = (
        LiveKitSileroSpeechRegionDetector() if config.speaker_shadow_enabled else None
    )
    vision_health_tap = (
        VisionFrameHealthTap(self_awareness) if self_awareness is not None else None
    )
    active_speaker_tap = (
        active_speaker_visual_buffer.observe
        if active_speaker_visual_buffer is not None
        else None
    )

    vision_service = (
        build_default_vision_service(
            head_model_path=config.vision_head_model_path,
            evidence_observer=evidence_observer,
            tracking_observer=tracking_observer,
            frame_pair_tap=compose_frame_pair_taps(
                active_speaker_tap,
                vision_health_tap,
            ),
            camera_source=camera_source,
            perception_fps_provider=(
                tracking_observer.perception_fps_hint
                if tracking_observer is not None
                else None
            ),
        )
        if config.vision_enabled
        else None
    )

    memory_runtime = build_default_memory_runtime() if config.memory_enabled else None

    memory_query_coordinator = None
    if memory_runtime is not None and config.memory_semantic_recall_enabled:
        assert config.memory_semantic_recall_model is not None
        query_model = config.memory_semantic_recall_model
        interpreter = build_memory_query_interpreter(
            provider=config.ai_provider,
            model=query_model,
        )
        release_guard = build_memory_release_guard(
            provider=config.ai_provider,
            model=query_model,
        )
        memory_query_coordinator = ProviderVerifiedMemoryQueryCoordinator(
            coordinator=MemoryQueryCoordinator(
                interpreter=interpreter,
                retrieval=memory_runtime.retrieval,
            ),
            release_guard=release_guard,
        )
        LOGGER.warning(
            "Phase-4.5D bounded provider-assisted semantic recall configured: "
            "active_provider=%s model=%s structured_planner=True "
            "structured_release_verifier=True deterministic_core=True "
            "probabilistic_semantic_boundary=True",
            config.ai_provider,
            interpreter.model_name,
        )

    candidate_extractor = None
    if config.memory_candidate_extraction_enabled:
        assert config.memory_candidate_extraction_model is not None
        candidate_extractor = build_memory_candidate_extractor(
            provider=config.ai_provider,
            model=config.memory_candidate_extraction_model,
        )
        LOGGER.info(
            "Phase-4.4 memory candidate extraction shadow is configured: "
            "active_provider=%s model=%s quarantine=session_local "
            "durable_admission=False",
            config.ai_provider,
            candidate_extractor.model_name,
        )

    research_service = build_current_research_service()
    LOGGER.info(
        "Step-6 source-aware research is configured: active_brain=%s "
        "search_provider=%s brain_search_decoupled=True provider_neutral_contract=True",
        config.ai_provider,
        research_service.provider_name,
    )

    result_observer = (
        CapabilityExecutionHealthObserver(self_awareness)
        if self_awareness is not None
        else None
    )
    package_stack = None
    try:
        active_release = load_active_release_for_startup()
        if active_release is not None:
            package_stack = build_package_managed_runtime_stack(
                active_release,
            )
    except Exception as exc:
        LOGGER.exception(
            "Package-managed capability runtime is unavailable; acquired "
            "capabilities remain disabled: %s",
            type(exc).__name__,
        )
        package_stack = None

    self_awareness_executors = (
        (SelfAwarenessReadExecutor(self_awareness),)
        if self_awareness is not None
        else ()
    )
    package_executors = () if package_stack is None else package_stack.executors
    extra_executors = self_awareness_executors + package_executors
    capability_runtime = build_default_capability_runtime(
        ai_provider=config.ai_provider,
        hands_planner_model=config.hands_planner_model,
        chatgpt_plan_enabled=config.chatgpt_plan_enabled,
        chatgpt_plan_model=config.chatgpt_plan_model,
        result_observer=result_observer,
        extra_executors=extra_executors,
        catalog_projection=(
            None if package_stack is None else package_stack.projection
        ),
        close_callbacks=(() if package_stack is None else (package_stack.close,)),
    )
    capability_catalog = capability_runtime.refresh_catalog()
    if self_awareness is not None:
        record_capability_catalog_health(self_awareness, capability_catalog)
        record_hands_availability_health(self_awareness, capability_catalog)
    structured_hands = capability_catalog.by_key("windows:desktop.control")
    visual_hands = capability_catalog.by_key("visual:desktop.control")
    browser_hands = capability_catalog.by_key("browser:playwright")
    hands_planner = capability_runtime.hands_planner
    LOGGER.info(
        "Governed capability runtime configured: capabilities=%s "
        "structured_desktop_control=%s visual_fallback=%s browser_control=%s "
        "hands_planner=%s/%s chatgpt_plan=%s package_managed=%s raw_shell=False",
        len(capability_catalog.capabilities),
        bool(structured_hands and structured_hands.execution_enabled),
        bool(visual_hands and visual_hands.execution_enabled),
        bool(browser_hands and browser_hands.execution_enabled),
        getattr(hands_planner, "provider_name", "none"),
        getattr(hands_planner, "model_name", "none"),
        config.chatgpt_plan_enabled,
        len(package_executors),
    )

    work_runtime = None
    if config.work_orchestration_enabled:
        deployment_metadata = DeploymentMetadataStore(default_deployment_root())
        work_runtime = build_work_runtime(
            provider=config.ai_provider,
            research_service=research_service,
            model=config.work_orchestration_model,
            chatgpt_plan_enabled=config.chatgpt_plan_enabled,
            chatgpt_plan_model=config.chatgpt_plan_model,
            global_brain_router_mode=config.global_brain_router_mode,
            global_concurrency=config.work_global_concurrency,
            development_test_image=config.development_test_docker_image,
            dbos_database_url=config.work_dbos_database_url,
            event_loop=asyncio.get_running_loop(),
            capability_runtime=capability_runtime,
            acquisition_context_provider=(
                CapabilityRuntimeAcquisitionContextProvider(
                    capability_runtime,
                    projection=(
                        None if package_stack is None else package_stack.projection
                    ),
                )
            ),
            capability_lifecycle_service=(
                None if package_stack is None else package_stack.lifecycle
            ),
            capability_deployment_metadata=deployment_metadata,
            capability_package_admission=(
                None if package_stack is None else package_stack.admission
            ),
            capability_package_reconciler=(
                None if package_stack is None else package_stack.reconciler
            ),
            promotion_runtime_config=(
                None
                if not config.github_promotion_enabled
                else PromotionRuntimeConfig(
                    client_id=config.github_app_client_id or "",
                    installation_id=config.github_app_installation_id or 0,
                    repository_full_name=config.github_repository_full_name or "",
                    secret_id=config.github_app_secret_id or "",
                    base_branch=config.github_base_branch,
                    workflow_file=config.github_workflow_file,
                    expected_ci_app_id=config.github_expected_ci_app_id,
                )
            ),
            capability_catalog_refresher=capability_runtime.refresh_catalog,
        )
        LOGGER.info(
            "Persistent work runtime configured: provider=%s physical_concurrency=%s "
            "brain_router_mode=%s dev_sandbox=%s canonical_store=True durable_backend=DBOS "
            "capability_acquisition_live_catalog=True",
            config.ai_provider,
            config.work_global_concurrency,
            config.global_brain_router_mode,
            bool(config.development_test_docker_image),
        )

    provider_resilience_state = ProviderResilienceState()
    provider_health_observer = (
        ProviderResilienceHealthObserver(self_awareness)
        if self_awareness is not None
        else None
    )
    voice_behavior_observer = (
        VoiceBehaviorHealthObserver(self_awareness)
        if self_awareness is not None
        else None
    )
    local_status_speech = build_local_status_speech()
    LOGGER.info(
        "Step-5 minimal provider resilience is configured: provider=%s "
        "terminal_error_diagnosis=True local_status_speech=%s automatic_failover=False",
        config.ai_provider,
        local_status_speech is not None,
    )

    def media_output() -> MediaDevicesAudioOutput | None:
        output = audio.output
        return output if isinstance(output, MediaDevicesAudioOutput) else None

    def production_session_factory(session_config: JarvisConfig):
        session, bridge = create_voice_session(session_config)
        ProviderResilienceSessionObserver(
            session,
            provider=session_config.ai_provider,
            state=provider_resilience_state,
            status_speech=local_status_speech,
            output_getter=lambda: audio.output,
            health_observer=provider_health_observer,
            failure_observer=(
                (
                    lambda failure: provider_lifecycle_trigger.set()
                    if failure.kind is ProviderFailureKind.MODEL_UNAVAILABLE
                    else None
                )
                if provider_lifecycle_trigger is not None
                else None
            ),
        )
        silent_audio_recovery = SilentRealtimeAudioRecovery(
            session_config,
            output_getter=media_output,
        )
        bridge.add_accepted_turn_observer(silent_audio_recovery.observe_turn)
        bridge.add_close_observer(silent_audio_recovery.close)
        if candidate_extractor is not None:
            candidate_runtime = MemoryCandidateSessionRuntime(
                conversation=bridge.conversation,
                extractor=candidate_extractor,
            )
            bridge.add_accepted_turn_observer(candidate_runtime.observe_turn)
            bridge.add_close_observer(candidate_runtime.close)
        return session, bridge

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
        memory_runtime=memory_runtime,
        memory_query_coordinator=memory_query_coordinator,
        research_service=research_service,
        capability_runtime=capability_runtime,
        work_runtime=work_runtime,
        session_factory=production_session_factory,
        local_status_speech=local_status_speech,
        startup_readiness_waiter=(
            tracking_observer.wait_for_startup_lock
            if tracking_observer is not None
            else None
        ),
        startup_readiness_timeout_seconds=_POCKET3_STARTUP_LOCK_WAIT_SECONDS,
        voice_behavior_observer=voice_behavior_observer,
    )


async def _reconcile_provider_model_lifecycle(
    config: JarvisConfig,
):
    if config.ai_provider != "gemini":
        return None
    try:
        api_key = require_provider_api_key(
            "gemini",
            purpose="provider model lifecycle validation",
        )
    except RuntimeError as exc:
        LOGGER.warning(
            "Gemini model lifecycle validation skipped because credentials are "
            "unavailable: %s",
            exc,
        )
        return None
    return await reconcile_gemini_live_model(config, api_key=api_key)


async def _run_provider_model_lifecycle_watch(
    config: JarvisConfig,
    runtime,
    migrated: asyncio.Event,
    lifecycle_trigger: asyncio.Event,
    *,
    poll_seconds: float = _PROVIDER_MODEL_LIFECYCLE_POLL_SECONDS,
) -> None:
    while True:
        try:
            await asyncio.wait_for(lifecycle_trigger.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass
        lifecycle_trigger.clear()
        result = await _reconcile_provider_model_lifecycle(config)
        if result is None or not result.migrated:
            continue
        LOGGER.warning(
            "Provider model lifecycle migration detected while JARVIS is running | "
            "current=%s replacement=%s; recycling voice runtime in-process",
            result.current_model,
            result.replacement_model,
        )
        migrated.set()
        runtime.request_shutdown()
        return


async def _run_from_configuration() -> None:
    while True:
        config = JarvisConfig.from_environment()
        configure_logging(config.log_level)

        startup_lifecycle = await _reconcile_provider_model_lifecycle(config)
        if startup_lifecycle is not None and startup_lifecycle.migrated:
            LOGGER.warning(
                "Provider model lifecycle migration completed before startup | "
                "current=%s replacement=%s; reloading machine configuration",
                startup_lifecycle.current_model,
                startup_lifecycle.replacement_model,
            )
            config = JarvisConfig.from_environment()

        self_awareness: SelfAwarenessRuntime | None = None
        try:
            self_awareness = SelfAwarenessRuntime()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not block startup
            LOGGER.warning(
                "Self-awareness evidence is unavailable; continuing without it: %s",
                type(exc).__name__,
            )

        lifecycle_trigger = asyncio.Event()
        if self_awareness is None:
            require_startup_preflight(config)
            runtime = build_production_voice_runtime(
                config,
                provider_lifecycle_trigger=lifecycle_trigger,
            )
        else:
            record_foundation_health(self_awareness)
            require_startup_preflight_with_health(config, self_awareness)
            runtime = build_production_voice_runtime(
                config,
                self_awareness=self_awareness,
                provider_lifecycle_trigger=lifecycle_trigger,
            )

        migrated = asyncio.Event()
        lifecycle_task = (
            asyncio.create_task(
                _run_provider_model_lifecycle_watch(
                    config,
                    runtime,
                    migrated,
                    lifecycle_trigger,
                ),
                name="jarvis-provider-model-lifecycle-watch",
            )
            if config.ai_provider == "gemini"
            else None
        )
        try:
            await runtime.run()
        finally:
            if lifecycle_task is not None and not lifecycle_task.done():
                lifecycle_task.cancel()
                await asyncio.gather(lifecycle_task, return_exceptions=True)
            if self_awareness is not None:
                self_awareness.close()

        if migrated.is_set():
            LOGGER.warning(
                "Reloading JARVIS after automatic provider model lifecycle migration"
            )
            continue
        return


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
