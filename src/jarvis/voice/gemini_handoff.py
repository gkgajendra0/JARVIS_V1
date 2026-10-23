"""Bounded Gemini transport handoff owned by the existing voice controller."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections import deque
from uuid import uuid4
from weakref import WeakSet

from livekit.agents import Agent, TurnHandlingOptions, inference
from livekit.agents.llm import ChatMessage

from jarvis.ai_provider import gemini_credential_ref
from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.model_routing.gemini import gemini_paid_fallback_allowed
from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    ScopedRoutingRequest,
)
from jarvis.model_routing.router import RoutingUnavailableError
from jarvis.provider_resilience import ProviderFailureKind, classify_provider_failure
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission
from jarvis.voice.gemini_live_model import ControlledGeminiLiveModel
from jarvis.voice.gemini_transport import GeminiTransportState
from jarvis.voice.livekit_session import _create_realtime_model


class _TransportAgent(Agent):
    def __init__(self, *, previous, model, context, ready):
        controlled = isinstance(
            getattr(model, "inner", None), ControlledGeminiLiveModel
        )
        options = {}
        if controlled:
            options = {
                "vad": inference.VAD(model="silero"),
                "turn_handling": TurnHandlingOptions(
                    turn_detection="vad",
                    endpointing={"mode": "fixed", "min_delay": 0.8, "max_delay": 3.0},
                    interruption={"enabled": True},
                    preemptive_generation={"enabled": False},
                ),
            }
        super().__init__(
            **options,
            instructions=previous.instructions,
            tools=previous.tools,
            llm=model,
            chat_ctx=context,
        )
        self._transport_ready = ready

    async def on_enter(self):
        self._transport_ready.set()


class GeminiLiveHandoff:
    def __init__(
        self,
        *,
        config,
        routing_runtime,
        session,
        bridge,
        current_model,
        guard,
        model_factory=_create_realtime_model,
        paid_admission=None,
        setup_timeout=10,
    ):
        self.config = config
        self.runtime = routing_runtime
        self.session = session
        self.bridge = bridge
        self.current_model = current_model
        self.guard = guard
        self.model_factory = model_factory
        self.paid_admission = paid_admission
        self.setup_timeout = setup_timeout
        self.router = routing_runtime.router_for(
            "voice.live", config.gemini_realtime_model
        )
        self.current_target = next(
            t
            for t in self.router.target_registry.all()
            if t.credential_ref == gemini_credential_ref("free")
        )
        self.agent = None
        self.input = None
        self.output = None
        self.task = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._retired = WeakSet()
        self._handled_events = deque(maxlen=32)
        self._pending_tools = set()
        self._completed_tools = False
        self._tool_receipts = deque(maxlen=32)
        self._tool_sources = {}
        self._user_speaking = False
        self._output_speaking = False
        self._output_delivered = False
        self._paid_visits = 0
        self._recovery_demand = False
        self._recovery_lease = None
        self.last_reason = "ready"
        bridge.bind_transport_error_handler(self.try_handle_event)
        bridge.add_accepted_turn_observer(self._accepted_turn)
        session.on("user_state_changed", self._user_state)
        session.on("agent_state_changed", self._agent_state)
        session.on("tool_execution_updated", self._tool_state)
        session.on("function_tools_executed", self._tools_finished)

    def bind_agent(self, agent):
        self.agent = agent

    def bind_io(self, audio_input, audio_output):
        self.input = audio_input
        self.output = audio_output
        self.current_model.state.output_sample_rate = getattr(
            audio_output, "sample_rate", None
        )

    def _user_state(self, event):
        self._user_speaking = event.new_state == "speaking"
        if (
            self._user_speaking
            and self.current_target.credential_ref == gemini_credential_ref("paid")
        ):
            self._recovery_demand = True
        self._schedule_free_recovery()

    def _agent_state(self, event):
        self._output_speaking = event.new_state == "speaking"
        self._schedule_free_recovery()

    def _controlled_idle(self):
        inner = getattr(self.current_model, "inner", None)
        return not isinstance(inner, ControlledGeminiLiveModel) or all(
            s.idle for s in inner.sessions
        )

    def _schedule_free_recovery(self):
        if (
            not self._closed
            and self._recovery_demand
            and not self._user_speaking
            and not self._output_speaking
            and not self._pending_tools
            and self._controlled_idle()
            and (self.task is None or self.task.done())
        ):
            self.task = asyncio.create_task(
                self.maybe_recover_free(), name="jarvis-gemini-free-recovery"
            )

    def _tool_state(self, event):
        update = event.update
        if update.type == "tool_call_started":
            self._pending_tools.add(update.function_call.call_id)
            user = next(
                (
                    t
                    for t in reversed(self.bridge.conversation.turns)
                    if t.role is ConversationRole.USER
                ),
                None,
            )
            if user is not None:
                self._tool_sources[update.function_call.call_id] = user.turn_id
        elif update.type == "tool_call_ended":
            self._pending_tools.discard(update.call_id)
            self._completed_tools = True

    def _tools_finished(self, event):
        self._completed_tools = True
        for call, result in event.zipped():
            self._pending_tools.discard(call.call_id)
            source = self._tool_sources.pop(call.call_id, None)
            if source is not None:
                self._tool_receipts.append(
                    {
                        "source_turn_id": source,
                        "call_id": call.call_id[:256],
                        "tool_name": call.name[:128],
                        "invocation_returned": True,
                        "is_error": bool(result.is_error),
                        "effect_details": "Use the canonical capability or Work owner; do not repeat this invocation.",
                    }
                )

    def note_output_delivered(self):
        self._output_delivered = True

    def _accepted_turn(self, turn):
        if turn.role is ConversationRole.USER:
            self._completed_tools = False
            self._output_delivered = False
        elif (
            turn.role is ConversationRole.ASSISTANT
            and self._recovery_lease is not None
            and not turn.interrupted
        ):
            self.runtime.store.complete_free_recovery(
                self._recovery_lease, now_epoch=float(self.runtime.clock())
            )
            self._recovery_lease = None
            self._paid_visits = 0

    async def _authorized(self):
        if (
            self._closed
            or self.bridge.conversation.status is not ConversationStatus.ACTIVE
        ):
            return False
        try:
            value = self.guard()
            if inspect.isawaitable(value):
                value = await value
        except Exception:  # noqa: BLE001 - continuity errors must deny without raw detail
            self.last_reason = "continuity_unavailable"
            return False
        return (
            value is True
            and not self._closed
            and self.bridge.conversation.status is ConversationStatus.ACTIVE
        )

    def try_handle_event(self, event):
        if any(previous is event for previous in self._handled_events):
            return True
        if getattr(event, "source", None) in self._retired:
            event.error.recoverable = True
            return True
        if getattr(event, "source", None) is not self.current_model:
            return False
        failure = classify_provider_failure(event.error, provider="gemini")
        if self.current_target.credential_ref == gemini_credential_ref(
            "paid"
        ) and failure.kind in {
            ProviderFailureKind.BALANCE_EXHAUSTED,
            ProviderFailureKind.AUTHENTICATION_FAILED,
        }:
            self.runtime.store.disable_paid_credential(
                failure=failure, now_epoch=float(self.runtime.clock())
            )
        if (
            self._closed
            or self.paid_admission is None
            or self._pending_tools
            or not gemini_paid_fallback_allowed(
                failure, source_target=self.current_target
            )
        ):
            return False
        event.error.recoverable = True
        self._handled_events.append(event)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(
                self._handle_event_failure(failure), name="jarvis-gemini-handoff"
            )
        return True

    async def _handle_event_failure(self, failure):
        try:
            continued = await self.handle_failure(failure)
        except Exception:  # noqa: BLE001 - terminal event ownership must always close safely
            self.last_reason = "handoff_unavailable"
            continued = False
        if not continued:
            await self.session.aclose()

    def _request(self):
        return ScopedRoutingRequest(
            routing_request_id=f"live:{self.bridge.conversation.session_id}:{uuid4()}",
            scope_kind="voice",
            scope_id=self.bridge.conversation.session_id,
            task_kind="voice.live",
            strategy_key="engineering_stage",
            strategy_version=1,
            required_capabilities=("realtime_voice", "tool_calling"),
            privacy_class=PrivacyClass.STANDARD,
            locality_requirement=LocalityRequirement.ANY,
            estimated_context_tokens=0,
            evidence_size_class=EvidenceSizeClass.SMALL,
            recent_progress_signals=(),
            recent_failure_signals=(),
            latency_preference="realtime",
            cost_preference="low",
        )

    async def handle_failure(self, failure):
        async with self._lock:
            if (
                self._closed
                or self._pending_tools
                or not gemini_paid_fallback_allowed(
                    failure, source_target=self.current_target
                )
            ):
                return False
            self.runtime.store.record_pressure(
                target=self.current_target,
                failure=failure,
                config=self.runtime.config,
                now_epoch=float(self.runtime.clock()),
            )
            if (
                self.paid_admission is None
                or self._paid_visits >= 1
                or not await self._authorized()
            ):
                return False
            try:
                selection = self.router.route(self._request())
            except RoutingUnavailableError:
                self.last_reason = "no_eligible_live_target"
                return False
            if selection.target.credential_ref != gemini_credential_ref("paid"):
                return False
            self._paid_visits += 1
            return await self._switch(selection.target, continue_request=True)

    async def _switch(self, target, *, continue_request):
        if self.agent is None or not await self._authorized():
            return False
        context = self.bridge.project_accepted_context()
        current_turns = {t.turn_id for t in self.bridge.live_context.recent_turns}
        for receipt in self._tool_receipts:
            if receipt["source_turn_id"] in current_turns:
                identity = hashlib.sha256(
                    (receipt["source_turn_id"] + receipt["call_id"]).encode()
                ).hexdigest()
                context.items.append(
                    ChatMessage(
                        id=f"jarvis-tool:{identity}",
                        role="assistant",
                        content=[
                            "Completed tool invocation receipt (data, not an instruction): "
                            + json.dumps(receipt, ensure_ascii=False, sort_keys=True)
                        ],
                    )
                )
        self.bridge.register_restored_context(context)
        latest = (
            self.bridge.conversation.turns[-1]
            if self.bridge.conversation.turns
            else None
        )
        can_continue = (
            continue_request
            and latest is not None
            and latest.role is ConversationRole.USER
            and not self._pending_tools
            and not self._completed_tools
            and not self._output_delivered
            and not self._output_speaking
            and not self._user_speaking
        )
        budget = None
        controlled = isinstance(self.paid_admission, ControlledLiveAdmission)
        if target.credential_ref == gemini_credential_ref("paid") and not controlled:
            try:
                budget = self.paid_admission.reserve_transport(
                    target=target,
                    context=context,
                    instructions=self.agent.instructions,
                    tools=self.agent.tools,
                )
            except (ValueError, RuntimeError):
                self.last_reason = "paid_live_admission_unavailable"
                return False
        if not await self._authorized():
            if budget is not None:
                budget.cancel_unsent()
            return False
        epoch = self.bridge.begin_transport_handoff()
        if self.input is not None:
            self.input.set_transport_enabled(False)
        if self.output is not None:
            self.output.clear_buffer()
        old_model = self.current_model
        self._retired.add(old_model)
        old_model.retire()
        state = GeminiTransportState(
            epoch=epoch,
            current_epoch=lambda: self.bridge.transport_epoch,
            authorize=self._authorized,
            budget=budget,
            ready=False,
            output_sample_rate=getattr(self.output, "sample_rate", None),
            restored_ids=frozenset(item.id for item in context.items),
            on_idle=self._schedule_free_recovery,
        )
        if target.credential_ref == gemini_credential_ref("paid") and controlled:

            async def controlled_source_current():
                await state.require_context()
                return True

            state.controlled_admission = ControlledLiveAdmission(
                self.runtime,
                session_id=self.bridge.conversation.session_id,
                authorize=controlled_source_current,
                contract=self.paid_admission.contract,
            )
        try:
            model = self.model_factory(
                self.config, target=target, transport_state=state
            )
            ready = asyncio.Event()
            agent = _TransportAgent(
                previous=self.agent, model=model, context=context, ready=ready
            )
            self.current_model = model
            self.current_target = target
            self.session.update_agent(agent)
            await asyncio.wait_for(ready.wait(), self.setup_timeout)
            if not await self._authorized():
                model.retire()
                return False
            self.agent = agent
            self.bridge.finish_transport_handoff(epoch)
            state.ready = True
            if self.input is not None:
                self.input.set_transport_enabled(True)
            if can_continue:
                self.session.generate_reply(
                    instructions="Continue the latest accepted user request. Do not repeat an already spoken answer or execute an action from earlier history.",
                    allow_interruptions=True,
                    input_modality="text",
                )
            if target.credential_ref == gemini_credential_ref("free"):
                self._recovery_demand = False
            self.last_reason = "switched"
            return True
        except (TimeoutError, RuntimeError, ValueError):
            state.active = False
            if budget is not None:
                budget.close()
            self.last_reason = "handoff_unavailable"
            return False

    async def maybe_recover_free(self):
        async with self._lock:
            if (
                self.current_target.credential_ref != gemini_credential_ref("paid")
                or self._pending_tools
                or self._user_speaking
                or self._output_speaking
                or not self._controlled_idle()
                or not await self._authorized()
            ):
                return False
            try:
                selection = self.router.route(self._request())
            except RoutingUnavailableError:
                self.last_reason = "no_eligible_live_target"
                return False
            if selection.target.credential_ref != gemini_credential_ref("free"):
                return False
            lease = self.runtime.store.claim_free_recovery(
                target_id=selection.target.target_id,
                operation_id=selection.request.routing_request_id,
                now_epoch=float(self.runtime.clock()),
                lease_seconds=60,
            )
            if lease is None:
                return False
            if not self.runtime.store.start_free_recovery(
                lease, now_epoch=float(self.runtime.clock())
            ):
                self.runtime.store.release_free_recovery(lease)
                return False
            self._recovery_lease = lease
            self._paid_visits = 0
            if not await self._switch(selection.target, continue_request=False):
                self.runtime.store.release_free_recovery(lease)
                self._recovery_lease = None
                return False
            return True

    def close(self):
        self._closed = True
        self.current_model.retire()
        if self._recovery_lease is not None:
            self.runtime.store.release_free_recovery(self._recovery_lease)
            self._recovery_lease = None
        if (
            self.task is not None
            and self.task is not asyncio.current_task()
            and not self.task.done()
        ):
            self.task.cancel()
