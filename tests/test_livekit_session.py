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
from jarvis.voice.agent import INSTRUCTIONS
from jarvis.voice.livekit_session import (
    LiveKitConversationBridge,
    _create_realtime_model,
    _create_session_vad,
    _create_turn_handling,
    create_voice_session,
    require_google_api_key,
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


def test_gemini_api_key_is_required_only_for_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        require_google_api_key()
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        _create_realtime_model(JarvisConfig(realtime_provider="gemini"))


def test_gemini_model_disables_server_activity_detection(
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
            realtime_provider="gemini",
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
    assert activity.disabled is True


def test_gemini_session_uses_conservative_local_silero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_vad(**kwargs: Any) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("jarvis.voice.livekit_session.inference.VAD", fake_vad)

    vad = _create_session_vad(JarvisConfig(realtime_provider="gemini"))

    assert vad is sentinel
    assert captured == {
        "model": "silero",
        "min_speech_duration": 0.12,
        "min_silence_duration": 0.55,
        "prefix_padding_duration": 0.30,
        "max_buffered_speech": 60.0,
        "activation_threshold": 0.65,
    }
    assert _create_session_vad(JarvisConfig(realtime_provider="openai")) is None


def test_gemini_turn_handling_requires_vad_barge_in() -> None:
    handling = _create_turn_handling(JarvisConfig(realtime_provider="gemini"))

    assert handling["turn_detection"] == "vad"
    assert handling["interruption"] == {
        "enabled": True,
        "mode": "vad",
        "min_duration": 0.30,
        "false_interruption_timeout": 1.0,
        "resume_false_interruption": True,
    }
    assert handling["preemptive_generation"] == {"enabled": False}


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

    _create_realtime_model(JarvisConfig(realtime_provider="openai"))

    assert captured["turn_detection"].threshold == 0.8
