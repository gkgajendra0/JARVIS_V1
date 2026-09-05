from __future__ import annotations

from datetime import UTC, datetime

import pytest
from livekit.agents.llm import ChatMessage

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.context import ContextAssembler, Utf8ByteBudgetEstimator
from jarvis.memory.live_context import LiveContext
from jarvis.voice.context_adapter import context_packet_to_livekit


def _turn(
    turn_id: str,
    role: ConversationRole,
    text: str,
    *,
    interrupted: bool = False,
) -> ConversationTurn:
    return ConversationTurn(
        role=role,
        text=text,
        interrupted=interrupted,
        turn_id=turn_id,
        accepted_at=datetime(2026, 9, 5, 7, 30, tzinfo=UTC),
    )


def test_livekit_translation_uses_ordinary_messages_and_chronological_turns() -> None:
    live = LiveContext(max_recent_turns=4)
    oldest = _turn("turn-1", ConversationRole.USER, "oldest")
    interrupted = _turn(
        "turn-2",
        ConversationRole.ASSISTANT,
        "partial",
        interrupted=True,
    )
    current = _turn("turn-3", ConversationRole.USER, "current")
    for turn in (oldest, interrupted, current):
        live.observe_turn(turn)

    live.set_active_goal("finish Phase 4.2", source_turn_id="turn-3")
    live.set_entity("camera", "Pocket 3", source_ref="runtime:vision")
    packet = ContextAssembler(
        estimator=Utf8ByteBudgetEstimator(framing_overhead_units=0),
        max_units=10_000,
    ).assemble(live.snapshot(), current_turn=current)

    chat_ctx = context_packet_to_livekit(packet)
    messages = chat_ctx.messages()

    assert all(isinstance(item, ChatMessage) for item in chat_ctx.items)
    assert [message.role for message in messages] == [
        "assistant",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert [message.text_content for message in messages] == [
        "Active goal: finish Phase 4.2",
        "Entity [camera]: Pocket 3",
        "oldest",
        "partial",
        "current",
    ]
    assert all(message.role not in {"system", "developer"} for message in messages)
    assert messages[3].interrupted is True
    assert messages[0].extra["jarvis_source_turn_id"] == "turn-3"
    assert messages[1].extra["jarvis_source_ref"] == "runtime:vision"


def test_translation_does_not_mutate_packet_or_create_provider_ids_from_jarvis_ids() -> None:
    live = LiveContext(max_recent_turns=1)
    current = _turn("canonical-turn", ConversationRole.USER, "hello")
    live.observe_turn(current)
    packet = ContextAssembler(
        estimator=Utf8ByteBudgetEstimator(framing_overhead_units=0),
        max_units=100,
    ).assemble(live.snapshot(), current_turn=current)

    before = packet.items
    chat_ctx = context_packet_to_livekit(packet)
    message = chat_ctx.messages()[0]

    assert packet.items == before
    assert message.id != "canonical-turn"
    assert message.extra["jarvis_source_turn_id"] == "canonical-turn"


def test_translation_rejects_invalid_packet_type() -> None:
    with pytest.raises(TypeError, match="ContextPacket"):
        context_packet_to_livekit(object())  # type: ignore[arg-type]
