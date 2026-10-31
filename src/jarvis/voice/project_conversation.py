"""Application-owned capture -> selected context -> ordinary model/tool cycle.

Normal native audio is not attached: it cannot guarantee this ordering. This
coordinator is shared by the isolated text path and a future qualified speech
adapter. No raw transcript observers or separate extraction request are used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.conversation import ConversationRole
from jarvis.memory.project_context import build_project_context
from jarvis.memory.project_conversation_recording import (
    RecordingRoute,
    RequiredConversationRecorder,
)
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import (
    ConversationEvent,
    PreparedProjectReply,
    ProjectSelection,
)
from jarvis.memory.project_routing import ProjectRouter, ProjectRoutingDecision
from jarvis.voice.project_memory_tools import ProjectMemoryTools


@dataclass(frozen=True)
class ProjectResponse:
    packet: PreparedProjectReply
    answer: str
    receipt: object
    announcement: str
    usage: tuple[dict, ...]


class ProjectConversationCoordinator:
    def __init__(self, access, *, source_clearance, personal_factory=None):
        self.access = access
        self.router = ProjectRouter(access)
        self.recorder = RequiredConversationRecorder(
            access.store,
            authority=access.authority,
            grant=access.grant,
            source_clearance=source_clearance,
        )
        self.personal_factory = personal_factory
        self._activity = 0
        self._request = None
        self._packet = None
        self._version = None
        self._authorize = lambda: False
        self._personal = None
        self._decision = None
        self._receipts = {}
        self._issued_responses = {}
        self._delivery_receipts = {}
        self._delivery_lock = asyncio.Lock()
        access._invalidators.append(self._control_invalidated)
        self.stage = "idle"

    def _control_invalidated(self, reason, project_id):
        self.invalidate(reason)
        if reason == "forget":
            self.recorder.clear_project(project_id)
            forgotten = [
                key
                for key, (reply, _) in self._issued_responses.items()
                if reply.packet.selection.project_id == project_id
            ]
            for key in forgotten:
                self._issued_responses.pop(key, None)
                self._delivery_receipts.pop(key, None)
            if self._personal is not None:
                self._personal.close()
            self._personal = None

    def invalidate(self, reason):
        if not reason:
            raise ValueError("invalidation reason required")
        self._activity += 1
        self._packet = None
        if self._personal is not None:
            self._personal.close()
            self._personal = None

    def _request_current(self, request_id, activity):
        return (
            self._request == request_id
            and self._activity == activity
            and self.access.current()
            and self._authorize() is True
        )

    def validate_current(self, packet):
        return (
            packet is self._packet
            and self._version
            == (self.access.local_revision, self.access.store.change_revision)
            and self._request_current(packet.request_id, self._packet_activity)
        )

    def _check(self, packet):
        if not self.validate_current(packet):
            raise PermissionError("project response invalidated")

    async def _build_packet(
        self, selection, *, request_id, extra_sources=(), personal=None, retrieval=()
    ):
        before = (self.access.local_revision, self.access.store.change_revision)
        # A project is the durable context boundary; a new thread must not hide
        # its recent originals. The same authorized scope and wire budget apply.
        snapshot = await self.access.snapshot(selection, project_wide=True)
        if before != (self.access.local_revision, self.access.store.change_revision):
            raise PermissionError("archive changed during context preparation")
        context, ids, tokens = build_project_context(
            snapshot,
            extra_sources=extra_sources,
            personal=personal,
            retrieval=retrieval,
        )
        digest = hashlib.sha256(context.encode()).hexdigest()
        packet = PreparedProjectReply(
            request_id, selection, ids, context, digest, tokens
        )
        self._packet, self._version = (
            packet,
            (self.access.local_revision, self.access.store.change_revision),
        )
        self._packet_activity = self._activity
        self._check(packet)
        return packet

    async def prepare_reply(
        self, conversation, turn, *, routing_receipt=None, authorize
    ):
        self.invalidate("new_request")
        self._request = str(uuid4())
        self._decision = None
        self._authorize = lambda: False
        self.stage = "authorizing"
        if not callable(authorize) or authorize() is not True:
            raise PermissionError("current release authorization required")
        self._authorize = authorize
        request_id, activity = self._request, self._activity
        self.stage = "routing"
        eligible = self.recorder._clearance(turn) is True
        if eligible:
            decision = routing_receipt or await self.router.resolve(conversation, turn)
        else:
            # Excluded source text must not leak through a project title/alias.
            catalog = await self.access.catalog()
            entry = next(
                (e for e in catalog.entries if e.selection == catalog.current), None
            )
            if entry is None:
                general = [
                    e for e in catalog.entries if e.title.casefold() == "general"
                ]
                if len(general) > 1:
                    raise PermissionError("ambiguous General workspace")
                entry = general[0] if general else None
            decision = ProjectRoutingDecision(
                "ready",
                entry.selection
                if entry
                else ProjectSelection(str(uuid4()), str(uuid4()), 0),
                entry.title if entry else "General",
                catalog.selection_revision,
                entry.archive_revision if entry else 0,
                create=entry is None,
            )
        if decision.status != "ready":
            raise ValueError(
                "project clarification required: " + ", ".join(decision.candidates)
            )
        await self.router.select(decision)
        if not self._request_current(request_id, activity):
            raise PermissionError("routing request changed")
        self._decision = decision
        snapshot = await self.access.snapshot(decision.selection)
        route = RecordingRoute(
            decision.selection, snapshot.archive_revision, request_id
        )
        if snapshot.retention_paused or not eligible:
            reason = (
                "retention_paused"
                if snapshot.retention_paused
                else "source_not_eligible"
            )
            await self.recorder.record_omission(
                conversation, turn, route, reason=reason
            )
            self.stage = reason
            raise PermissionError("original turn omitted; dependent generation blocked")
        self.stage = "recording"
        receipt = await self.recorder.record(conversation, turn, route)
        if not self._request_current(request_id, activity):
            raise PermissionError("recorded request changed")
        self._receipts[request_id] = receipt
        self._personal = (
            self.personal_factory(conversation) if self.personal_factory else None
        )
        self.stage = "retrieving"
        return await self._build_packet(decision.selection, request_id=request_id)

    async def _capture_tool(self, conversation, packet, name, phase, source_ids=()):
        # Only actual executed local tool metadata is journalled. Query/result
        # values stay in their admitted sources rather than model-fabricated text.
        snapshot = await self.access.snapshot(packet.selection)
        event = ConversationEvent(
            str(uuid4()),
            conversation.session_id,
            packet.request_id,
            "tool",
            json.dumps({"tool": name, "phase": phase, "source_ids": list(source_ids)}),
            datetime.now(UTC),
        )
        material = self.access.store.append_material(
            packet.selection, event, snapshot.archive_revision
        )
        issuer = self.access.authority
        issuer.register_source(self.access.grant, event.event_id, source=event)
        try:
            permit = issuer.issue_child(
                self.access.grant,
                HistoryActionBinding(
                    "admit",
                    event.event_id,
                    archive_digest(material),
                    targets=(
                        ("project", packet.selection.project_id),
                        ("thread", packet.selection.thread_id),
                    ),
                ),
            )
            await self.access.store.append_event(
                packet.selection,
                event,
                permit=permit,
                expected_revision=snapshot.archive_revision,
            )
        finally:
            issuer.release_source(self.access.grant, event.event_id)

    async def _validate_personal(self, personal):
        if (
            self._personal is not None
            and personal
            and personal.get("status") == "selected"
            and (
                not await self._personal._facts_current()
                or not await self._personal._validate()
            )
        ):
            self.invalidate("personal_context_changed")
            raise PermissionError("personal context invalidated")

    async def respond(self, conversation, turn, *, provider, authorize):
        packet = await self.prepare_reply(conversation, turn, authorize=authorize)
        request_id, activity = packet.request_id, self._activity
        tools = ProjectMemoryTools(
            self.access,
            selection=packet.selection,
            request_id=request_id,
            is_current=lambda: self._request_current(request_id, activity),
        )
        usage = []
        extras = ()
        personal = None
        personal_read = False
        retrieval = []
        for index in range(4):
            await self._validate_personal(personal)
            captured_session = self._personal

            async def dispatch_check(
                packet=packet, personal=personal, session=captured_session
            ):
                self._check(packet)
                if session is not self._personal:
                    raise PermissionError("personal session changed")
                await self._validate_personal(personal)
                self._check(packet)

            self.stage = "generating"
            available = tools.availability(
                personal_available=self._personal is not None and not personal_read,
                remaining_steps=4 - index,
            )
            telemetry = await provider.step(
                packet,
                question=turn.text,
                check=dispatch_check,
                operation_id=f"reply-{index}",
                available_tools=available,
            )
            usage.append(
                {
                    "operation": f"reply-{index}",
                    "usage": dict(telemetry.usage),
                    "observed": telemetry.usage_observed,
                    "latency_ms": telemetry.latency_ms,
                }
            )
            step = telemetry.parsed
            actions = sum(
                bool(v)
                for v in (step.search_query, step.source_ids, step.personal_requests)
            )
            if actions:
                if step.answer or actions != 1:
                    raise ValueError(
                        "one memory tool or answer per model step required"
                    )
                name = (
                    "search"
                    if step.search_query
                    else "read"
                    if step.source_ids
                    else "personal"
                )
                self.stage = "tool_" + name
                if not {
                    "search": available["search_available"],
                    "read": bool(available["read_source_ids"]),
                    "personal": available["personal_available"],
                }[name]:
                    raise PermissionError("memory tool unavailable for this request")
                await self._capture_tool(conversation, packet, name, "intent")
                if step.search_query:
                    result = await tools.search_conversation_memory(
                        packet.selection.project_id, step.search_query
                    )
                    extras = (*extras, *result.sources)
                    tool_status = result.status
                elif step.source_ids:
                    result = await tools.read_conversation_sources(
                        tuple(step.source_ids)
                    )
                    extras = (*extras, *result.sources)
                    tool_status = result.status
                else:
                    if personal_read:
                        raise PermissionError("personal read budget exhausted")
                    personal_read = True
                    personal = (
                        await self._personal.query_for_question(
                            [
                                r.model_dump(exclude_none=True)
                                for r in step.personal_requests
                            ]
                        )
                        if self._personal
                        else {"status": "unavailable", "facts": []}
                    )
                    tool_status = personal.get("status", "unavailable")
                retrieval.append(
                    {
                        "tool": name,
                        "status": tool_status,
                        "source_ids": []
                        if name == "personal"
                        else [s.event.event_id for s in result.sources],
                    }
                )
                if not self._request_current(request_id, activity):
                    raise PermissionError("tool request invalidated")
                await self._capture_tool(
                    conversation,
                    packet,
                    name,
                    "result",
                    tuple(s.event.event_id for s in extras),
                )
                packet = await self._build_packet(
                    packet.selection,
                    request_id=request_id,
                    extra_sources=extras,
                    personal=personal,
                    retrieval=retrieval,
                )
                continue
            if not step.answer.strip():
                raise ValueError("empty project answer")
            await self._validate_personal(personal)
            self._check(packet)
            self.stage = "answer_ready"
            response = ProjectResponse(
                packet,
                step.answer,
                self._receipts[request_id],
                self._decision.announcement,
                tuple(usage),
            )
            self._issued_responses[request_id] = (response, conversation.session_id)
            return response
        raise PermissionError("answer/tool continuation budget exhausted")

    def diagnostics(self):
        selection = self._decision.selection if self._decision else None
        return {
            "request_id": self._request,
            "stage": self.stage,
            "project_id": selection.project_id if selection else None,
            "thread_id": selection.thread_id if selection else None,
        }

    async def validate_for_release(self, response):
        self._check(response.packet)
        await self._validate_personal_from_packet(response.packet)
        self._check(response.packet)

    async def _validate_personal_from_packet(self, packet):
        personal = json.loads(packet.context).get("personal")
        await self._validate_personal(personal)

    async def record_assistant(
        self, conversation, response, *, delivered_text, interrupted=False
    ):
        async with self._delivery_lock:
            key = response.packet.request_id
            issued = self._issued_responses.get(key)
            if (
                issued is None
                or issued[0] is not response
                or issued[1] != conversation.session_id
            ):
                raise PermissionError(
                    "exact issued response and original conversation required"
                )
            previous = self._delivery_receipts.get(key)
            if previous is not None:
                if previous[:2] != (delivered_text, interrupted):
                    raise PermissionError("delivery callback changed")
                return previous[2]
            receipt = await self._record_assistant(
                conversation,
                response,
                delivered_text=delivered_text,
                interrupted=interrupted,
            )
            self._delivery_receipts[key] = (delivered_text, interrupted, receipt)
            if self._packet is response.packet:
                self.invalidate("delivery_finished")
            return receipt

    async def _record_assistant(
        self, conversation, response, *, delivered_text, interrupted=False
    ):
        if (
            not isinstance(delivered_text, str)
            or not delivered_text
            or not response.answer.startswith(delivered_text)
        ):
            raise ValueError("actual delivered answer prefix required")
        turn = conversation.accept_turn(
            ConversationRole.ASSISTANT,
            delivered_text,
            interrupted=interrupted or delivered_text != response.answer,
        )
        snapshot = await self.access.snapshot(response.packet.selection)
        route = RecordingRoute(
            response.packet.selection,
            snapshot.archive_revision,
            response.packet.request_id,
        )
        if snapshot.retention_paused or self.recorder._clearance(turn) is not True:
            return await self.recorder.record_omission(
                conversation,
                turn,
                route,
                reason="retention_paused"
                if snapshot.retention_paused
                else "source_not_eligible",
            )
        return await self.recorder.record(conversation, turn, route)
