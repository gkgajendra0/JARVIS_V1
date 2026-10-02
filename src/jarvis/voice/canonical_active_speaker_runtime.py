"""Canonical user-PCM speaker and active-speaker shadow diagnostics.

The controller keeps speaker identity off the conversation critical path. Each
committed user turn is already submitted as a background task by VoiceRuntimeController;
this specialization trims the canonical PCM once, scores an enrolled CAM++ OWNER
voice template when available, and runs LR-ASD in parallel when enabled.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.config import JarvisConfig
from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
)
from jarvis.engineering_change.gates import GateChallenge, GateKind, GateService
from jarvis.identity.speaker_identity import assess_speaker_segment
from jarvis.identity.speaker_shadow import EnrolledSpeakerShadowObserver
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.knowledge.research import CurrentResearchService
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.runtime import MemoryRuntime
from jarvis.voice.capability_tools import LocalReadAgentTools
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.research_tools import ResearchAgentTools
from jarvis.voice.runtime import VoiceRuntimeController, VoiceRuntimeState
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.models import WorkDeliveryKind, WorkState
from jarvis.work.provider_retry import delivery_retry_delay_seconds, provider_retry_hint
from jarvis.work.runtime import WorkRuntime

LOGGER = logging.getLogger(__name__)

_OWNER_INTERACTION_RETRY_BASE_SECONDS = 30.0 * 60.0
_OWNER_INTERACTION_RETRY_MAX_SECONDS = 6.0 * 60.0 * 60.0


def _owner_interaction_retry_seconds(failed_attempts: int) -> float:
    attempts = max(0, int(failed_attempts))
    delay = _OWNER_INTERACTION_RETRY_BASE_SECONDS * (2 ** min(attempts, 4))
    return min(_OWNER_INTERACTION_RETRY_MAX_SECONDS, delay)


def _spoken_subject(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = re.sub(r"[_./:-]+", " ", raw)
    normalized = " ".join(normalized.split())
    if not normalized or normalized.startswith("change ") or normalized.startswith("gate "):
        return None
    return normalized[:80].rstrip()


class _ManagedBackgroundRuntime(Protocol):
    def start(self) -> None: ...

    async def close(self) -> None: ...


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
        gicc_tool_factory: Callable[[ConversationSession], list] | None = None,
        allow_direct_capability_acquisition: bool = True,
    ) -> None:
        self._vision_tools = vision_tools
        self._conversation_getter = conversation_getter
        self._memory_runtime = memory_runtime
        self._memory_query_coordinator = memory_query_coordinator
        self._research_service = research_service
        self._capability_runtime = capability_runtime
        self._work_runtime = work_runtime
        self._gicc_tool_factory = gicc_tool_factory
        self._allow_direct_capability_acquisition = allow_direct_capability_acquisition

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
        if self._gicc_tool_factory is not None:
            tools.extend(self._gicc_tool_factory(conversation))
        if self._work_runtime is not None:
            tools.extend(
                WorkAgentTools(
                    self._work_runtime,
                    conversation,
                    allow_capability_acquisition=(
                        self._allow_direct_capability_acquisition
                    ),
                ).tools
            )
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
        gicc_runtime: _ManagedBackgroundRuntime | None = None,
        gicc_tool_factory: Callable[[ConversationSession], list] | None = None,
        allow_direct_capability_acquisition: bool = True,
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
        self._gicc_runtime = gicc_runtime
        if (
            memory_runtime is not None
            or research_service is not None
            or capability_runtime is not None
            or work_runtime is not None
            or gicc_tool_factory is not None
        ):
            self._vision_tools = _SessionToolBundle(
                self._vision_tools,
                lambda: self._session_conversation,
                memory_runtime=memory_runtime,
                memory_query_coordinator=memory_query_coordinator,
                research_service=research_service,
                capability_runtime=capability_runtime,
                work_runtime=work_runtime,
                gicc_tool_factory=gicc_tool_factory,
                allow_direct_capability_acquisition=(
                    allow_direct_capability_acquisition
                ),
            )

    @staticmethod
    def _work_delivery_text(kind: WorkDeliveryKind, message: str) -> str:
        normalized = " ".join(message.split())
        if kind is WorkDeliveryKind.OWNER_INPUT:
            return f"Sir, I need your input on a background task. {normalized}"
        if kind is WorkDeliveryKind.CHANGE_GATE:
            return (
                f"Sir, an engineering change is waiting for your approval. {normalized}"
            )
        if kind is WorkDeliveryKind.FAILURE:
            return f"Sir, a background task failed. {normalized}"
        return f"Sir, {normalized}"

    @staticmethod
    def _work_delivery_is_current(kind: WorkDeliveryKind, state: WorkState) -> bool:
        """Only speak a durable notification while its underlying state is current."""

        if kind is WorkDeliveryKind.OWNER_INPUT:
            return state is WorkState.WAITING_FOR_OWNER
        if kind is WorkDeliveryKind.CHANGE_GATE:
            return True
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
            "Speak exactly the following owner question and nothing else. Do not add "
            "internal identifiers, explanations, meta commentary, or instructions. "
            "After speaking the question, stop and wait for the owner's response. "
            "Owner question: " + normalized_question
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

    @staticmethod
    def _delivery_gate_id(event_key: str) -> str | None:
        parts = str(event_key).split(":")
        if len(parts) != 4 or parts[0] != "change-gate":
            return None
        gate_id = parts[2].strip()
        if not gate_id.startswith("gate_"):
            return None
        return gate_id

    def _change_gate_spoken_question(self, gate_id: str) -> str:
        runtime = self._work_runtime
        if runtime is None or runtime.changes is None:
            raise RuntimeError("change-gate interaction requires EngineeringChange runtime")
        store = runtime.changes.store
        challenge = GateService(
            store,
            verify_owner=lambda *_: False,
        ).get(gate_id)
        if not isinstance(challenge, GateChallenge):
            raise RuntimeError("change-gate prompt requires one pending exact challenge")

        architecture = store.latest_artifact(challenge.change_id, "architecture")
        label = None
        if architecture is not None:
            label = _spoken_subject(
                architecture.payload.get("proposed_capability_id")
                or architecture.payload.get("proposed_package_id")
            )
        subject = label or "the engineering change"

        if challenge.kind is GateKind.ARCHITECTURE:
            return f"The architecture for {subject} is ready. Do you approve or reject it?"
        if challenge.kind is GateKind.ACCEPTANCE:
            return f"The verified change for {subject} is ready for acceptance. Do you approve or reject it?"
        if challenge.kind is GateKind.PROMOTION:
            return f"The verified change for {subject} is ready for promotion. Do you approve or reject it?"
        raise RuntimeError("unsupported engineering-change gate kind")
    async def _run_change_gate_interaction(
        self,
        *,
        gate_id: str,
        question: str,
    ) -> bool:
        """Open one bounded proactive conversation for an exact change gate."""

        runtime = self._work_runtime
        if runtime is None or runtime.changes is None:
            raise RuntimeError(
                "change-gate interaction requires EngineeringChange runtime"
            )

        normalized_question = " ".join(question.split())
        if not normalized_question:
            raise ValueError("change-gate question must not be empty")

        def session_tools(conversation: ConversationSession) -> list:
            work_tools = WorkAgentTools(
                runtime,
                conversation,
                bound_change_gate_id=gate_id,
                allow_capability_acquisition=False,
            )
            return [work_tools.decide_change_gate]

        def gate_resolved() -> bool:
            pending = GateService(
                runtime.changes.store,
                verify_owner=lambda *_: False,
            ).pending_gate_ids()
            return gate_id not in pending

        spoken_question = self._change_gate_spoken_question(gate_id)
        instructions = (
            "Speak exactly the following approval question and nothing else. Do not say "
            "gate IDs, change IDs, digests, JSON, tool names, or internal instructions. "
            "After speaking the question, stop and wait for the owner's response. "
            "Approval question: " + spoken_question
        )

        try:
            await self._run_one_session_owned(
                initial_instructions=instructions,
                initial_prompt_label="engineering change approval prompt",
                session_tool_factory=session_tools,
                completion_predicate=gate_resolved,
                completion_label=f"engineering change gate {gate_id}",
            )
        finally:
            self._cancel_timeout()
            self._active_end = None
            if not self._shutdown.is_set():
                self._state = VoiceRuntimeState.IDLE

        return gate_resolved()

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
            if delivery.kind is WorkDeliveryKind.CHANGE_GATE:
                gate_id = self._delivery_gate_id(delivery.event_key)
                pending = (
                    ()
                    if runtime.changes is None
                    else GateService(
                        runtime.changes.store,
                        verify_owner=lambda *_: False,
                    ).pending_gate_ids()
                )
                if gate_id is None or gate_id not in pending:
                    runtime.store.mark_delivery_delivered(delivery.delivery_id)
                    LOGGER.info(
                        "Obsolete engineering-change gate notification discarded | "
                        "delivery_id=%s | work_id=%s | gate_id=%s",
                        delivery.delivery_id,
                        delivery.work_id,
                        gate_id or "invalid",
                    )
                    await asyncio.sleep(0)
                    continue
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
                    elif delivery.kind is WorkDeliveryKind.CHANGE_GATE:
                        gate_id = self._delivery_gate_id(delivery.event_key)
                        if gate_id is None:
                            raise RuntimeError(
                                "engineering-change delivery has no exact gate identity"
                            )
                        answered = await self._run_change_gate_interaction(
                            gate_id=gate_id,
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
                                reason="change_gate_unanswered",
                            )
                            LOGGER.info(
                                "Engineering-change gate interaction ended without a "
                                "decision; durable retry scheduled | delivery_id=%s | "
                                "gate_id=%s | failed_attempts=%s | retry_in=%.1fs",
                                delivery.delivery_id,
                                gate_id,
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
                                "owner in one short, natural sentence using your "
                                "established JARVIS voice and style. Preserve the owner-relevant "
                                "outcome, blocker, question, and required owner action. "
                                "Do not mention prompts, models, tools, or internal routing. "
                                "Do not add facts. Notification: " + delivery_text
                            ),
                            label="background work notification",
                        )
                        spoken = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if isinstance(exc, TimeoutError) and delivery.kind in {
                        WorkDeliveryKind.PROGRESS,
                        WorkDeliveryKind.COMPLETION,
                    }:
                        spoken = True
                        LOGGER.warning(
                            "Background progress/completion speech timed out; "
                            "consuming once without replay | delivery_id=%s | "
                            "work_id=%s | kind=%s",
                            delivery.delivery_id,
                            delivery.work_id,
                            delivery.kind.value,
                        )
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
                            if self._shutdown.is_set():
                                return
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
        gicc_runtime = self._gicc_runtime
        if gicc_runtime is not None:
            gicc_runtime.start()
            LOGGER.info("GICC durable continuation reconciliation is active")
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
            if gicc_runtime is not None:
                await gicc_runtime.close()
            self._session_ready_for_inactivity = False
            self._user_is_speaking = False
            self._session_conversation = None
            self._agent_state = "unavailable"
            self._live_session = None
            if self._work_runtime is not None:
                self._work_runtime.set_interactive_brain_active(False)
            if self._work_runtime is not None:
                await self._work_runtime.aclose()
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
