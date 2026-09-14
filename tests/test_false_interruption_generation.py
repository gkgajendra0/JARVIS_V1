from __future__ import annotations

from collections.abc import Callable
from typing import Any

from livekit.agents import AgentFalseInterruptionEvent, ConversationItemAddedEvent
from livekit.agents.llm import ChatMessage

from jarvis.conversation import ConversationSession
from jarvis.memory.live_context import LiveContext
from jarvis.voice.livekit_session import LiveKitConversationBridge


class FakeAgentSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], None]] = {}

    def on(self, event: str, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        self.handlers[event] = callback
        return callback

    def emit(self, event: str, value: Any) -> None:
        self.handlers[event](value)


def test_false_interruption_retires_phantom_generation_before_real_user_turn() -> None:
    livekit = FakeAgentSession()
    conversation = ConversationSession(session_id="false-interruption-generation")
    conversation.start()
    bridge = LiveKitConversationBridge(
        livekit,  # type: ignore[arg-type]
        conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )

    phantom_generation = conversation.begin_user_utterance()

    assert "agent_false_interruption" in livekit.handlers
    livekit.emit(
        "agent_false_interruption",
        AgentFalseInterruptionEvent(resumed=False),
    )

    real_generation = conversation.begin_user_utterance()
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(
                id="volume-turn",
                role="user",
                content=["Jarvis, set volume to 40 percent."],
            )
        ),
    )

    assert phantom_generation == 1
    assert real_generation == 2
    assert len(bridge.conversation.turns) == 1
    assert bridge.conversation.turns[0].user_utterance_generation == real_generation
