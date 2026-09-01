"""Roomless Step-2 wake-to-conversation runtime."""

from __future__ import annotations

import asyncio
import logging
import unicodedata
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
from jarvis.voice.observed_audio import ObservedSessionAudioInput
from jarvis.voice.paired_audio import PairedAudioRuntime
from jarvis.voice.scripted_speech import ScriptedSpeech, build_scripted_speech
from jarvis.voice.startup_greeting import select_startup_greeting
from jarvis.voice.vision_tools import VisionAgentTools
from jarvis.voice.wakeword import LiveKitWakeDetector, load_livekit_predictor

LOGGER = logging.getLogger(__name__)

SessionFactory = Callable[
    [JarvisConfig], tuple[AgentSession, LiveKitConversationBridge]
]
StartupGreetingFactory = Callable[[], str]

_UPDATE_APPROVAL_PROMPT = (
    "A JARVIS software update is available. Shall I install it and restart now? "
    "Please answer yes or no."
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


_EXIT_CORES = frozenset(
    {
        "go to sleep",
        "end session",
        "end the session",
        "सो जाओ",
        "सेशन बंद करो",
    }
)
_EXIT_PREFIXES = (
    "ok ",
    "okay ",
    "hey ",
    "please ",
    "jarvis ",
    "ठीक है ",
    "कृपया ",
    "जार्विस ",
)
_EXIT_SUFFIXES = (" please", " now", " कृपया", " अभी")


def _normalized_intent(text: str) -> str:
    normalized = "".join(
        character
        if character.isspace()
        or character == "_"
        or unicodedata.category(character)[0] in {"L", "M", "N"}
        else " "
        for character in text.casefold()
    )
    return " ".join(normalized.split())


def _final_spoken_clause(text: str) -> str:
    """Return the final non-empty punctuation-delimited clause."""
    clauses: list[str] = []
    current: list[str] = []
    for character in text:
        if unicodedata.category(character).startswith("P"):
            clause = "".join(current).strip()
            if clause:
                clauses.append(clause)
            current.clear()
        else:
            current.append(character)
    clause = "".join(current).strip()
    if clause:
        clauses.append(clause)
    return clauses[-1] if clauses else text


def _is_exit_intent(text: str) -> bool:
    """Accept bounded command variants without matching quoted or negated text."""
    candidate = _normalized_intent(_final_spoken_clause(text))
    changed = True
    while changed:
        changed = False
        for prefix in _EXIT_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate.removeprefix(prefix).strip()
                changed = True
                break
    changed = True
    while changed:
        changed = False
        for suffix in _EXIT_SUFFIXES:
            if candidate.endswith(suffix):
                candidate = candidate.removesuffix(suffix).strip()
                changed = True
                break
    return candidate in _EXIT_CORES


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
        startup_greeting_factory: StartupGreetingFactory = select_startup_greeting,
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
        self._scripted_speech = scripted_speech
        self._owns_scripted_speech = False
        self._startup_greeting_factory = startup_greeting_factory

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

    def _get_scripted_speech(self) -> ScriptedSpeech:
        if self._scripted_speech is None:
            self._scripted_speech = build_scripted_speech(self.config)
            self._owns_scripted_speech = True
        return self._scripted_speech

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
        try:
            await self._get_scripted_speech().speak(output, greeting)
            LOGGER.info("JARVIS startup greeting finished playing")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("JARVIS startup greeting failed; continuing without it")

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
                    "Canonical microphone source is paired DJI PCM from GStreamer; "
                    "no PortAudio or Voicemeeter input device is open"
                )
                LOGGER.info(
                    "WebRTC APM is active on paired DJI conversation audio with Tribit "
                    "physical playback supplied as the reverse-stream echo reference"
                )
            if self._dev_control is not None:
                control_task = asyncio.create_task(
                    self._dev_control.run(
                        approval_handler=self._queue_update_approval,
                        shutdown_handler=self.request_shutdown,
                    ),
                    name="jarvis-dev-control",
                )
                LOGGER.info("JARVIS development voice-control channel is active")

            await self._speak_startup_greeting()
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
                try:
                    await self._run_one_session()
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
                await session.start(agent=JarvisVoiceAgent(tools=[]))
            except Exception:
                bridge.conversation.fail()
                raise
            self._state = VoiceRuntimeState.ACTIVE
            LOGGER.info("JARVIS is requesting spoken approval for a software update")
            await self._get_scripted_speech().speak(output, _UPDATE_APPROVAL_PROMPT)
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

    async def _run_one_session(self) -> None:
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

        def on_user_state(event: UserStateChangedEvent) -> None:
            if event.new_state == "speaking":
                self._arm_timeout(self.config.max_utterance_seconds)
            elif event.new_state == "listening":
                timeout = (
                    self.config.follow_up_timeout_seconds
                    if has_user_turn
                    else self.config.initial_request_timeout_seconds
                )
                self._arm_timeout(timeout)

        def on_agent_state(event: AgentStateChangedEvent) -> None:
            if has_user_turn and event.new_state in {"thinking", "speaking"}:
                self._cancel_timeout()

        def on_conversation_item(event: ConversationItemAddedEvent) -> None:
            nonlocal has_user_turn
            item = event.item
            if not isinstance(item, ChatMessage) or item.role != "user":
                return
            text = item.text_content.strip()
            if not text:
                return
            has_user_turn = True
            self._cancel_timeout()
            submit_shadow_turn()
            if _is_exit_intent(text):
                LOGGER.info("Explicit voice-session exit accepted")
                active_end.set()

        def on_playback_finished(event: PlaybackFinishedEvent) -> None:
            del event
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
        self.audio.activate_session(session_input)
        self._arm_timeout(self.config.initial_request_timeout_seconds)
        tools = self._vision_tools.tools if self._vision_tools is not None else []
        try:
            try:
                await session.start(agent=JarvisVoiceAgent(tools=tools))
            except Exception:
                bridge.conversation.fail()
                raise
            self._state = VoiceRuntimeState.ACTIVE
            LOGGER.info("JARVIS realtime conversation is active")
            if turn_capture is not None:
                LOGGER.info(
                    "Speaker shadow bridge active: committed user turns snapshot a bounded "
                    "memory-only canonical conversation-audio window + live-owner context; "
                    "prototype admission remains disabled"
                )
            if self._active_speaker_provider is not None:
                LOGGER.info(
                    "LR-ASD active-speaker shadow is active: synchronized Pocket3 video + "
                    "paired DJI PCM are captured once by GStreamer, local Silero trims the "
                    "paired audio, and scores remain diagnostic only; active-speaker "
                    "confirmation and prototype admission remain disabled"
                )
            await active_end.wait()
        finally:
            self._cancel_timeout()
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
            GStreamerPairedAVConfig(audio_rate=48_000),
        )
        audio: LocalAudioRuntime | PairedAudioRuntime = PairedAudioRuntime(
            detector,
            output_device_name=config.audio_output_device,
            pre_roll_seconds=config.audio_pre_roll_seconds,
            ring_buffer_seconds=config.audio_ring_buffer_seconds,
        )
        if config.audio_input_device is not None:
            LOGGER.info(
                "JARVIS_AUDIO_INPUT_DEVICE is ignored because paired GStreamer DJI PCM "
                "is the canonical microphone source"
            )

        def on_paired_audio(
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
            assert isinstance(audio, PairedAudioRuntime)
            audio.feed_external_pcm(
                data,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
                observed_at_monotonic=observed_at_monotonic,
            )

        active_speaker_av_source.set_audio_frame_tap(on_paired_audio)
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
