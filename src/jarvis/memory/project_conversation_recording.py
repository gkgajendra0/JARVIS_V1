"""Required original-turn capture for the controlled project reply pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.authority.conversation_history import (
    ConversationHistoryAuthority,
    HistoryActionBinding,
)
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .project_conversation_store import ProjectConversationStore, archive_digest
from .project_conversations import (
    ConversationEvent,
    ConversationReceipt,
    ProjectSelection,
)


@dataclass(frozen=True, slots=True)
class RecordingRoute:
    selection: ProjectSelection
    expected_revision: int
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.selection, ProjectSelection):
            raise TypeError("immutable selection required")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("archive revision required")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request identity required")


class RequiredConversationRecorder:
    def __init__(
        self,
        store: ProjectConversationStore,
        *,
        authority: ConversationHistoryAuthority,
        grant,
        source_clearance: Callable[[ConversationTurn], bool],
    ) -> None:
        if not callable(source_clearance):
            raise TypeError("independent original-history source clearance required")
        store.bind_authority(authority)
        self._store, self._authority, self._grant = store, authority, grant
        self._clearance = source_clearance
        self._record_lock = asyncio.Lock()
        self._sources: dict[
            str, tuple[ConversationTurn, RecordingRoute, ConversationEvent]
        ] = {}

    async def record(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        routing_receipt: RecordingRoute,
    ) -> ConversationReceipt:
        # Source leases are shared by event identity. A duplicate callback must
        # never release the lease still needed by an overlapping write.
        async with self._record_lock:
            return await self._record(conversation, turn, routing_receipt)

    async def _record(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        routing_receipt: RecordingRoute,
    ) -> ConversationReceipt:
        if (
            not isinstance(conversation, ConversationSession)
            or not isinstance(turn, ConversationTurn)
            or not any(item is turn for item in conversation.turns)
        ):
            raise PermissionError("exact accepted canonical turn required")
        if not isinstance(routing_receipt, RecordingRoute):
            raise TypeError("frozen routing receipt required")
        if self._clearance(turn) is not True:
            raise PermissionError("original-history source clearance denied")
        existing = self._sources.get(turn.turn_id)
        if existing is not None:
            if (
                existing[0] is not turn
                or existing[1].selection != routing_receipt.selection
                or existing[1].request_id != routing_receipt.request_id
            ):
                raise PermissionError("accepted turn source or routing changed")
            event = existing[2]
        else:
            # Bound memory; exhaustion fails visibly rather than silently dropping history.
            if len(self._sources) >= 4096:
                raise PermissionError("recorder segment source limit reached")
            event = ConversationEvent(
                turn.turn_id,
                conversation.session_id,
                routing_receipt.request_id,
                turn.role.value,
                turn.text,
                turn.accepted_at,
                delivery="partial"
                if turn.role is ConversationRole.ASSISTANT and turn.interrupted
                else "complete",
            )
            self._sources[turn.turn_id] = (turn, routing_receipt, event)
        material = self._store.append_material(
            routing_receipt.selection, event, routing_receipt.expected_revision
        )
        self._authority.register_source(self._grant, event.event_id, source=event)
        try:
            permit = self._authority.issue_child(
                self._grant,
                HistoryActionBinding(
                    "admit",
                    event.event_id,
                    archive_digest(material),
                    targets=(
                        ("project", routing_receipt.selection.project_id),
                        ("thread", routing_receipt.selection.thread_id),
                    ),
                ),
            )
            return await self._store.append_event(
                routing_receipt.selection,
                event,
                permit=permit,
                expected_revision=routing_receipt.expected_revision,
            )
        finally:
            self._authority.release_source(self._grant, event.event_id)

    async def record_omission(self, conversation, turn, routing_receipt, *, reason):
        async with self._record_lock:
            return await self._record_omission(
                conversation, turn, routing_receipt, reason=reason
            )

    async def _record_omission(self, conversation, turn, routing_receipt, *, reason):
        import json

        if reason not in {"source_not_eligible", "retention_paused"}:
            raise ValueError("fixed omission reason required")
        if not any(item is turn for item in conversation.turns):
            raise PermissionError("accepted omission source required")
        event = ConversationEvent(
            turn.turn_id,
            conversation.session_id,
            routing_receipt.request_id,
            "tool",
            json.dumps(
                {
                    "capture": "omitted",
                    "reason": reason,
                    "source_role": turn.role.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            turn.accepted_at,
            delivery="failed",
        )
        material = self._store.append_material(
            routing_receipt.selection, event, routing_receipt.expected_revision
        )
        self._authority.register_source(self._grant, event.event_id, source=event)
        try:
            permit = self._authority.issue_child(
                self._grant,
                HistoryActionBinding(
                    "admit",
                    event.event_id,
                    archive_digest(material),
                    targets=(
                        ("project", routing_receipt.selection.project_id),
                        ("thread", routing_receipt.selection.thread_id),
                    ),
                ),
            )
            from dataclasses import replace

            receipt = await self._store.append_event(
                routing_receipt.selection,
                event,
                permit=permit,
                expected_revision=routing_receipt.expected_revision,
            )
            return replace(receipt, status="omitted")
        finally:
            self._authority.release_source(self._grant, event.event_id)

    def clear_project(self, project_id):
        self._sources = {
            key: value
            for key, value in self._sources.items()
            if value[1].selection.project_id != project_id
        }
