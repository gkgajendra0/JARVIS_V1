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
from time import monotonic
from typing import Any

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent
from livekit.agents.llm import FunctionCall

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
from jarvis.voice.capability_tools import LocalReadAgentTools
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.personal_context import (
    PersonalContextAgentTools,
    PersonalContextSession,
)
from jarvis.voice.personal_context_audio import PersonalContextAudioOutput
from jarvis.voice.research_tools import ResearchAgentTools
from jarvis.voice.runtime import VoiceRuntimeController, VoiceRuntimeState
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.models import WorkDeliveryKind, WorkState
from jarvis.work.provider_retry import delivery_retry_delay_seconds, provider_retry_hint
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
        research_result_observer: Callable[[dict[str, object]], None] | None = None,
        capability_runtime: CapabilityRuntime | None,
        work_runtime: WorkRuntime | None = None,
        personal_context_getter: Callable[[], PersonalContextSession | None]
        | None = None,
    ) -> None:
        self._vision_tools = vision_tools
        self._conversation_getter = conversation_getter
        self._memory_runtime = memory_runtime
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._research_result_observer = research_result_observer
        self._capability_runtime = capability_runtime
        self._work_runtime = work_runtime
        self._personal_context_getter = personal_context_getter or (lambda: None)

    @property
    def tools(self) -> list:
        tools = list(self._vision_tools.tools) if self._vision_tools is not None else []
        conversation = self._conversation_getter()
        if conversation is None:
            return tools
        if self._memory_runtime is not None:
            personal = self._personal_context_getter()
            tools.extend(
                MemoryAgentTools(
                    self._memory_runtime.service,
                    conversation,
                    semantic_query_coordinator=self._memory_query_coordinator,
                    personal_context=personal,
                ).tools
            )
            if personal is not None:
                tools.extend(PersonalContextAgentTools(personal).tools)
        if self._research_service is not None:
            tools.extend(
                ResearchAgentTools(
                    self._research_service,
                    conversation,
                    result_observer=self._research_result_observer,
                ).tools
            )
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
        research_result_observer: Callable[[dict[str, object]], None] | None = None,
        capability_runtime: CapabilityRuntime | None = None,
        work_runtime: WorkRuntime | None = None,
        routing_runtime=None,
        semantic_session_factory=None,
        semantic_producer=None,
        semantic_authorization_binding=None,
        semantic_on_applied=None,
        semantic_on_applied_factory=None,
        semantic_accepted_plan_epoch=None,
        semantic_topic_resume_enabled=False,
        **kwargs: Any,
    ) -> None:
        original_session_factory = kwargs.pop("session_factory", create_voice_session)
        self._session_conversation: ConversationSession | None = None
        self._user_is_speaking = False
        self._session_ready_for_inactivity = False
        self._agent_state = "unavailable"
        self._live_session: Any | None = None
        self._personal_context: PersonalContextSession | None = None
        self._personal_learning = None
        self._learning_authority = None
        self._learning_grant = None
        self._learning_start_attempted = False
        self._semantic_context_attachment = None
        if semantic_session_factory is not None:
            if not callable(semantic_session_factory):
                raise TypeError("semantic_session_factory must be callable")
            if any(
                value is not None
                for value in (
                    semantic_producer,
                    semantic_authorization_binding,
                    semantic_on_applied,
                    semantic_on_applied_factory,
                    semantic_accepted_plan_epoch,
                )
            ):
                raise ValueError("choose semantic session factory or direct components")
            if memory_runtime is None or capability_runtime is None:
                raise ValueError(
                    "Semantic voice requires canonical memory and authority"
                )
        if type(semantic_topic_resume_enabled) is not bool:
            raise TypeError("semantic_topic_resume_enabled must be a bool")
        if semantic_topic_resume_enabled and (
            memory_runtime is None or capability_runtime is None
        ):
            raise ValueError(
                "Topic resumption requires canonical memory and capability authority"
            )
        if semantic_on_applied is not None and semantic_on_applied_factory is not None:
            raise ValueError(
                "choose one semantic commit callback or per-session factory"
            )
        if semantic_on_applied_factory is not None and not callable(
            semantic_on_applied_factory
        ):
            raise TypeError("semantic_on_applied_factory must be callable")
        if (
            semantic_on_applied is not None or semantic_on_applied_factory is not None
        ) and (semantic_producer is None or not callable(semantic_accepted_plan_epoch)):
            raise ValueError(
                "Checkpoint persistence requires authorized producer and "
                "accepted-turn plan epoch capture"
            )
        if (semantic_producer is None) != (semantic_authorization_binding is None):
            raise ValueError(
                "Semantic voice requires both an authorized producer and owner binding"
            )
        if semantic_producer is not None and (
            memory_runtime is None or capability_runtime is None
        ):
            raise ValueError(
                "Semantic voice requires canonical encrypted memory and capability authority"
            )
        if (
            args
            and args[0].personal_context_mode == "apply"
            and (memory_runtime is None or capability_runtime is None)
        ):
            raise ValueError(
                "Personal context APPLY requires canonical memory and capability authority"
            )

        def capture_session(config: JarvisConfig):
            session, bridge = original_session_factory(config)
            self._live_session = session
            self._session_conversation = bridge.conversation
            self._user_is_speaking = False
            self._session_ready_for_inactivity = False
            self._agent_state = "unavailable"
            if config.personal_context_mode == "apply":
                if memory_runtime is None or capability_runtime is None:
                    raise ValueError(
                        "Personal context APPLY requires canonical memory and capability authority"
                    )

                def retire_personal():
                    if self._live_session is session and self._active_end is not None:
                        if personal.retirement_reason in {
                            "response_completed",
                            "user_activity",
                        }:
                            self._follow_up_requested_after = monotonic()
                        LOGGER.info(
                            "Personal context session retired | reason=%s",
                            personal.retirement_reason,
                        )
                        self._active_end.set()

                def personal_busy(busy):
                    if self._live_session is not session:
                        return
                    if busy:
                        self._cancel_timeout()
                    else:
                        self._arm_timeout(config.follow_up_timeout_seconds)

                personal = PersonalContextSession(
                    conversation=bridge.conversation,
                    retrieval=memory_runtime.retrieval,
                    authority=capability_runtime,
                    retire=retire_personal,
                    busy_changed=personal_busy,
                    learning_authority=(
                        capability_runtime.personal_learning_authority
                        if config.personal_learning_mode == "apply"
                        else None
                    ),
                    learning_grant=self._learning_grant,
                    topic_checkpoints=(
                        memory_runtime.topic_checkpoints
                        if semantic_topic_resume_enabled
                        else None
                    ),
                )
                self._personal_context = personal
                bridge.add_accepted_turn_observer(personal.observe_turn)
                bridge.add_close_observer(personal.close)
            else:
                personal = None
                self._personal_context = None
            if self._personal_learning is not None and self._learning_grant is not None:
                bridge.add_accepted_turn_observer(
                    self._personal_learning.bind(
                        bridge.conversation, self._learning_grant
                    )
                )
            # Explicit opt-in only. No model dispatch, memory persistence, or
            # model-visible release without a separately provided, trusted gate.
            # The bridge closes and invalidates this state on session retirement.
            if semantic_producer is not None or semantic_session_factory is not None:
                if config.personal_context_mode != "apply":
                    raise PermissionError(
                        "Semantic voice requires protected personal context APPLY"
                    )
                from jarvis.voice.semantic_context_bridge import (
                    attach_semantic_voice_context,
                    resolve_session_commit_callback,
                    resolve_session_components,
                )

                if semantic_session_factory is not None:
                    components = resolve_session_components(
                        bridge.conversation, factory=semantic_session_factory
                    )
                    producer = components.producer
                    binding = components.authorization_binding
                    applied = components.on_applied
                    plan_epoch = components.accepted_plan_epoch
                else:
                    producer = semantic_producer
                    binding = semantic_authorization_binding
                    applied = resolve_session_commit_callback(
                        bridge.conversation,
                        direct=semantic_on_applied,
                        factory=semantic_on_applied_factory,
                    )
                    plan_epoch = semantic_accepted_plan_epoch
                self._semantic_context_attachment = attach_semantic_voice_context(
                    bridge,
                    producer=producer,
                    authorization_binding=binding,
                    on_applied=applied,
                    accepted_plan_epoch=plan_epoch,
                )
            else:
                self._semantic_context_attachment = None
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
                if self._live_session is not session:
                    return
                self._agent_state = event.new_state
                sync_interactive_brain_gate()
                LOGGER.info(
                    "Voice agent state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if self._standby_requested:
                    return
                if event.new_state in {"thinking", "speaking"}:
                    self._cancel_timeout()
                    return
                if event.new_state != "listening":
                    return

                self._session_ready_for_inactivity = True
                has_user_turn = any(
                    turn.role is ConversationRole.USER
                    for turn in bridge.conversation.turns
                )
                self._arm_timeout(
                    config.follow_up_timeout_seconds
                    if has_user_turn or self._follow_up_listening
                    else config.initial_request_timeout_seconds
                )

            def track_user_activity(event: UserStateChangedEvent) -> None:
                if self._live_session is not session or self._standby_requested:
                    return
                LOGGER.info(
                    "Voice user state changed: %s -> %s",
                    event.old_state,
                    event.new_state,
                )
                if event.new_state == "speaking":
                    if bridge.conversation.status is ConversationStatus.ACTIVE:
                        bridge.conversation.begin_user_activity()
                        if personal is not None:
                            personal.observe_activity()
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
                    if has_user_turn or self._follow_up_listening
                    else config.initial_request_timeout_seconds
                )
                self._arm_timeout(timeout)

            def clear_live_session(event) -> None:
                del event
                if self._live_session is session:
                    if personal is not None:
                        personal.close()
                    self._personal_context = None
                    self._live_session = None
                    self._agent_state = "unavailable"
                    self._user_is_speaking = False
                    if work_runtime is not None:
                        work_runtime.set_interactive_brain_active(False)

            def track_speech(event):
                if personal is None:
                    return

                def finished(handle):
                    if self._live_session is not session:
                        return
                    # Gemini's automatic tool follow-up has a SEPARATE handle.
                    # The completed tool/preamble handle is not the final answer.
                    if config.ai_provider == "gemini" and any(
                        isinstance(item, FunctionCall) for item in handle.chat_items
                    ):
                        return
                    if handle.interrupted:
                        if personal.protected:
                            personal.close()
                        return
                    personal.response_finished()

                event.speech_handle.add_done_callback(finished)

            session.on("agent_state_changed", track_agent_state)
            session.on("user_state_changed", track_user_activity)
            session.on("close", clear_live_session)
            session.on("speech_created", track_speech)
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
        self._research_result_observer = research_result_observer
        self._capability_runtime = capability_runtime
        self._work_runtime = work_runtime
        self._routing_runtime = routing_runtime
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
                research_result_observer=research_result_observer,
                capability_runtime=capability_runtime,
                work_runtime=work_runtime,
                personal_context_getter=lambda: self._personal_context,
            )

    async def _validate_gemini_handoff(self, bridge):
        if (
            not await super()._validate_gemini_handoff(bridge)
            or self._session_conversation is not bridge.conversation
        ):
            return False
        # Ordinary voice can outlive the memory timer. OS/authority revocation
        # still blocks the transport; protected restores keep their own permit.
        if self._learning_grant is not None and self._learning_authority is not None:
            try:
                state = await asyncio.to_thread(
                    self._learning_authority.validate, self._learning_grant
                )
            except Exception:  # noqa: BLE001 - unavailable continuity fails closed
                return False
            if state.status not in {"active", "expired"}:
                return False
        personal = self._personal_context
        return personal is None or await personal.validate_transport_restore()

    def _session_audio_output(self, bridge, output):
        personal = self._personal_context
        if personal is not None and bridge.conversation is self._session_conversation:
            return PersonalContextAudioOutput(output, personal)
        return output

    @staticmethod
    def _work_delivery_text(kind: WorkDeliveryKind, message: str) -> str:
        normalized = " ".join(message.split())
        if kind is WorkDeliveryKind.OWNER_INPUT:
            return f"Sir, I need your input on a background task. {normalized}"
        if kind is WorkDeliveryKind.FAILURE:
            return f"Sir, a background task failed. {normalized}"
        return f"Sir, {normalized}"

    @staticmethod
    def _work_delivery_is_current(kind: WorkDeliveryKind, state: WorkState) -> bool:
        """Only speak a durable notification while its underlying state is current."""

        if kind is WorkDeliveryKind.OWNER_INPUT:
            return state is WorkState.WAITING_FOR_OWNER
        if kind is WorkDeliveryKind.RESOURCE_BLOCKER:
            return state in {
                WorkState.WAITING_RESOURCE,
                WorkState.WAITING_DEPENDENCY,
                WorkState.WAITING_UNTIL,
            }
        if kind is WorkDeliveryKind.PROGRESS:
            return not state.terminal
        if kind is WorkDeliveryKind.COMPLETION:
            return state is WorkState.COMPLETED
        if kind is WorkDeliveryKind.FAILURE:
            return state is WorkState.FAILED
        return True

    async def _run_owner_input_interaction(
        self,
        *,
        work_id: str,
        question: str,
    ) -> bool:
        """Open one bounded proactive conversation for an exact waiting WorkItem.

        Work/DBOS remains the durable owner-input truth. This method owns only the
        voice transport: it asks the pending question, leaves the microphone active,
        and exposes only answer-or-cancel Work tools bound to the waiting WorkItem. The
        shared speech lease is held by the caller for the entire session, so no second
        JARVIS producer can write to the physical output concurrently.
        """

        runtime = self._work_runtime
        if runtime is None:
            raise RuntimeError("owner-input interaction requires WorkRuntime")

        normalized_question = " ".join(question.split())
        if not normalized_question:
            raise ValueError("owner-input question must not be empty")

        owner_input_submitted = asyncio.Event()

        def session_tools(conversation: ConversationSession) -> list:
            work_tools = WorkAgentTools(
                runtime,
                conversation,
                bound_owner_input_work_id=work_id,
                on_bound_owner_input_submitted=lambda _work: (
                    owner_input_submitted.set()
                ),
            )
            return [
                work_tools.continue_background_work,
                work_tools.cancel_background_work,
            ]

        def owner_input_resolved() -> bool:
            return owner_input_submitted.is_set()

        instructions = (
            "JARVIS has proactively opened this voice interaction because one exact "
            "background WorkItem is waiting for the owner's input. Ask the owner the "
            "pending question below naturally and concisely, preserving every concrete "
            "fact, option, identifier, number, and required action. Then stop and listen; "
            "the owner does not need to say the wake word. Interpret short or imperfect "
            "speech transcription in the context of this exact question. If the answer "
            "is genuinely ambiguous, ask one concise clarification and keep listening. "
            "When the owner clearly answers, call continue_background_work. If the owner "
            "instead clearly asks to cancel or stop this exact pending task, call "
            "cancel_background_work. Both tools are already deterministically bound to "
            "the correct WorkItem, so do not invent or target another work ID. After one "
            "tool succeeds, acknowledge briefly and do not start, reprioritize, or modify "
            "any other work. Pending question: " + normalized_question
        )

        try:
            await self._run_one_session_owned(
                initial_instructions=instructions,
                initial_prompt_label="owner input prompt",
                session_tool_factory=session_tools,
                completion_predicate=owner_input_resolved,
                completion_label=f"owner input for {work_id}",
            )
        finally:
            self._cancel_timeout()
            self._active_end = None
            if not self._shutdown.is_set():
                self._state = VoiceRuntimeState.IDLE

        return owner_input_submitted.is_set()

    async def _deliver_pending_work(self) -> None:
        """Speak durable Work notifications only at an exclusive idle boundary.

        Realtime AgentSession output owns the physical speaker for the whole
        conversation. Background lifecycle speech therefore stays queued until no
        live session exists, then temporarily suspends wake detection while a
        short realtime-model session speaks it. This prevents two JARVIS producers
        from interleaving frames on the same MediaDevices output and prevents
        JARVIS from hearing its own notification as a fresh user/wake utterance.
        """

        while not self._shutdown.is_set():
            runtime = self._work_runtime
            output = self.audio.output
            idle_boundary = (
                runtime is not None
                and output is not None
                and self._state.value == "idle"
                and self._live_session is None
            )
            if not idle_boundary:
                await asyncio.sleep(0.25)
                continue

            due = runtime.store.list_due_deliveries(limit=5)
            if not due:
                await asyncio.sleep(0.5)
                continue

            delivery = due[0]
            work = runtime.store.require(delivery.work_id)
            if not self._work_delivery_is_current(delivery.kind, work.state):
                runtime.store.mark_delivery_delivered(delivery.delivery_id)
                LOGGER.info(
                    "Obsolete background notification discarded | "
                    "delivery_id=%s | work_id=%s | kind=%s | current_state=%s",
                    delivery.delivery_id,
                    delivery.work_id,
                    delivery.kind.value,
                    work.state.value,
                )
                await asyncio.sleep(0)
                continue

            # A wake activation and a Work notification may become ready on the
            # same event-loop turn. The shared lease makes the winner explicit;
            # after waiting, re-check lifecycle truth before producing audio.
            async with self._speech_ownership:
                runtime = self._work_runtime
                output = self.audio.output
                if (
                    runtime is None
                    or output is None
                    or self._state.value != "idle"
                    or self._live_session is not None
                ):
                    continue

                self.audio.detector.disable()
                spoken = False
                try:
                    delivery_text = self._work_delivery_text(
                        delivery.kind,
                        delivery.message,
                    )
                    if delivery.kind is WorkDeliveryKind.OWNER_INPUT:
                        answered = await self._run_owner_input_interaction(
                            work_id=delivery.work_id,
                            question=delivery.message,
                        )
                        if not answered:
                            retry_seconds = max(
                                30.0,
                                delivery_retry_delay_seconds(
                                    failed_attempts=delivery.failed_attempts,
                                    provider_hint=None,
                                ),
                            )
                            deferred = runtime.store.schedule_delivery_retry(
                                delivery.delivery_id,
                                delay_seconds=retry_seconds,
                                reason="owner_input_unanswered",
                            )
                            LOGGER.info(
                                "Owner-input interaction ended without a resolved answer; "
                                "durable retry scheduled | delivery_id=%s | work_id=%s | "
                                "failed_attempts=%s | retry_in=%.1fs",
                                delivery.delivery_id,
                                delivery.work_id,
                                deferred.failed_attempts,
                                retry_seconds,
                            )
                        else:
                            spoken = True
                    else:
                        await self._speak_ephemeral_realtime_message(
                            output,
                            instructions=(
                                "Deliver the following background-task notification to the "
                                "owner in one or two brief, natural sentences using your "
                                "established JARVIS voice and style. Preserve every concrete "
                                "fact, number, blocker, question, and required owner action. "
                                "Do not mention prompts, models, tools, or internal routing. "
                                "Do not add facts. Notification: " + delivery_text
                            ),
                            label="background work notification",
                        )
                        spoken = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    critical = delivery.kind in {
                        WorkDeliveryKind.RESOURCE_BLOCKER,
                        WorkDeliveryKind.FAILURE,
                    }
                    local_speech = self._local_status_speech
                    if critical and local_speech is not None:
                        try:
                            await local_speech.speak(output, delivery_text)
                            spoken = True
                            LOGGER.warning(
                                "Critical background notification used local speech fallback | "
                                "delivery_id=%s | work_id=%s | kind=%s | cloud_error=%s",
                                delivery.delivery_id,
                                delivery.work_id,
                                delivery.kind.value,
                                type(exc).__name__,
                            )
                        except Exception:
                            LOGGER.exception(
                                "Critical background notification local fallback failed | "
                                "delivery_id=%s | work_id=%s | kind=%s",
                                delivery.delivery_id,
                                delivery.work_id,
                                delivery.kind.value,
                            )

                    if not spoken:
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
                            reason = f"realtime_voice_{type(exc).__name__.casefold()}"

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
                                "Background work realtime notification failed; durable "
                                "backoff scheduled | delivery_id=%s | failed_attempts=%s | "
                                "retry_in=%.1fs | reason=%s",
                                delivery.delivery_id,
                                deferred.failed_attempts,
                                retry_seconds,
                                reason,
                            )
                finally:
                    if not self._shutdown.is_set():
                        try:
                            await self.audio.resume_wake(
                                cooldown_seconds=self.config.wake_cooldown_seconds
                            )
                        except Exception:
                            LOGGER.exception(
                                "Wake detection could not resume after exclusive "
                                "background speech"
                            )
                            try:
                                self.audio.detector.enable()
                            except Exception:
                                LOGGER.exception(
                                    "Wake detector emergency re-enable also failed"
                                )

                if not spoken:
                    await asyncio.sleep(0.2)
                    continue

                runtime.store.mark_delivery_delivered(delivery.delivery_id)
                LOGGER.info(
                    "Background work notification delivered at exclusive idle boundary | "
                    "delivery_id=%s | work_id=%s | kind=%s | policy=%s",
                    delivery.delivery_id,
                    delivery.work_id,
                    delivery.kind.value,
                    delivery.policy.value,
                )
                # Keep wake detection available between queued notifications. Without
                # this owner-priority window, a recovered delivery backlog can disable
                # wake, speak, re-enable wake, and immediately disable it again before
                # the owner has a realistic chance to say the wake word.
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=max(3.0, self.config.wake_cooldown_seconds),
                    )
                except TimeoutError:
                    pass

    def _arm_timeout(self, seconds: float) -> None:
        """Arm inactivity shutdown only after startup and only while user is silent."""

        if self._standby_requested:
            super()._arm_timeout(seconds)
            return

        if (
            not self._session_ready_for_inactivity
            or self._agent_state in {"thinking", "speaking"}
            or self._user_is_speaking
            or (self._personal_context is not None and self._personal_context.busy)
        ):
            self._cancel_timeout()
            return

        self._cancel_timeout()
        active_end = self._active_end
        if active_end is None:
            return

        def expire_inactivity() -> None:
            if (
                self._active_end is not active_end
                or self._user_is_speaking
                or self._agent_state in {"thinking", "speaking"}
                or (self._personal_context is not None and self._personal_context.busy)
            ):
                return
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

    @staticmethod
    def _learning_failure_reason(error):
        # Emit only fixed reason labels, never exception messages, provider
        # response bodies, personal facts, or credential values.
        allowed = (
            "helper_timeout",
            "helper_launch_failed",
            "helper_invalid_output",
            "helper_failed",
            "helper_not_found",
            "helper_not_configured",
            "helper_unknown_status",
            "session_mismatch",
            "proposal_integrity_invalid",
        )
        seen = set()
        for _ in range(8):
            if error is None or id(error) in seen:
                break
            seen.add(id(error))
            message = str(error)
            for reason in allowed:
                if reason in message:
                    return reason
            error = getattr(error, "__cause__", None) or getattr(
                error, "__context__", None
            )
        return "unclassified"

    async def _start_personal_learning(self):
        if (
            self.config.personal_learning_mode != "apply"
            or self._learning_start_attempted
        ):
            return
        self._learning_start_attempted = True
        from uuid import uuid4

        from jarvis.memory.learning_extractors import build_learning_adapters
        from jarvis.memory.learning_reconciliation import LearningReconciler
        from jarvis.memory.learning_runtime import PersonalLearningRuntime

        capabilities = self._capability_runtime
        self._learning_authority = capabilities.personal_learning_authority
        phase = "authorize"
        try:
            grant = await asyncio.to_thread(
                capabilities.open_personal_learning,
                str(uuid4()),
                self.config.ai_provider,
            )
            self._learning_grant = grant
            phase = "memory_binding"
            self._memory_runtime.bind_learning_authority(self._learning_authority)
            phase = "category_reenable"
            for category in self.config.personal_learning_reenable_categories:
                from datetime import UTC, datetime

                from jarvis.memory.provenance import MemorySource
                from jarvis.memory.types import (
                    AuthorityClass,
                    MemorySourceClass,
                    Sensitivity,
                )

                guard = await asyncio.to_thread(
                    self._learning_authority.authorize_reenable_category, category
                )
                now = datetime.now(UTC)
                source = MemorySource(
                    str(uuid4()),
                    MemorySourceClass.OWNER_EXPLICIT,
                    "local-control:reenable:" + category,
                    now,
                    AuthorityClass.OWNER_EXPLICIT,
                    Sensitivity.STANDARD,
                    now,
                )
                await self._memory_runtime.service.reenable_learning_category(
                    category, source, guard
                )
            phase = "suppression_read"
            suppression = await self._memory_runtime.service.learning_suppression()
            LOGGER.info(
                "Personal learning suppression | categories=%s",
                ",".join(sorted(suppression.suppressed)) or "none",
            )
            if self.config.show_transcript:
                LOGGER.info(
                    "Conversation diagnostics enabled | accepted transcripts and memory decisions "
                    "are written to console and rotating logs | credentials=masked"
                )
            phase = "provider_adapters"
            extractor, resolver = build_learning_adapters(
                self.config.ai_provider,
                diagnostics=self.config.show_transcript,
                **(
                    {"routing_runtime": self._routing_runtime}
                    if self._routing_runtime is not None
                    else {}
                ),
            )
            phase = "learning_worker"
            self._personal_learning = PersonalLearningRuntime(
                self._learning_authority,
                self._memory_runtime.service,
                extractor,
                resolver,
                LearningReconciler(
                    self._memory_runtime.service.canonical_reader,
                    self._learning_authority,
                    diagnostics=self.config.show_transcript,
                ),
                diagnostics=self.config.show_transcript,
                status_observer=lambda state: LOGGER.info(
                    "Personal learning | session=%s | queued=%s | processed=%s | committed=%s | dropped=%s | reason=%s",
                    state.session,
                    state.queued,
                    state.processed,
                    state.committed,
                    state.dropped,
                    state.reason,
                ),
            )
            LOGGER.info(
                "Personal learning session active | lifetime=Jarvis_runtime_and_same_unlocked_Windows_session | idle_expiry=False | speaker_verification=False"
            )
        except Exception as exc:  # noqa: BLE001 - no provider/private error body in logs
            if self._learning_grant is not None:
                capabilities.close_personal_learning(self._learning_grant)
                self._learning_grant = None
            LOGGER.warning(
                "Personal learning session unavailable | phase=%s | error_type=%s | "
                "reason=%s; no automatic reopening",
                phase,
                type(exc).__name__,
                self._learning_failure_reason(exc),
            )

    async def run(self) -> None:
        memory_runtime = self._memory_runtime
        capability_runtime = self._capability_runtime
        delivery_task: asyncio.Task[None] | None = None
        if memory_runtime is not None:
            await memory_runtime.start()
            LOGGER.info(
                "JARVIS canonical persistent memory is active | learning_mode=%s",
                self.config.personal_learning_mode,
            )
            await self._start_personal_learning()
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
            if self._personal_learning is not None:
                await self._personal_learning.close()
            if capability_runtime is not None:
                capability_runtime.close()
            if self._research_service is not None:
                await self._research_service.close()
            if memory_runtime is not None:
                await memory_runtime.close()
            if self._routing_runtime is not None:
                await self._routing_runtime.aclose()

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
