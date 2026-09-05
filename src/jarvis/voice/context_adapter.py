"""Translate governed JARVIS context packets into LiveKit chat context."""

from __future__ import annotations

from livekit.agents import ChatContext

from jarvis.conversation import ConversationRole
from jarvis.memory.context import ContextItem, ContextItemKind, ContextPacket

_STATE_KINDS = frozenset(
    {
        ContextItemKind.UNRESOLVED_WORK,
        ContextItemKind.ACTIVE_GOAL,
        ContextItemKind.ACTIVE_TOPIC,
        ContextItemKind.ENTITY,
        ContextItemKind.INTERACTION_CONTEXT,
    }
)


def context_packet_to_livekit(packet: ContextPacket) -> ChatContext:
    """Build a fresh ordinary-message context without mutating provider state."""

    if not isinstance(packet, ContextPacket):
        raise TypeError("packet must be a ContextPacket")

    chat_ctx = ChatContext()
    state_items = [item for item in packet.items if item.kind in _STATE_KINDS]
    recent_items = [
        item for item in packet.items if item.kind is ContextItemKind.RECENT_TURN
    ]
    current_items = [
        item for item in packet.items if item.kind is ContextItemKind.CURRENT_TURN
    ]

    if len(current_items) > 1:
        raise ValueError("context packet contains more than one current turn")

    for item in state_items:
        _add_item(chat_ctx, item, role=ConversationRole.ASSISTANT)

    # ContextAssembler considers recent turns newest-first for budget priority.
    # Providers need ordinary conversation history in chronological order.
    for item in reversed(recent_items):
        _add_item(chat_ctx, item, role=_required_turn_role(item))

    if current_items:
        current = current_items[0]
        _add_item(chat_ctx, current, role=_required_turn_role(current))

    return chat_ctx


def _required_turn_role(item: ContextItem) -> ConversationRole:
    if item.role is None:
        raise ValueError(f"{item.kind.value} context item is missing its turn role")
    return item.role


def _add_item(
    chat_ctx: ChatContext,
    item: ContextItem,
    *,
    role: ConversationRole,
) -> None:
    extra: dict[str, str] = {"jarvis_context_kind": item.kind.value}
    if item.source_turn_id is not None:
        extra["jarvis_source_turn_id"] = item.source_turn_id
    if item.source_ref is not None:
        extra["jarvis_source_ref"] = item.source_ref

    chat_ctx.add_message(
        role=role.value,
        content=item.text,
        interrupted=item.interrupted if role is ConversationRole.ASSISTANT else False,
        extra=extra,
    )
