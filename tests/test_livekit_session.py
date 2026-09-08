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
from jarvis.memory.live_context import LiveContext
from jarvis.voice.agent import INSTRUCTIONS
from jarvis.voice.livekit_session import (
    LiveKitConversationBridge,
    _create_realtime_model,
    create_voice_session,
)


class FakeAgentSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], None]] = {}

    def on(self, event: str, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        self.handlers[event] = callback
        return callback

    def emit(self, event: str, value: Any) -> None:
        self.handlers[event](value)


class RejectingConversation(ConversationSession):
    def accept_turn(self, *args: Any, **kwargs: Any):
        del args, kwargs
        raise RuntimeError("controlled canonical rejection")


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
        LiveContext(max_recent_turns=8),
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

    turns = bridge.conversation.turns
    assert [turn.text for turn in turns] == ["repeat", "repeat"]
    assert [turn.external_item_id for turn in turns] == ["one", "two"]
    assert all(turn.turn_id != turn.external_item_id for turn in turns)
    assert turns[0].turn_id != turns[1].turn_id
    assert bridge.live_context.recent_turns == turns


def test_accepted_turn_observer_receives_exact_canonical_turn() -> None:
    livekit, bridge = active_bridge()
    observed = []
    bridge.add_accepted_turn_observer(observed.append)

    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("one", "user", "canonical text")),
    )

    assert len(observed) == 1
    assert observed[0] is bridge.conversation.turns[0]
    assert observed[0] is bridge.live_context.recent_turns[0]


def test_observer_failure_cannot_reject_a_canonical_turn() -> None:
    livekit, bridge = active_bridge()

    def fail_observer(_turn) -> None:
        raise RuntimeError("controlled observer failure")

    bridge.add_accepted_turn_observer(fail_observer)

    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("one", "user", "still accepted")),
    )

    assert [turn.text for turn in bridge.conversation.turns] == ["still accepted"]


def test_live_context_updates_only_after_canonical_acceptance_succeeds() -> None:
    livekit = FakeAgentSession()
    conversation = RejectingConversation()
    conversation.start()
    live_context = LiveContext(max_recent_turns=4)
    LiveKitConversationBridge(
        livekit,  # type: ignore[arg-type]
        conversation,
        live_context,
        show_transcript=False,
    )
    event = ConversationItemAddedEvent(item=message("rejected", "user", "do not add"))

    with pytest.raises(RuntimeError, match="controlled canonical rejection"):
        livekit.emit("conversation_item_added", event)
    with pytest.raises(RuntimeError, match="controlled canonical rejection"):
        livekit.emit("conversation_item_added", event)

    assert live_context.recent_turns == ()


def test_interrupted_assistant_item_is_marked_partial() -> None:
    livekit, bridge = active_bridge()
    event = ConversationItemAddedEvent(
        item=message("assistant-one", "assistant", "Partial answer", interrupted=True)
    )

    livekit.emit("conversation_item_added", event)

    assert bridge.conversation.turns[0].interrupted is True
    assert bridge.live_context.recent_turns[0].interrupted is True


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
    assert bridge.live_context.recent_turns == ()


def test_recoverable_error_keeps_session_active() -> None:
    livekit, bridge = active_bridge()
    livekit.emit("error", ErrorEvent(error=FakeError(True), source=object()))
    assert bridge.conversation.status is ConversationStatus.ACTIVE


def test_terminal_error_fails_and_close_preserves_failure() -> None:
    livekit, bridge = active_bridge()
    livekit.emit("error", ErrorEvent(error=FakeError(False), source=object()))
    livekit.emit("close", CloseEvent(reason=CloseReason.ERROR))
    assert bridge.conversation.status is ConversationStatus.FAILED
    assert bridge.live_context.recent_turns == ()


def test_close_without_error_closes_session_and_disposes_live_context() -> None:
    livekit, bridge = active_bridge()
    closed: list[bool] = []
    bridge.add_close_observer(lambda: closed.append(True))
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("one", "user", "temporary context")),
    )
    assert len(bridge.live_context.recent_turns) == 1

    livekit.emit("close", CloseEvent(reason=CloseReason.USER_INITIATED))

    assert bridge.conversation.status is ConversationStatus.CLOSED
    assert bridge.live_context.recent_turns == ()
    assert closed == [True]


def test_api_key_is_required_before_session_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_voice_session(JarvisConfig())


def test_gemini_api_key_is_required_only_for_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        _create_realtime_model(JarvisConfig(ai_provider="gemini"))


def test_gemini_model_keeps_provider_native_activity_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_model(**kwargs: Any) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel", fake_model
    )

    model = _create_realtime_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-test",
            gemini_realtime_voice="Gacrux",
        )
    )

    assert model is sentinel
    assert captured["model"] == "gemini-test"
    assert captured["voice"] == "Gacrux"
    assert captured["api_key"] == "test-google-key"
    assert captured["instructions"] == INSTRUCTIONS
    assert captured["input_audio_transcription"] == {}
    assert captured["output_audio_transcription"] == {}
    activity = captured["realtime_input_config"].automatic_activity_detection
    assert activity.disabled is not True
    assert activity.start_of_speech_sensitivity == "START_SENSITIVITY_LOW"
    assert activity.end_of_speech_sensitivity == "END_SENSITIVITY_LOW"
    assert activity.prefix_padding_ms == 300
    assert activity.silence_duration_ms == 800


def test_openai_model_uses_stricter_vad_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_model(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.openai.realtime.RealtimeModel", fake_model
    )

    _create_realtime_model(JarvisConfig(ai_provider="openai"))

    assert captured["turn_detection"].threshold == 0.8
