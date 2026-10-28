"""Bounded Gemini transport handoff owned by the existing voice controller."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
from collections import deque
from uuid import uuid4
from weakref import WeakSet

from livekit.agents import Agent, TurnHandlingOptions
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
from jarvis.provider_resilience import (
    ProviderFailureKind,
    _error_chain,
    classify_provider_failure,
)
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission
from jarvis.voice.gemini_live_model import ControlledGeminiLiveModel
from jarvis.voice.gemini_transport import GeminiTransportState
from jarvis.voice.livekit_session import (
    _create_realtime_model,
    create_user_activity_vad,
)

LOGGER = logging.getLogger(__name__)


def _fresh_session_failure(error):
    # Only the explicit Live transport faults qualify; generic policy violations
    # and model/authentication errors must retain terminal handling.
    chain = _error_chain(error)
    coded = [item for item in chain if getattr(item, "code", None) is not None]
    for item in coded or chain:
        text = str(item).casefold()
        code = getattr(item, "code", None)
        internal = code == 1011 or (code is None and re.search(r"\b1011\b", text))
        collision = code == 1008 or (code is None and re.search(r"\b1008\b", text))
        if internal and "internal error" in text:
            return True
        if collision and (
            "bidigeneratecontent session is already connected to an existing client"
            in text
        ):
            return True
    return False


class _TransportAgent(Agent):
    def __init__(self, *, previous, model, context, ready):
        controlled = isinstance(
            getattr(model, "inner", None), ControlledGeminiLiveModel
        )
        options = {}
        if controlled:
            options = {
                "vad": create_user_activity_vad(),
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
        self._session_recoveries = 0
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

    def _controlled_idle(self, pending_input=None):
        inner = getattr(self.current_model, "inner", None)
        return not isinstance(inner, ControlledGeminiLiveModel) or all(
            (s.connection_idle if s is pending_input else s.idle)
            for s in inner.sessions
        )

    async def _before_paid_demand(self, source):
        if not await self._authorized() or not source.connection_idle:
            return False
        if self.task is not None and not self.task.done():
            await asyncio.shield(self.task)
            if not source.model.state.current:
                return False
        self._recovery_demand = True
        # A separate shielded owner survives retirement/cancellation of the old
        # Paid sender while public update_agent installs Free. No new grant.
        self.task = asyncio.create_task(
            self.maybe_recover_free(pending_input=source),
            name="jarvis-gemini-demand-selection",
        )
        switched = await asyncio.shield(self.task)
        return not switched and source.model.state.current

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
            diagnostic = getattr(self.runtime, "live_diagnostics", None)
            if (
                diagnostic is not None
                and diagnostic.plan.scope == "whole_app_diagnostic"
                and self.agent is not None
                and (self.task is None or self.task.done())
            ):
                self.task = asyncio.create_task(
                    diagnostic.inject_next(self), name="jarvis-explicit-live-diagnostic"
                )
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
        if (
            not self._closed
            and not self._pending_tools
            and self._session_recoveries == 0
            and (self.task is None or self.task.done())
            and _fresh_session_failure(event.error)
        ):
            self._session_recoveries += 1
            event.error.recoverable = True
            self._handled_events.append(event)
            self.task = asyncio.create_task(
                self._recover_fresh_session(), name="jarvis-gemini-fresh-session"
            )
            return True
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

    async def _recover_fresh_session(self):
        continued = False
        try:
            async with self._lock:
                if self._pending_tools or not await self._authorized():
                    self.last_reason = "fresh_session_authority_or_tools_denied"
                else:
                    # Freeze old audio/events and fully close physical SDK sessions.
                    # Reusing a resumption handle can collide with Google's old client.
                    old = self.current_model
                    old.state.ready = False
                    old.state.active = False
                    self._retired.add(old)
                    if self.input is not None:
                        self.input.set_transport_enabled(False)
                    if self.output is not None:
                        self.output.clear_buffer()

                    async def close_old_transport():
                        await asyncio.gather(*(s.aclose() for s in old.sessions))
                        await old.aclose()

                    await asyncio.wait_for(close_old_transport(), timeout=3.0)
                    if not self._pending_tools and await self._authorized():
                        continued = await self._switch(
                            self.current_target, continue_request=False
                        )
                        if continued:
                            self.last_reason = "fresh_session_ready_waiting_for_user"
                            LOGGER.info(
                                "Gemini fresh voice session ready; accepted context restored; "
                                "waiting for new user speech; automatic request replay disabled"
                            )
        except Exception:  # noqa: BLE001 - recovery must fail closed without provider details
            self.last_reason = "fresh_session_recovery_failed"
        if not continued:
            LOGGER.warning(
                "Gemini fresh session recovery unavailable; closing voice session"
            )
            await self.session.aclose()

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

    def _context_for_replay(self):
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
        return context

    async def _switch(self, target, *, continue_request, pending_input=None):
        if self.agent is None or not await self._authorized():
            return False
        context = self._context_for_replay()
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
        pending_frames = (
            pending_input.take_pending_audio() if pending_input is not None else ()
        )
        if pending_frames:
            can_continue = False
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
            context_for_replay=self._context_for_replay,
            before_demand=self._before_paid_demand,
        )
        if target.credential_ref == gemini_credential_ref("paid") and controlled:

            async def controlled_source_current():
                await state.require_context()
                return True

            from jarvis.voice.gemini_operational_budget import rebind_live_admission

            async def original_and_current():
                await self.paid_admission.require_authority()
                return await controlled_source_current()

            state.controlled_admission = rebind_live_admission(
                self.paid_admission, authorize=original_and_current
            )
        from jarvis.voice.gemini_automatic_fallback import AutomaticLiveAdmission

        if (
            target.credential_ref == gemini_credential_ref("paid")
            and type(self.paid_admission) is AutomaticLiveAdmission
        ):
            await self.paid_admission.require_authority()
            state.automatic_admission = self.paid_admission
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
            # Preserve the bounded current PCM before enabling later live frames.
            if pending_frames:
                for frame in pending_frames:
                    model.sessions[-1].push_audio(frame)
            if self.input is not None:
                self.input.set_transport_enabled(True)
            if can_continue:
                # Operational setup already carries accepted instructions/history;
                # a per-response override would be an unadmitted extra send.
                from jarvis.voice.gemini_operational_budget import (
                    OperationalLiveAdmission,
                )

                overrides = (
                    {}
                    if type(self.paid_admission)
                    in {OperationalLiveAdmission, AutomaticLiveAdmission}
                    else {
                        "instructions": "Continue the latest accepted user request. Do not repeat an already spoken answer or execute an action from earlier history."
                    }
                )
                self.session.generate_reply(
                    allow_interruptions=True, input_modality="text", **overrides
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

    async def maybe_recover_free(self, *, pending_input=None):
        async with self._lock:
            if (
                self.current_target.credential_ref != gemini_credential_ref("paid")
                or self._pending_tools
                or (self._user_speaking and pending_input is None)
                or self._output_speaking
                or not self._controlled_idle(pending_input)
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
            if not await self._switch(
                selection.target,
                continue_request=pending_input is not None,
                pending_input=pending_input,
            ):
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
