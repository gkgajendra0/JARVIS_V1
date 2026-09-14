from __future__ import annotations

from collections.abc import Callable
from typing import Any

from livekit.agents import ConversationItemAddedEvent, UserInputTranscribedEvent
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


def test_false_vad_activity_cannot_poison_next_real_user_generation() -> None:
    livekit = FakeAgentSession()
    conversation = ConversationSession(session_id="false-interruption-generation")
    conversation.start()
    bridge = LiveKitConversationBridge(
        livekit,  # type: ignore[arg-type]
        conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )

    phantom_activity = conversation.begin_user_activity()

    assert phantom_activity == 1
    assert conversation.user_utterance_generation == 0
    assert "agent_false_interruption" not in livekit.handlers

    real_activity = conversation.begin_user_activity()
    livekit.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="Jarvis, set volume to 40 percent.",
            is_final=True,
            item_id="volume-turn",
        ),
    )
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

    assert real_activity == 2
    assert len(bridge.conversation.turns) == 1
    turn = bridge.conversation.turns[0]
    assert turn.user_utterance_generation == 1
    assert turn.user_activity_epoch == real_activity
    assert bridge.conversation.user_utterance_generation == 1
