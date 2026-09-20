"""Canonical user-PCM speaker and active-speaker shadow diagnostics.

The controller keeps speaker identity off the conversation critical path. Each
committed user turn is already submitted as a background task by VoiceRuntimeController;
this specialization trims the canonical PCM once, scores an enrolled CAM++ OWNER
voice template when available, and runs LR-ASD in parallel when enabled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.config import JarvisConfig
from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
)
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_shadow import EnrolledSpeakerShadowObserver
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.knowledge.research import CurrentResearchService
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.runtime import MemoryRuntime
from jarvis.provider_retry import delivery_retry_delay_seconds, provider_retry_hint
from jarvis.voice.capability_tools import LocalReadAgentTools
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.research_tools import ResearchAgentTools
from jarvis.voice.runtime import VoiceRuntimeController
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.models import DeliveryPolicy, WorkDeliveryKind
from jarvis.work.runtime import WorkRuntime

LOGGER = logging.getLogger(__name__)


class _SessionToolBundle:
    """Combine vision with per-session memory, research, and governed capabilities."""

    def __init__(
        self,
        vision_tools: Any | None,
        conversation_getter: Callable[[], ConversationSession | None],
        *,
        memory_runtime: MemoryRuntime | None,
        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None,
        research_service: CurrentResearchService | None,
        capability_runtime: CapabilityRuntime | None,
        work_runtime: WorkRuntime | None = None,
    ) -> None:
        self._vision_tools = vision_tools
        self._conversation_getter = conversation_getter
        self._memory_runtime = memory_runtime
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._capability_runtime = capability_runtime
        self._work_runtime = work_runtime

    @property
    def tools(self) -> list:
        tools = list(self._vision_tools.tools) if self._vision_tools is not None else []
        conversation = self._conversation_getter()
        if conversation is None:
            return tools
        if self._memory_runtime is not None:
            tools.extend(
                MemoryAgentTools(
                    self._memory_runtime.service,
                    conversation,
                    semantic_query_coordinator=self._memory_query_coordinator,
                ).tools
            )
        if self._research_service is not None:
            tools.extend(ResearchAgentTools(self._research_service, conversation).tools)
        if self._capability_runtime is not None:
            tools.extend(
                LocalReadAgentTools(self._capability_runtime, conversation).tools
            )
        if self._work_runtime is not None:
            tools.extend(WorkAgentTools(self._work_runtime, conversation).tools)
        return tools


class CanonicalActiveSpeakerRuntimeController(VoiceRuntimeController):
    """Run CAM++ + LR-ASD shadow analysis on one canonical microphone timeline."""

    def __init__(
        self,
        *args: Any,
        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,
        memory_runtime: MemoryRuntime | None = None,
        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None = None,
        research_service: CurrentResearchService | None = None,
        capability_runtime: CapabilityRuntime | None = None,
        work_runtime: WorkRuntime | None = None,
        **kwargs: Any,
    ) -> None:
        original_session_factory = kwargs.pop("session_factory", create_voice_session)
        self._session_conversation: ConversationSession | None = None
        self._user_is_speaking = False
        self._session_ready_for_inactivity = False
        self._agent_state = "unavailable"
        self._live_session: Any | None = None

        def capture_session(config: JarvisConfig):
            session, bridge = original_session_factory(config)
            self._live_session = session
            self._session_conversation = bridge.conversation
            self._user_is_speaking = False
            self._session_ready_for_inactivity = False
            self._agent_state = "unavailable"
            if work_runtime is not None:
                work_runtime.set_interactive_brain_active(False)

            def sync_interactive_brain_gate() -> None:
                if work_runtime is None:
                    return
                interactive = self._user_is_speaking or self._agent_state in {
                    "thinking",
                    "speaking",
                }
                work_runtime.set_interactive_brain_active(interactive)

            def track_agent_state(event: AgentStateChangedEvent) -> None:
                self._agent_state = event.new_state
                sync_interactive_brain_gate()
                LOGGER.info(
                    "Voice agent state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if self._session_ready_for_inactivity:
                    return
                if event.new_state != "listening":
                    return

                self._session_ready_for_inactivity = True
                if self._user_is_speaking:
                    self._cancel_timeout()
                    return
                self._arm_timeout(config.initial_request_timeout_seconds)

            def track_user_activity(event: UserStateChangedEvent) -> None:
                LOGGER.info(
                    "Voice user state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if event.new_state == "speaking":
                    if bridge.conversation.status is ConversationStatus.ACTIVE:
                        bridge.conversation.begin_user_activity()
                    self._user_is_speaking = True
                    sync_interactive_brain_gate()
                    self._cancel_timeout()
                    return
                if event.new_state != "listening":
                    return

                self._user_is_speaking = False
                sync_interactive_brain_gate()
                if not self._session_ready_for_inactivity:
                    return
                has_user_turn = any(
                    turn.role is ConversationRole.USER
                    for turn in bridge.conversation.turns
                )
                timeout = (
                    config.follow_up_timeout_seconds
                    if has_user_turn
                    else config.initial_request_timeout_seconds
                )
                self._arm_timeout(timeout)

            def clear_live_session(event) -> None:
                del event
                if self._live_session is session:
                    self._live_session = None
                    self._agent_state = "unavailable"
                    self._user_is_speaking = False
                    if work_runtime is not None:
                        work_runtime.set_interactive_brain_active(False)

            session.on("agent_state_changed", track_agent_state)
            session.on("user_state_changed", track_user_activity)
            session.on("close", clear_live_session)
            return session, bridge

        super().__init__(*args, session_factory=capture_session, **kwargs)
        self._speaker_shadow_observer = speaker_shadow_observer
        self._memory_runtime = memory_runtime
        if memory_query_coordinator is not None and memory_runtime is None:
            raise ValueError(
                "memory_query_coordinator requires an active memory runtime"
            )
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._capability_runtime = capability_runtime
        self._work_runtime = work_runtime
        if (
            memory_runtime is not None
            or research_service is not None
            or capability_runtime is not None
            or work_runtime is not None
        ):
            self._vision_tools = _SessionToolBundle(
                self._vision_tools,
                lambda: self._session_conversation,
                memory_runtime=memory_runtime,
                memory_query_coordinator=memory_query_coordinator,
                research_service=research_service,
                capability_runtime=capability_runtime,
                work_runtime=work_runtime,
            )

    @staticmethod
    def _work_delivery_text(kind: WorkDeliveryKind, message: str) -> str:
        normalized = " ".join(message.split())
        if kind is WorkDeliveryKind.OWNER_INPUT:
            return f"Sir, I need your input on a background task. {normalized}"
        if kind is WorkDeliveryKind.FAILURE:
            return f"Sir, a background task failed. {normalized}"
        return f"Sir, {normalized}"

    async def _deliver_pending_work(self) -> None:
        while not self._shutdown.is_set():
            runtime = self._work_runtime
            output = self.audio.output
            active = (
                runtime is not None
                and output is not None
                and self._state.value == "active"
                and not self._user_is_speaking
            )
            if not active:
                await asyncio.sleep(0.5)
                continue

            due = runtime.store.list_due_deliveries(limit=5)
            if not due:
                await asyncio.sleep(0.5)
                continue

            delivery = due[0]
            if (
                delivery.policy is DeliveryPolicy.WHEN_IDLE
                and self._agent_state != "listening"
            ):
                await asyncio.sleep(0.25)
                continue

            if (
                delivery.policy is DeliveryPolicy.INTERRUPT
                and self._agent_state != "listening"
            ):
                session = self._live_session
                if session is None:
                    await asyncio.sleep(0.25)
                    continue
                try:
                    await session.interrupt(force=True)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Could not interrupt realtime response for urgent work delivery"
                    )
                    await asyncio.sleep(0.5)
                    continue

            try:
                await self._get_scripted_speech().speak(
                    output,
                    self._work_delivery_text(delivery.kind, delivery.message),
                    max_provider_retries=0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                hint = provider_retry_hint(exc)
                retry_seconds = delivery_retry_delay_seconds(
                    failed_attempts=delivery.failed_attempts,
                    provider_hint=hint,
                )
                if hint is not None:
                    reason = (
                        f"provider_{hint.reason}"
                        if hint.status_code is None
                        else f"provider_{hint.reason}_{hint.status_code}"
                    )
                else:
                    reason = f"tts_{type(exc).__name__.casefold()}"

                deferred = runtime.store.schedule_delivery_retry(
                    delivery.delivery_id,
                    delay_seconds=retry_seconds,
                    reason=reason,
                )
                if hint is not None:
                    LOGGER.warning(
                        "Background work notification deferred for provider pressure | "
                        "delivery_id=%s | failed_attempts=%s | retry_in=%.1fs | "
                        "reason=%s | provider_status=%s | provider_retry_after=%s",
                        delivery.delivery_id,
                        deferred.failed_attempts,
                        retry_seconds,
                        reason,
                        hint.status_code,
                        hint.retry_after_seconds,
                    )
                else:
                    LOGGER.exception(
                        "Background work notification delivery failed; durable "
                        "backoff scheduled | delivery_id=%s | failed_attempts=%s | "
                        "retry_in=%.1fs | reason=%s",
                        delivery.delivery_id,
                        deferred.failed_attempts,
                        retry_seconds,
                        reason,
                    )
                await asyncio.sleep(0.2)
                continue

            runtime.store.mark_delivery_delivered(delivery.delivery_id)
            LOGGER.info(
                "Background work notification delivered | delivery_id=%s | "
                "work_id=%s | kind=%s | policy=%s",
                delivery.delivery_id,
                delivery.work_id,
                delivery.kind.value,
                delivery.policy.value,
            )
            await asyncio.sleep(0.2)

    def _arm_timeout(self, seconds: float) -> None:
        """Arm inactivity shutdown only after startup and only while user is silent."""

        if not self._session_ready_for_inactivity or self._user_is_speaking:
            self._cancel_timeout()
            return

        self._cancel_timeout()
        active_end = self._active_end
        if active_end is None:
            return

        def expire_inactivity() -> None:
            LOGGER.info(
                "Voice session inactivity timeout expired | seconds=%.2f | "
                "user_speaking=%s | canonical_user_turns=%s",
                seconds,
                self._user_is_speaking,
                (
                    sum(
                        turn.role is ConversationRole.USER
                        for turn in self._session_conversation.turns
                    )
                    if self._session_conversation is not None
                    else 0
                ),
            )
            active_end.set()

        self._timeout_handle = asyncio.get_running_loop().call_later(
            seconds,
            expire_inactivity,
        )

    async def run(self) -> None:
        memory_runtime = self._memory_runtime
        capability_runtime = self._capability_runtime
        delivery_task: asyncio.Task[None] | None = None
        if memory_runtime is not None:
            await memory_runtime.start()
            LOGGER.info(
                "JARVIS explicit persistent memory is active; implicit admission remains disabled"
            )
            if self._memory_query_coordinator is not None:
                LOGGER.warning(
                    "Bounded provider-assisted semantic recall is active | provider=%s | "
                    "model=%s | final semantic verification is probabilistic and fail-closed",
                    self._memory_query_coordinator.provider_name,
                    self._memory_query_coordinator.model_name,
                )
        if self._research_service is not None:
            LOGGER.info(
                "Step-6 web research tool is active | search_provider=%s | "
                "active_brain_independent=True",
                self._research_service.provider_name,
            )
        if self._work_runtime is not None:
            LOGGER.info(
                "Persistent concurrent work orchestration is active | "
                "supported_types=%s | voice_session_ownership=False",
                ",".join(
                    sorted(
                        item.value for item in self._work_runtime.supported_work_types
                    )
                ),
            )
        if capability_runtime is not None:
            capability_catalog = capability_runtime.refresh_catalog()
            browser_hands = capability_catalog.by_key("browser:playwright")
            LOGGER.info(
                "Governed local capabilities are active | local_reads=True | "
                "structured_desktop_control=True | visual_fallback=owner_opt_in | "
                "browser_control=%s | raw_shell=False",
                bool(browser_hands and browser_hands.execution_enabled),
            )
        if self._work_runtime is not None:
            delivery_task = asyncio.create_task(
                self._deliver_pending_work(),
                name="jarvis-work-delivery",
            )
        try:
            await super().run()
        finally:
            if delivery_task is not None:
                delivery_task.cancel()
                await asyncio.gather(delivery_task, return_exceptions=True)
            self._session_ready_for_inactivity = False
            self._user_is_speaking = False
            self._session_conversation = None
            self._agent_state = "unavailable"
            self._live_session = None
            if self._work_runtime is not None:
                self._work_runtime.set_interactive_brain_active(False)
            if self._work_runtime is not None:
                self._work_runtime.close()
            if capability_runtime is not None:
                capability_runtime.close()
            if self._research_service is not None:
                await self._research_service.close()
            if memory_runtime is not None:
                await memory_runtime.close()

    async def _score_enrolled_speaker(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
    ) -> None:
        observer = self._speaker_shadow_observer
        if observer is None:
            return
        try:
            result = await asyncio.to_thread(
                observer.score,
                turn.samples,
                sample_rate=turn.sample_rate,
            )
        except Exception:
            LOGGER.exception(
                "Enrolled speaker shadow turn %s failed; conversation is unaffected",
                audio_turn_id,
            )
            return
        LOGGER.info(
            "Enrolled speaker shadow turn %s | state=%s | max_owner_cosine=%s | "
            "embedding_ms=%.1f | threshold_selected=False | owner_classification=False | "
            "authority_effect=False | reasons=%s",
            audio_turn_id,
            result.state,
            (
                f"{result.max_reference_cosine:.4f}"
                if result.max_reference_cosine is not None
                else "n/a"
            ),
            result.embedding_ms,
            ",".join(result.reason_codes) if result.reason_codes else "none",
        )

    async def _inspect_shadow_turn(
        self,
        turn: SpeakerTurnAudio,
        *,
        audio_turn_id: str,
        active_speaker_turn: SpeakerTurnAudio | None = None,
    ) -> None:
        del active_speaker_turn

        analysis_turn = turn
        speech_segments = 0
        speech_detector = self._speech_region_detector
        if speech_detector is not None:
            region = await speech_detector.extract(turn)
            speech_segments = region.segment_count
            if region.turn is None:
                owner_context_live = bool(
                    self._owner_context_state is not None
                    and self._owner_context_state.has_fresh_live_owner_candidate()
                )
                LOGGER.info(
                    "Speaker shadow turn %s | source=canonical_livekit_pcm | "
                    "captured=%.2fs | speech=none | accepted=False | "
                    "live_owner_context=%s | enrolled_speaker_scored=False | "
                    "active_speaker_confirmed=False | prototype_admission=False | "
                    "reasons=%s",
                    audio_turn_id,
                    turn.duration_seconds,
                    owner_context_live,
                    region.reason,
                )
                return
            analysis_turn = region.turn

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
            "Speaker shadow turn %s | source=canonical_livekit_pcm | captured=%.2fs | "
            "speech=%.2fs | segments=%s | rms %.1f dBFS | accepted=%s | "
            "live_owner_context=%s | active_speaker_confirmed=False | "
            "prototype_admission=False | reasons=%s",
            audio_turn_id,
            turn.duration_seconds,
            analysis_turn.duration_seconds,
            speech_segments,
            quality.rms_dbfs,
            quality.accepted,
            owner_context_live,
            ",".join(quality.reason_codes) if quality.reason_codes else "none",
        )

        tasks = [
            self._inspect_active_speaker_turn(
                analysis_turn,
                audio_turn_id=audio_turn_id,
                quality_accepted=quality.accepted,
            )
        ]
        if quality.accepted and self._speaker_shadow_observer is not None:
            tasks.append(
                self._score_enrolled_speaker(
                    analysis_turn,
                    audio_turn_id=audio_turn_id,
                )
            )
        elif self._speaker_shadow_observer is not None:
            LOGGER.info(
                "Enrolled speaker shadow turn %s | state=insufficient | "
                "threshold_selected=False | owner_classification=False | "
                "authority_effect=False | reasons=speaker_quality_rejected",
                audio_turn_id,
            )
        await asyncio.gather(*tasks)
