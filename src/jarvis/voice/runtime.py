"""Roomless Step-2 wake-to-conversation runtime."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from livekit.agents import (
    AgentSession,
    AgentStateChangedEvent,
    CloseEvent,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.io import PlaybackFinishedEvent

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession
from jarvis.dev_control import DevControlClient, parse_explicit_update_decision
from jarvis.identity.active_speaker import (
    ActiveSpeakerVisualBuffer,
    LrAsdActiveSpeakerProvider,
)
from jarvis.identity.owner_context import (
    OwnerContextState,
    build_default_owner_context_observer,
)
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture, SpeakerTurnAudio
from jarvis.identity.speech_region import (
    LiveKitSileroSpeechRegionDetector,
    SpeechRegionDetector,
)
from jarvis.logging_config import configure_logging
from jarvis.sensors.gstreamer_av import (
    GStreamerPairedAVConfig,
    GStreamerPairedAVSource,
)
from jarvis.sensors.windows_discovery import discover_windows_av_sources
from jarvis.vision.service import VisionService, build_default_vision_service
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.audio import LocalAudioRuntime, SessionAudioInput
from jarvis.voice.livekit_session import (
    LiveKitConversationBridge,
    create_voice_session,
)
from jarvis.voice.local_status_speech import LocalStatusSpeech
from jarvis.voice.observed_audio import ObservedSessionAudioInput
from jarvis.voice.paired_audio import PairedAudioRuntime
from jarvis.voice.scripted_speech import ScriptedSpeech
from jarvis.voice.standby_tools import StandbyAgentTools
from jarvis.voice.startup_greeting import select_startup_greeting
from jarvis.voice.vision_tools import VisionAgentTools
from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor

LOGGER = logging.getLogger(__name__)

SessionFactory = Callable[
    [JarvisConfig], tuple[AgentSession, LiveKitConversationBridge]
]
StartupGreetingFactory = Callable[[], str]
StartupReadinessWaiter = Callable[[float], bool]
VoiceBehaviorObserver = Callable[[str, str, str, dict[str, object]], None]
ConversationSuccessObserver = Callable[[], None]

_UPDATE_APPROVAL_PROMPT = (
    "A JARVIS software update is available. Shall I install it and restart now? "
    "Please answer yes or no."
)
_REALTIME_LIFECYCLE_TIMEOUT_SECONDS = 12.0
_STANDBY_ACK_TIMEOUT_SECONDS = 8.0
_WAKE_ACK_GRACE_SECONDS = 0.85
_WAKE_ZERO_TURN_DEGRADED_THRESHOLD = 3
_WAKE_ACK_INSTRUCTIONS = (
    "The owner invoked you and then paused without giving a request. "
    "Respond with exactly one very short, natural acknowledgement consistent with "
    "your established JARVIS personality and the current conversational context. "
    "Choose the wording naturally; do not use or imitate a fixed phrase list. "
    "Use one short sentence only. Do not mention prompts, models, tools, wake-word "
    "mechanics, or internal implementation."
)


class VoiceRuntimeState(str, Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    ACTIVATING = "activating"
    ACTIVE = "active"
    RECOVERING = "recovering"


@dataclass(slots=True)
class _UpdateApprovalRequest:
    local_sha: str
    remote_sha: str
    response: asyncio.Future[bool]


class VoiceRuntimeController:
    """Own wake, activation, active-session, recovery, and shutdown truth."""

    def __init__(
        self,
        config: JarvisConfig,
        audio: LocalAudioRuntime | PairedAudioRuntime,
        *,
        session_factory: SessionFactory = create_voice_session,
        vision_service: VisionService | None = None,
        owner_context_state: OwnerContextState | None = None,
        active_speaker_visual_buffer: ActiveSpeakerVisualBuffer | None = None,
        active_speaker_provider: LrAsdActiveSpeakerProvider | None = None,
        active_speaker_audio_capture: InMemorySpeakerTurnCapture | None = None,
        active_speaker_av_source: GStreamerPairedAVSource | None = None,
        speech_region_detector: SpeechRegionDetector | None = None,
        scripted_speech: ScriptedSpeech | None = None,
        local_status_speech: LocalStatusSpeech | None = None,
        startup_greeting_factory: StartupGreetingFactory = select_startup_greeting,
        startup_readiness_waiter: StartupReadinessWaiter | None = None,
        startup_readiness_timeout_seconds: float = 30.0,
        voice_behavior_observer: VoiceBehaviorObserver | None = None,
        conversation_success_observer: ConversationSuccessObserver | None = None,
    ) -> None:
        self.config = config
        self.audio = audio
        self._session_factory = session_factory
        self._vision_service = vision_service
        self._owner_context_state = owner_context_state
        self._active_speaker_visual_buffer = active_speaker_visual_buffer
        self._active_speaker_provider = active_speaker_provider
        self._active_speaker_audio_capture = active_speaker_audio_capture
        self._active_speaker_av_source = active_speaker_av_source
        self._speech_region_detector = speech_region_detector
        self._vision_tools = (
            VisionAgentTools(vision_service) if vision_service is not None else None
        )
        self._state = VoiceRuntimeState.STOPPED
        self._shutdown = asyncio.Event()
        self._active_end: asyncio.Event | None = None
        self._timeout_handle: asyncio.TimerHandle | None = None
        self._dev_control = DevControlClient.from_environment()
        self._update_approval_requests: asyncio.Queue[_UpdateApprovalRequest] = (
            asyncio.Queue()
        )
        # One owner may drive the physical JARVIS speaker at a time. Realtime
        # sessions hold this lease for their full lifetime; background lifecycle
        # speech acquires the same lease only while no session is active.
        self._speech_ownership = asyncio.Lock()
        self._scripted_speech = scripted_speech
        self._owns_scripted_speech = False
        self._local_status_speech = local_status_speech
        self._startup_greeting_factory = startup_greeting_factory
        if startup_readiness_timeout_seconds <= 0:
            raise ValueError("startup_readiness_timeout_seconds must be positive")
        self._startup_readiness_waiter = startup_readiness_waiter
        self._startup_readiness_timeout_seconds = startup_readiness_timeout_seconds
        self._voice_behavior_observer = voice_behavior_observer
        self._conversation_success_observer = conversation_success_observer
        self._consecutive_wake_sessions_without_user_turn = 0
        self._voice_behavior_degraded = False

    def _publish_voice_behavior(
        self,
        state: str,
        reason_code: str,
        summary: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        observer = self._voice_behavior_observer
        if observer is None:
            return
        try:
            observer(state, reason_code, summary, metadata or {})
        except Exception:
            LOGGER.debug("Voice behavior health observer failed", exc_info=True)

    def _note_successful_conversation(self) -> None:
        observer = self._conversation_success_observer
        if observer is None:
            return
        try:
            observer()
        except Exception:
            LOGGER.debug("Conversation success observer failed", exc_info=True)

    def _note_committed_user_turn(self) -> None:
        had_zero_turn_streak = self._consecutive_wake_sessions_without_user_turn > 0
        self._consecutive_wake_sessions_without_user_turn = 0
        if self._voice_behavior_degraded:
            self._voice_behavior_degraded = False
            self._publish_voice_behavior(
                "healthy",
                "voice_user_turn_recovered",
                "Realtime voice is committing owner turns again",
            )
        elif had_zero_turn_streak:
            LOGGER.info("Wake-to-user-turn voice behavior recovered before degradation")

    def _note_wake_session_without_user_turn(self) -> None:
        self._consecutive_wake_sessions_without_user_turn += 1
        streak = self._consecutive_wake_sessions_without_user_turn
        LOGGER.warning(
            "Wake-triggered realtime session ended without a committed user turn | "
            "consecutive=%s threshold=%s",
            streak,
            _WAKE_ZERO_TURN_DEGRADED_THRESHOLD,
        )
        if (
            streak >= _WAKE_ZERO_TURN_DEGRADED_THRESHOLD
            and not self._voice_behavior_degraded
        ):
            self._voice_behavior_degraded = True
            self._publish_voice_behavior(
                "degraded",
                "voice_repeated_wake_without_user_turn",
                "Repeated wake-triggered realtime sessions committed no owner turn",
                metadata={
                    "consecutive_zero_turn_sessions": streak,
                    "threshold": _WAKE_ZERO_TURN_DEGRADED_THRESHOLD,
                    "provider": self.config.ai_provider,
                    "realtime_model": (
                        self.config.gemini_realtime_model
                        if self.config.ai_provider == "gemini"
                        else self.config.realtime_model
                    ),
                },
            )

    @property
    def state(self) -> VoiceRuntimeState:
        return self._state

    @property
    def vision_service(self) -> VisionService | None:
        return self._vision_service

    def request_shutdown(self) -> None:
        self._shutdown.set()
        if self._active_end is not None:
            self._active_end.set()

    async def _queue_update_approval(self, local_sha: str, remote_sha: str) -> bool:
        response = asyncio.get_running_loop().create_future()
        await self._update_approval_requests.put(
            _UpdateApprovalRequest(
                local_sha=local_sha,
                remote_sha=remote_sha,
                response=response,
            )
        )
        return await response

    async def _wait_for_realtime_speech(
        self,
        handle,
        *,
        label: str,
        timeout_seconds: float = _REALTIME_LIFECYCLE_TIMEOUT_SECONDS,
    ) -> None:
        """Wait for one realtime-model utterance and surface provider failure."""

        await asyncio.wait_for(
            handle.wait_for_playout(),
            timeout=timeout_seconds,
        )
        error = handle.exception()
        if error is not None:
            raise error
        LOGGER.info(
            "JARVIS %s finished playing via realtime conversation voice",
            label,
        )

    async def _speak_ephemeral_realtime_message(
        self,
        output,
        *,
        instructions: str,
        label: str,
    ) -> None:
        """Speak one system message through the normal realtime model/voice lane."""

        session, bridge = self._session_factory(self.config)
        session.output.audio = output
        try:
            session.input.set_audio_enabled(False)
        except Exception:
            LOGGER.debug(
                "Ephemeral realtime lifecycle session has no mutable input gate",
                exc_info=True,
            )
        bridge.conversation.start()
        try:
            await session.start(
                agent=JarvisVoiceAgent(
                    tools=[],
                    default_media_target=self.config.default_media_target,
                )
            )
            handle = session.generate_reply(
                instructions=instructions,
                allow_interruptions=(self.config.ai_provider == "gemini"),
                input_modality="text",
            )
            await self._wait_for_realtime_speech(
                handle,
                label=label,
                timeout_seconds=_REALTIME_LIFECYCLE_TIMEOUT_SECONDS,
            )
        finally:
            await session.aclose()

    async def _wait_for_startup_readiness(self) -> bool:
        if self._startup_readiness_waiter is None:
            return True
        timeout = self._startup_readiness_timeout_seconds
        LOGGER.info(
            "JARVIS startup waiting up to %.1fs for trusted camera tracking lock",
            timeout,
        )
        ready = await asyncio.to_thread(self._startup_readiness_waiter, timeout)
        if ready:
            LOGGER.info("JARVIS startup camera tracking lock is ready")
            return True
        LOGGER.warning(
            "JARVIS startup camera tracking lock was not confirmed within %.1fs; "
            "entering wake mode silently",
            timeout,
        )
        return False

    async def _speak_startup_greeting(self) -> None:
        if not self.config.startup_greeting_enabled:
            return
        output = self.audio.output
        if output is None:
            LOGGER.warning(
                "JARVIS startup greeting skipped because audio output is unavailable"
            )
            return
        greeting = self._startup_greeting_factory().strip()
        if not greeting:
            LOGGER.warning(
                "JARVIS startup greeting skipped because no greeting was selected"
            )
            return
        instructions = (
            "JARVIS has just completed startup successfully. Give the owner exactly one "
            "brief, natural greeting in your established JARVIS voice and style. Vary "
            "the wording naturally from previous greetings and do not mention prompts, "
            "models, tools, or internal implementation. Use this machine-selected "
            f"time-of-day cue only as context, not as a script to repeat verbatim: {greeting}"
        )
        try:
            await self._speak_ephemeral_realtime_message(
                output,
                instructions=instructions,
                label="startup greeting",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "JARVIS startup realtime greeting failed; entering wake mode silently"
            )

    def _on_audio_overflow(self) -> None:
        LOGGER.error("Voice session stopped because its microphone queue overflowed")
        if self._active_end is not None:
            self._active_end.set()

    def _cancel_timeout(self) -> None:
        if self._timeout_handle is not None:
            self._timeout_handle.cancel()
            self._timeout_handle = None

    def _arm_timeout(self, seconds: float) -> None:
        self._cancel_timeout()
        active_end = self._active_end
        if active_end is None:
            return
        self._timeout_handle = asyncio.get_running_loop().call_later(
            seconds,
            active_end.set,
        )

    async def _inspect_active_speaker_turn(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
        quality_accepted: bool,
    ) -> None:
        provider = self._active_speaker_provider
        visual_buffer = self._active_speaker_visual_buffer
        if provider is None or visual_buffer is None:
            return
        if not quality_accepted:
            LOGGER.info(
                "Active speaker shadow turn %s | state=insufficient | "
                "active_speaker_confirmed=False | prototype_admission=False | "
                "reasons=speaker_quality_rejected",
                audio_turn_id,
            )
            return
        if turn.start_monotonic is None or turn.end_monotonic is None:
            LOGGER.info(
                "Active speaker shadow turn %s | state=insufficient | "
                "active_speaker_confirmed=False | prototype_admission=False | "
                "reasons=audio_timestamps_missing",
                audio_turn_id,
            )
            return

        context = self._owner_context_state
        snapshot = context.snapshot() if context is not None else None
        assessment = snapshot.assessment if snapshot is not None else None
        owner_context_live = bool(
            context is not None
            and assessment is not None
            and context.has_fresh_live_owner_candidate()
        )
        if not owner_context_live or assessment is None:
            LOGGER.info(
                "Active speaker shadow turn %s | state=insufficient | "
                "active_speaker_confirmed=False | prototype_admission=False | "
                "reasons=no_fresh_live_owner_context",
                audio_turn_id,
            )
            return

        visual = visual_buffer.build_window(
            visual_track_id=assessment.visual_track_id,
            start_monotonic=turn.start_monotonic,
            end_monotonic=turn.end_monotonic,
        )
        if visual is None:
            LOGGER.info(
                "Active speaker shadow turn %s | state=insufficient | track=%s | "
                "active_speaker_confirmed=False | prototype_admission=False | "
                "reasons=visual_window_insufficient",
                audio_turn_id,
                assessment.visual_track_id,
            )
            return

        result = await asyncio.to_thread(
            provider.assess,
            turn,
            visual,
            audio_turn_id=audio_turn_id,
            windows_session_id=assessment.session_id,
        )
        LOGGER.info(
            "Active speaker shadow turn %s | state=%s | session=%s | track=%s | "
            "window=%.2fs | visual=%s/%s@%.2ffps | audio_features=%s | "
            "score mean=%s median=%s min=%s max=%s | "
            "active_speaker_confirmed=False | prototype_admission=False | reasons=%s",
            audio_turn_id,
            result.state.value,
            result.windows_session_id,
            result.visual_track_id,
            result.end_monotonic - result.start_monotonic,
            result.unique_visual_frames,
            result.visual_frames,
            visual.source_fps,
            result.audio_feature_frames,
            f"{result.mean_score:.4f}" if result.mean_score is not None else "n/a",
            f"{result.median_score:.4f}" if result.median_score is not None else "n/a",
            f"{result.minimum_score:.4f}"
            if result.minimum_score is not None
            else "n/a",
            f"{result.maximum_score:.4f}"
            if result.maximum_score is not None
            else "n/a",
            ",".join(result.reason_codes) if result.reason_codes else "none",
        )

    async def _inspect_paired_active_speaker_turn(
        self,
        turn: SpeakerTurnAudio | None,
        *,
        audio_turn_id: str,
    ) -> None:
        if self._active_speaker_provider is None:
            return
        if turn is None:
            LOGGER.info(
                "Active speaker shadow turn %s | state=insufficient | "
                "active_speaker_confirmed=False | prototype_admission=False | "
                "reasons=paired_audio_window_missing",
                audio_turn_id,
            )
            return

        analysis_turn = turn
        speech_detector = self._speech_region_detector
        if speech_detector is not None:
            region = await speech_detector.extract(turn)
            if region.turn is None:
                LOGGER.info(
                    "Active speaker shadow turn %s | state=insufficient | "
                    "paired_captured=%.2fs | active_speaker_confirmed=False | "
                    "prototype_admission=False | reasons=%s",
                    audio_turn_id,
                    turn.duration_seconds,
                    region.reason,
                )
                return
            analysis_turn = region.turn

        quality = await asyncio.to_thread(
            assess_speaker_segment,
            analysis_turn.samples,
            sample_rate=analysis_turn.sample_rate,
        )
        LOGGER.info(
            "Active speaker paired-audio turn %s | captured=%.2fs | speech=%.2fs | "
            "rms %.1f dBFS | accepted=%s | source=paired_gstreamer_av | reasons=%s",
            audio_turn_id,
            turn.duration_seconds,
            analysis_turn.duration_seconds,
            quality.rms_dbfs,
            quality.accepted,
            ",".join(quality.reason_codes) if quality.reason_codes else "none",
        )
        await self._inspect_active_speaker_turn(
            analysis_turn,
            audio_turn_id=audio_turn_id,
            quality_accepted=quality.accepted,
        )

    async def _inspect_shadow_turn(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
        active_speaker_turn: SpeakerTurnAudio | None = None,
    ) -> None:
        analysis_turn = turn
        speech_segments = 0
        speaker_region_available = True
        if self._speech_region_detector is not None:
            region = await self._speech_region_detector.extract(turn)
            speech_segments = region.segment_count
            if region.turn is None:
                speaker_region_available = False
                owner_context_live = bool(
                    self._owner_context_state is not None
                    and self._owner_context_state.has_fresh_live_owner_candidate()
                )
                LOGGER.info(
                    "Speaker shadow turn %s | captured=%.2fs | speech=none | "
                    "accepted=False | live_owner_context=%s | "
                    "active_speaker_confirmed=False | prototype_admission=False | "
                    "reasons=%s",
                    audio_turn_id,
                    turn.duration_seconds,
                    owner_context_live,
                    region.reason,
                )
            else:
                analysis_turn = region.turn

        if speaker_region_available:
            quality = await asyncio.to_thread(
                assess_speaker_segment,
                analysis_turn.samples,
                sample_rate=analysis_turn.sample_rate,
            )
            owner_context_live = bool(
                self._owner_context_state is not None
                and self._owner_context_state.has_fresh_live_owner_candidate()
            )
            LOGGER.info(
                "Speaker shadow turn %s | captured=%.2fs | speech=%.2fs | segments=%s | "
                "rms %.1f dBFS | accepted=%s | live_owner_context=%s | "
                "active_speaker_confirmed=False | prototype_admission=False | reasons=%s",
                audio_turn_id,
                turn.duration_seconds,
                analysis_turn.duration_seconds,
                speech_segments,
                quality.rms_dbfs,
                quality.accepted,
                owner_context_live,
                ",".join(quality.reason_codes) if quality.reason_codes else "none",
            )

        await self._inspect_paired_active_speaker_turn(
            active_speaker_turn,
            audio_turn_id=audio_turn_id,
        )

    async def run(self) -> None:
        self.audio.set_overflow_handler(self._on_audio_overflow)
        vision_started = False
        control_task: asyncio.Task[None] | None = None
        try:
            if self._dev_control is not None:
                control_task = asyncio.create_task(
                    self._dev_control.run(
                        approval_handler=self._queue_update_approval,
                        shutdown_handler=self.request_shutdown,
                    ),
                    name="jarvis-dev-control",
                )
                LOGGER.info(
                    "JARVIS development voice-control channel is connecting during startup"
                )

            if self._vision_service is not None:
                await asyncio.to_thread(self._vision_service.start)
                vision_started = True
                LOGGER.info("JARVIS integrated vision is active in SAFE mode")
                paired_source = self._active_speaker_av_source
                if paired_source is not None:
                    if paired_source.pipeline_clock_name != "GstAudioSrcClock":
                        raise RuntimeError(
                            "active-speaker paired AV source did not select GstAudioSrcClock"
                        )
                    LOGGER.info(
                        "Paired active-speaker AV source is active: %s (%s) on %s",
                        paired_source.source.display_name,
                        paired_source.source.source_id,
                        paired_source.pipeline_clock_name,
                    )

            await self.audio.start()
            if isinstance(self.audio, PairedAudioRuntime):
                LOGGER.info(
                    "Canonical microphone source is GStreamer WebRTC-AEC-cleaned DJI PCM; "
                    "no PortAudio or Voicemeeter input device is open"
                )
                LOGGER.info(
                    "Full-duplex GStreamer AEC is active: JARVIS playback feeds "
                    "webrtcechoprobe before physical render resampling, while raw paired "
                    "DJI PCM remains available only for synchronized LR-ASD evidence"
                )
            if self._dev_control is not None:
                self._dev_control.mark_ready()
                LOGGER.info(
                    "JARVIS development supervisor readiness published after "
                    "vision/audio initialization"
                )

            startup_ready = await self._wait_for_startup_readiness()
            if startup_ready:
                await self._speak_startup_greeting()
            else:
                LOGGER.info(
                    "JARVIS startup greeting skipped until a trusted camera lock exists"
                )
            self._state = VoiceRuntimeState.IDLE
            LOGGER.info("JARVIS is idle; local wake detection is active")
            while not self._shutdown.is_set():
                detection_task = asyncio.create_task(
                    self.audio.detector.wait_for_detection()
                )
                shutdown_task = asyncio.create_task(self._shutdown.wait())
                waiters: set[asyncio.Task[object]] = {
                    detection_task,
                    shutdown_task,
                }
                approval_task: asyncio.Task[_UpdateApprovalRequest] | None = None
                if control_task is not None and not control_task.done():
                    approval_task = asyncio.create_task(
                        self._update_approval_requests.get()
                    )
                    waiters.add(approval_task)

                done, pending = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                if shutdown_task in done:
                    break

                if approval_task is not None and approval_task in done:
                    request = approval_task.result()
                    approved = False
                    self._state = VoiceRuntimeState.ACTIVATING
                    try:
                        approved = await self._run_update_approval_session(
                            request.local_sha,
                            request.remote_sha,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        LOGGER.exception(
                            "Spoken update approval failed; treating the decision as No"
                        )
                    finally:
                        if not request.response.done():
                            request.response.set_result(approved)
                        self._cancel_timeout()
                        self._active_end = None
                        if not self._shutdown.is_set():
                            await self.audio.resume_wake(
                                cooldown_seconds=self.config.wake_cooldown_seconds
                            )
                            self._state = VoiceRuntimeState.IDLE
                            LOGGER.info("JARVIS returned to local wake detection")
                    continue

                detection = detection_task.result()
                LOGGER.info(
                    "Wake detected: %s (confidence %.3f)",
                    detection.name,
                    detection.confidence,
                )
                # Claim the lifecycle before awaiting the speech lease so a
                # queued background notification cannot race a just-detected wake.
                self._state = VoiceRuntimeState.ACTIVATING
                try:
                    await self._run_one_session(
                        pre_roll_after_monotonic=detection.audio_end_at
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._state = VoiceRuntimeState.RECOVERING
                    LOGGER.exception("Voice activation failed; returning to local idle")
                finally:
                    self._cancel_timeout()
                    self._active_end = None
                    if not self._shutdown.is_set():
                        await self.audio.resume_wake(
                            cooldown_seconds=self.config.wake_cooldown_seconds
                        )
                        self._state = VoiceRuntimeState.IDLE
                        LOGGER.info("JARVIS returned to local wake detection")
        finally:
            self._cancel_timeout()
            self._state = VoiceRuntimeState.STOPPED
            if control_task is not None:
                control_task.cancel()
                await asyncio.gather(control_task, return_exceptions=True)
            if self._owns_scripted_speech and self._scripted_speech is not None:
                try:
                    await self._scripted_speech.aclose()
                except Exception:
                    LOGGER.exception("JARVIS scripted speech did not shut down cleanly")
            await self.audio.aclose()
            if vision_started and self._vision_service is not None:
                try:
                    await asyncio.to_thread(self._vision_service.stop)
                except Exception:
                    LOGGER.exception(
                        "JARVIS integrated vision did not shut down cleanly"
                    )
            if self._active_speaker_visual_buffer is not None:
                self._active_speaker_visual_buffer.clear()
            if self._active_speaker_audio_capture is not None:
                self._active_speaker_audio_capture.clear()

    async def _run_update_approval_session(
        self,
        local_sha: str,
        remote_sha: str,
    ) -> bool:
        async with self._speech_ownership:
            return await self._run_update_approval_session_owned(
                local_sha,
                remote_sha,
            )

    async def _run_update_approval_session_owned(
        self,
        local_sha: str,
        remote_sha: str,
    ) -> bool:
        output = self.audio.output
        if output is None:
            raise RuntimeError("local audio output is not available")

        self._state = VoiceRuntimeState.ACTIVATING
        active_end = asyncio.Event()
        self._active_end = active_end
        decision = asyncio.get_running_loop().create_future()
        accepting_decision = False
        session, bridge = self._session_factory(self.config)
        session_input = SessionAudioInput()
        session.input.audio = session_input

        def on_transcript(event: UserInputTranscribedEvent) -> None:
            if (
                not accepting_decision
                or not event.is_final
                or not event.transcript.strip()
                or decision.done()
            ):
                return
            parsed = parse_explicit_update_decision(event.transcript)
            if parsed is None:
                LOGGER.info(
                    "Spoken update response was not an explicit Yes/No; treating as No"
                )
                parsed = False
            decision.set_result(parsed)
            active_end.set()

        session.on("user_input_transcribed", on_transcript)
        bridge.conversation.start()
        self.audio.activate_session(session_input)
        try:
            try:
                await session.start(
                    agent=JarvisVoiceAgent(
                        tools=[],
                        default_media_target=self.config.default_media_target,
                    )
                )
            except Exception:
                bridge.conversation.fail()
                raise
            self._state = VoiceRuntimeState.ACTIVE
            session.output.audio = output
            LOGGER.info("JARVIS is requesting spoken approval for a software update")
            prompt_handle = session.generate_reply(
                instructions=(
                    "Say exactly the following update-approval prompt and nothing else: "
                    + _UPDATE_APPROVAL_PROMPT
                ),
                allow_interruptions=False,
                input_modality="text",
            )
            await self._wait_for_realtime_speech(
                prompt_handle,
                label="update approval prompt",
            )
            accepting_decision = True
            LOGGER.info(
                "Spoken update approval prompt finished playing; awaiting owner Yes/No "
                "for %s -> %s",
                local_sha[:10],
                remote_sha[:10],
            )
            try:
                approved = await asyncio.wait_for(decision, timeout=20.0)
            except TimeoutError:
                LOGGER.info("Spoken update approval timed out; treating as No")
                approved = False
            return bool(approved)
        finally:
            active_end.set()
            self.audio.deactivate_session()
            await session.aclose()

    async def _run_one_session(
        self,
        *,
        pre_roll_after_monotonic: float | None = None,
        initial_instructions: str | None = None,
        initial_prompt_label: str = "proactive prompt",
        session_tool_factory: Callable[[ConversationSession], list] | None = None,
        completion_predicate: Callable[[], bool] | None = None,
        completion_label: str = "proactive interaction",
    ) -> None:
        async with self._speech_ownership:
            await self._run_one_session_owned(
                pre_roll_after_monotonic=pre_roll_after_monotonic,
                initial_instructions=initial_instructions,
                initial_prompt_label=initial_prompt_label,
                session_tool_factory=session_tool_factory,
                completion_predicate=completion_predicate,
                completion_label=completion_label,
            )

    async def _run_one_session_owned(
        self,
        *,
        pre_roll_after_monotonic: float | None = None,
        initial_instructions: str | None = None,
        initial_prompt_label: str = "proactive prompt",
        session_tool_factory: Callable[[ConversationSession], list] | None = None,
        completion_predicate: Callable[[], bool] | None = None,
        completion_label: str = "proactive interaction",
    ) -> None:
        output = self.audio.output
        if output is None:
            raise RuntimeError("local audio output is not available")

        self._state = VoiceRuntimeState.ACTIVATING
        active_end = asyncio.Event()
        self._active_end = active_end
        session, bridge = self._session_factory(self.config)
        turn_capture = (
            InMemorySpeakerTurnCapture(
                max_turn_seconds=self.config.max_utterance_seconds
            )
            if self.config.speaker_shadow_enabled
            else None
        )
        paired_turn_capture = self._active_speaker_audio_capture
        if paired_turn_capture is not None:
            paired_turn_capture.clear()
        shadow_tasks: set[asyncio.Task[None]] = set()
        exit_in_progress = False

        def on_audio_frame(
            frame,
            observed_at_monotonic: float,
        ) -> None:
            if turn_capture is None:
                return

            turn_capture.push_frame(
                frame.data,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel,
                observed_at_monotonic=observed_at_monotonic,
            )

        session_input = (
            ObservedSessionAudioInput(on_audio_frame)
            if turn_capture is not None
            else SessionAudioInput()
        )
        session.input.audio = session_input
        session.output.audio = output
        has_user_turn = False

        def submit_shadow_turn() -> None:
            if turn_capture is None:
                return
            turn = turn_capture.snapshot_recent_audio()
            if turn is None:
                return
            active_speaker_turn = (
                paired_turn_capture.snapshot_recent_audio()
                if paired_turn_capture is not None
                else None
            )
            audio_turn_id = str(uuid.uuid4())
            if paired_turn_capture is None:
                task = asyncio.create_task(
                    self._inspect_shadow_turn(turn, audio_turn_id=audio_turn_id),
                    name=f"jarvis-speaker-shadow-{audio_turn_id[:8]}",
                )
            else:
                task = asyncio.create_task(
                    self._inspect_shadow_turn(
                        turn,
                        audio_turn_id=audio_turn_id,
                        active_speaker_turn=active_speaker_turn,
                    ),
                    name=f"jarvis-speaker-shadow-{audio_turn_id[:8]}",
                )
            shadow_tasks.add(task)
            task.add_done_callback(shadow_tasks.discard)

        standby_ack_observed = False
        standby_playback_finished = False
        owner_activity = asyncio.Event()
        wake_ack_task: asyncio.Task[None] | None = None
        wake_ack_started = False
        session_success_observed = False

        async def maybe_acknowledge_wake() -> None:
            nonlocal wake_ack_started
            try:
                await asyncio.sleep(_WAKE_ACK_GRACE_SECONDS)
                if (
                    owner_activity.is_set()
                    or exit_in_progress
                    or active_end.is_set()
                    or self._shutdown.is_set()
                ):
                    return
                wake_ack_started = True
                LOGGER.info(
                    "Wake acknowledgement grace expired with no owner speech; "
                    "requesting one brief realtime acknowledgement"
                )
                handle = session.generate_reply(
                    instructions=_WAKE_ACK_INSTRUCTIONS,
                    allow_interruptions=True,
                    input_modality="text",
                )
                await handle.wait_for_playout()
                error = handle.exception()
                if error is not None:
                    raise error
                LOGGER.info("JARVIS wake acknowledgement finished playing")
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "JARVIS wake acknowledgement failed; continuing conversation silently"
                )
            finally:
                wake_ack_started = False

        def note_owner_activity() -> None:
            nonlocal wake_ack_task
            owner_activity.set()
            task = wake_ack_task
            if task is None or task.done():
                return
            if not wake_ack_started:
                task.cancel()
                wake_ack_task = None
                return
            # Gemini Live server-side activity detection already owns barge-in.
            # Calling AgentSession.interrupt() here races the provider's new user
            # turn and can cancel the response generated for the real utterance.
            LOGGER.info(
                "Owner speech arrived during wake acknowledgement; "
                "provider-native barge-in owns interruption"
            )

        def request_standby() -> bool:
            nonlocal exit_in_progress
            if exit_in_progress:
                return False
            exit_in_progress = True
            self._cancel_timeout()
            LOGGER.info(
                "Semantic voice-session standby accepted; realtime JARVIS will "
                "acknowledge before returning to wake mode"
            )
            try:
                session.input.set_audio_enabled(False)
            except Exception:
                LOGGER.exception(
                    "Voice input could not be disabled during standby transition"
                )
            # Stop routing physical microphone PCM immediately. Disabling the
            # LiveKit session input alone can still leave a small buffered/in-flight
            # window where a follow-up utterance reaches the realtime model.
            self.audio.deactivate_session()
            # Keep the existing realtime output attached. The tool result asks the
            # same Gemini Live session to generate one natural acknowledgement in
            # the established JARVIS voice. If no acknowledgement arrives, fail
            # closed to silent standby after a short timeout.
            self._arm_timeout(_STANDBY_ACK_TIMEOUT_SECONDS)
            return True

        def on_user_state(event: UserStateChangedEvent) -> None:
            if exit_in_progress:
                return
            if event.new_state == "speaking":
                note_owner_activity()
                self._arm_timeout(self.config.max_utterance_seconds)
            elif event.new_state == "listening":
                timeout = (
                    self.config.follow_up_timeout_seconds
                    if has_user_turn
                    else self.config.initial_request_timeout_seconds
                )
                self._arm_timeout(timeout)

        def on_agent_state(event: AgentStateChangedEvent) -> None:
            if (
                not exit_in_progress
                and has_user_turn
                and event.new_state in {"thinking", "speaking"}
            ):
                self._cancel_timeout()
            if (
                not exit_in_progress
                and has_user_turn
                and event.new_state == "listening"
                and completion_predicate is not None
            ):
                try:
                    completed = completion_predicate()
                except Exception:
                    LOGGER.exception(
                        "JARVIS %s completion predicate failed",
                        completion_label,
                    )
                else:
                    if completed:
                        LOGGER.info(
                            "JARVIS %s completed; closing interactive voice session",
                            completion_label,
                        )
                        active_end.set()

        def on_conversation_item(event: ConversationItemAddedEvent) -> None:
            nonlocal has_user_turn, session_success_observed, standby_ack_observed
            item = event.item
            if not isinstance(item, ChatMessage):
                return
            text = item.text_content.strip()
            if not text:
                return
            if item.role == "assistant" and exit_in_progress:
                standby_ack_observed = True
                if standby_playback_finished:
                    LOGGER.info(
                        "JARVIS realtime standby acknowledgement finished playing"
                    )
                    active_end.set()
                return
            if item.role == "assistant":
                return
            if item.role != "user":
                return
            if exit_in_progress:
                LOGGER.info("Late user turn ignored during standby transition")
                return
            note_owner_activity()
            has_user_turn = True
            self._note_committed_user_turn()
            self._cancel_timeout()
            submit_shadow_turn()

        def on_playback_finished(event: PlaybackFinishedEvent) -> None:
            nonlocal standby_playback_finished, session_success_observed
            if exit_in_progress:
                standby_playback_finished = True
                if standby_ack_observed:
                    LOGGER.info(
                        "JARVIS realtime standby acknowledgement finished playing"
                    )
                    active_end.set()
                return
            if (
                has_user_turn
                and not session_success_observed
                and not event.interrupted
                and (wake_ack_task is None or wake_ack_task.done())
            ):
                session_success_observed = True
                self._note_successful_conversation()
            if self._state is VoiceRuntimeState.ACTIVE:
                self._arm_timeout(self.config.follow_up_timeout_seconds)

        def on_close(event: CloseEvent) -> None:
            del event
            active_end.set()

        session.on("user_state_changed", on_user_state)
        session.on("agent_state_changed", on_agent_state)
        session.on("conversation_item_added", on_conversation_item)
        session.on("close", on_close)
        output.on("playback_finished", on_playback_finished)

        bridge.conversation.start()
        if pre_roll_after_monotonic is None:
            self.audio.activate_session(session_input)
        else:
            self.audio.activate_session(
                session_input,
                pre_roll_after_monotonic=pre_roll_after_monotonic,
            )
            LOGGER.info(
                "Wake handoff trimmed realtime pre-roll through %.6f; "
                "post-wake speech is preserved",
                pre_roll_after_monotonic,
            )
        self._arm_timeout(self.config.initial_request_timeout_seconds)
        if session_tool_factory is not None:
            tools = list(session_tool_factory(bridge.conversation))
        else:
            tools = (
                list(self._vision_tools.tools) if self._vision_tools is not None else []
            )
            standby_tools = StandbyAgentTools(request_standby)
            tools.extend(standby_tools.tools)
        try:
            try:
                await session.start(
                    agent=JarvisVoiceAgent(
                        tools=tools,
                        default_media_target=self.config.default_media_target,
                    )
                )
            except Exception:
                bridge.conversation.fail()
                raise
            self._state = VoiceRuntimeState.ACTIVE
            LOGGER.info("JARVIS realtime conversation is active")
            if initial_instructions is not None:
                prompt_handle = session.generate_reply(
                    instructions=initial_instructions,
                    allow_interruptions=True,
                    input_modality="text",
                )
                await self._wait_for_realtime_speech(
                    prompt_handle,
                    label=initial_prompt_label,
                )
            if pre_roll_after_monotonic is not None:
                wake_ack_task = asyncio.create_task(
                    maybe_acknowledge_wake(),
                    name="jarvis-wake-acknowledgement",
                )
            if turn_capture is not None:
                LOGGER.info(
                    "Speaker shadow bridge active: committed user turns snapshot a bounded "
                    "memory-only canonical conversation-audio window + live-owner context; "
                    "prototype admission remains disabled"
                )
            if self._active_speaker_provider is not None:
                if paired_turn_capture is None:
                    LOGGER.info(
                        "LR-ASD active-speaker shadow is active: canonical LiveKit user PCM + "
                        "timestamped selected-camera Vision owner/head frames are reused; scores remain "
                        "diagnostic only; active-speaker confirmation and prototype admission "
                        "remain disabled"
                    )
                else:
                    LOGGER.info(
                        "LR-ASD active-speaker shadow is active in historical paired-A/V mode: "
                        "synchronized Pocket3 video + raw paired DJI PCM are captured once by "
                        "GStreamer; scores remain diagnostic only; active-speaker confirmation "
                        "and prototype admission remain disabled"
                    )
            await active_end.wait()
        finally:
            self._cancel_timeout()
            if (
                pre_roll_after_monotonic is not None
                and not has_user_turn
                and not exit_in_progress
                and not self._shutdown.is_set()
            ):
                self._note_wake_session_without_user_turn()
            if wake_ack_task is not None and not wake_ack_task.done():
                wake_ack_task.cancel()
                await asyncio.gather(wake_ack_task, return_exceptions=True)
            output.off("playback_finished", on_playback_finished)
            self.audio.deactivate_session()
            await session.aclose()
            if shadow_tasks:
                await asyncio.gather(*tuple(shadow_tasks), return_exceptions=True)
            if turn_capture is not None:
                turn_capture.clear()
            if paired_turn_capture is not None:
                paired_turn_capture.clear()


def build_voice_runtime(config: JarvisConfig) -> VoiceRuntimeController:
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
    if (
        config.active_speaker_shadow_enabled
        and config.active_speaker_model_path is None
    ):
        raise RuntimeError(
            "JARVIS_LR_ASD_MODEL_PATH is required when active-speaker shadow is enabled"
        )
    if (
        config.active_speaker_shadow_enabled
        and config.audio_output_wasapi_device is None
    ):
        raise RuntimeError(
            "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE is required when active-speaker paired "
            "A/V is enabled so the GStreamer AEC graph has an explicit physical render "
            "endpoint"
        )

    predictor = load_livekit_predictor(Path(config.wake_model_path))
    detector = LiveKitWakeDetector(
        predictor,
        threshold=config.wake_threshold,
        debounce_seconds=config.wake_debounce_seconds,
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
    speech_region_detector: SpeechRegionDetector | None = None

    if config.active_speaker_shadow_enabled:
        assert config.active_speaker_model_path is not None
        assert config.audio_output_wasapi_device is not None
        discovered_sources = discover_windows_av_sources()
        if len(discovered_sources) != 1:
            raise RuntimeError(
                "active-speaker shadow requires exactly one physically paired Windows AV "
                f"source; discovered {len(discovered_sources)}"
            )
        active_speaker_audio_capture = InMemorySpeakerTurnCapture(
            max_turn_seconds=config.max_utterance_seconds
        )
        active_speaker_av_source = GStreamerPairedAVSource(
            discovered_sources[0],
            GStreamerPairedAVConfig(
                audio_rate=48_000,
                playback_device_id=config.audio_output_wasapi_device,
            ),
        )
        audio: LocalAudioRuntime | PairedAudioRuntime = PairedAudioRuntime(
            detector,
            av_source=active_speaker_av_source,
            pre_roll_seconds=config.audio_pre_roll_seconds,
            ring_buffer_seconds=config.audio_ring_buffer_seconds,
        )
        if config.audio_input_device is not None:
            LOGGER.info(
                "JARVIS_AUDIO_INPUT_DEVICE is ignored because paired GStreamer DJI PCM "
                "is the canonical microphone source"
            )
        if config.audio_output_device is not None:
            LOGGER.info(
                "JARVIS_AUDIO_OUTPUT_DEVICE is ignored in paired full-duplex mode; "
                "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE is the canonical render endpoint"
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

        def on_paired_clean_audio(
            data: bytes,
            sample_rate: int,
            num_channels: int,
            samples_per_channel: int,
            observed_at_monotonic: float,
        ) -> None:
            assert isinstance(audio, PairedAudioRuntime)
            audio.feed_clean_pcm(
                data,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
                observed_at_monotonic=observed_at_monotonic,
            )

        active_speaker_av_source.set_audio_frame_tap(on_paired_raw_audio)
        active_speaker_av_source.set_clean_audio_frame_tap(on_paired_clean_audio)
        active_speaker_visual_buffer = ActiveSpeakerVisualBuffer(
            max_seconds=config.max_utterance_seconds + 1.0
        )
        active_speaker_provider = LrAsdActiveSpeakerProvider(
            config.active_speaker_model_path
        )
        speech_region_detector = LiveKitSileroSpeechRegionDetector()
    else:
        audio = LocalAudioRuntime(
            detector,
            input_device_name=config.audio_input_device,
            output_device_name=config.audio_output_device,
            pre_roll_seconds=config.audio_pre_roll_seconds,
            ring_buffer_seconds=config.audio_ring_buffer_seconds,
        )

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
    runtime = build_voice_runtime(config)
    await runtime.run()


def main() -> None:
    try:
        asyncio.run(_run_from_environment())
    except KeyboardInterrupt:
        LOGGER.info("JARVIS voice runtime stopped")


if __name__ == "__main__":
    main()
