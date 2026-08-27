from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from livekit.agents import (
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    ErrorEvent,
)
from livekit.agents.llm import ChatMessage

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession, ConversationStatus
from jarvis.voice.livekit_session import (
    LiveKitConversationBridge,
    create_voice_session,
    require_openai_api_key,
)


class FakeAgentSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], None]] = {}

    def on(self, event: str, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        self.handlers[event] = callback
        return callback

    def emit(self, event: str, value: Any) -> None:
        self.handlers[event](value)


@dataclass
class FakeError:
    recoverable: bool

    def __str__(self) -> str:
        return "controlled test error"


def message(
    item_id: str,
    role: str,
    text: str,
    *,
    interrupted: bool = False,
) -> ChatMessage:
    return ChatMessage(
        id=item_id,
        role=role,
        content=[text],
        interrupted=interrupted,
    )


def active_bridge() -> tuple[FakeAgentSession, LiveKitConversationBridge]:
    livekit = FakeAgentSession()
    conversation = ConversationSession()
    conversation.start()
    bridge = LiveKitConversationBridge(
        livekit,  # type: ignore[arg-type]
        conversation,
        show_transcript=False,
    )
    return livekit, bridge


def test_committed_items_write_once_and_preserve_repeated_text() -> None:
    livekit, bridge = active_bridge()
    first = ConversationItemAddedEvent(item=message("one", "user", "repeat"))
    second = ConversationItemAddedEvent(item=message("two", "user", "repeat"))

    livekit.emit("conversation_item_added", first)
    livekit.emit("conversation_item_added", first)
    livekit.emit("conversation_item_added", second)

    assert [turn.text for turn in bridge.conversation.turns] == ["repeat", "repeat"]


def test_interrupted_assistant_item_is_marked_partial() -> None:
    livekit, bridge = active_bridge()
    event = ConversationItemAddedEvent(
        item=message("assistant-one", "assistant", "Partial answer", interrupted=True)
    )

    livekit.emit("conversation_item_added", event)

    assert bridge.conversation.turns[0].interrupted is True


def test_empty_and_unsupported_items_do_not_write_turns() -> None:
    livekit, bridge = active_bridge()
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("empty", "user", "   ")),
    )
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("system", "system", "ignored")),
    )

    assert bridge.conversation.turns == ()


def test_recoverable_error_keeps_session_active() -> None:
    livekit, bridge = active_bridge()
    livekit.emit("error", ErrorEvent(error=FakeError(True), source=object()))
    assert bridge.conversation.status is ConversationStatus.ACTIVE


def test_terminal_error_fails_and_close_preserves_failure() -> None:
    livekit, bridge = active_bridge()
    livekit.emit("error", ErrorEvent(error=FakeError(False), source=object()))
    livekit.emit("close", CloseEvent(reason=CloseReason.ERROR))
    assert bridge.conversation.status is ConversationStatus.FAILED


def test_close_without_error_closes_session() -> None:
    livekit, bridge = active_bridge()
    livekit.emit("close", CloseEvent(reason=CloseReason.USER_INITIATED))
    assert bridge.conversation.status is ConversationStatus.CLOSED


def test_api_key_is_required_before_session_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        require_openai_api_key()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_voice_session(JarvisConfig())
