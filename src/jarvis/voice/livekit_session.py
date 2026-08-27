"""LiveKit/OpenAI integration boundary for the Step-1 voice session."""

from __future__ import annotations

import logging
import os

from livekit.agents import (
    AgentSession,
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    ErrorEvent,
    TurnHandlingOptions,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import openai

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession

LOGGER = logging.getLogger(__name__)


def require_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required before starting voice mode")
    return api_key


class LiveKitConversationBridge:
    """Translate committed LiveKit items into canonical JARVIS turns."""

    def __init__(
        self,
        session: AgentSession,
        conversation: ConversationSession,
        *,
        show_transcript: bool,
    ) -> None:
        self.livekit_session = session
        self.conversation = conversation
        self._show_transcript = show_transcript
        self._seen_item_ids: set[str] = set()
        session.on("conversation_item_added", self._on_conversation_item_added)
        session.on("error", self._on_error)
        session.on("close", self._on_close)

    def _on_conversation_item_added(self, event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage) or item.id in self._seen_item_ids:
            return
        try:
            role = ConversationRole(item.role)
        except ValueError:
            return
        text = item.text_content.strip()
        if not text:
            return
        interrupted = bool(item.interrupted and role is ConversationRole.ASSISTANT)
        turn = self.conversation.accept_turn(role, text, interrupted=interrupted)
        self._seen_item_ids.add(item.id)
        if self._show_transcript:
            suffix = " [interrupted]" if turn.interrupted else ""
            LOGGER.info("%s: %s%s", turn.role.value, turn.text, suffix)

    def _on_error(self, event: ErrorEvent) -> None:
        summary = getattr(event.error, "label", type(event.error).__name__)
        if getattr(event.error, "recoverable", False):
            LOGGER.warning("Recoverable voice-session error: %s", summary)
            return
        LOGGER.error("Voice session failed: %s", summary)
        self.conversation.fail()

    def _on_close(self, event: CloseEvent) -> None:
        if event.error is not None or event.reason is CloseReason.ERROR:
            self.conversation.fail()
        else:
            self.conversation.close()


def create_voice_session(
    config: JarvisConfig,
) -> tuple[AgentSession, LiveKitConversationBridge]:
    api_key = require_openai_api_key()
    conversation = ConversationSession()
    livekit_session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=config.realtime_model,
            voice=config.realtime_voice,
            api_key=api_key,
        ),
        vad=None,
        turn_handling=TurnHandlingOptions(
            turn_detection=None,
            interruption={"enabled": True},
            preemptive_generation={"enabled": False},
        ),
    )
    bridge = LiveKitConversationBridge(
        livekit_session,
        conversation,
        show_transcript=config.show_transcript,
    )
    return livekit_session, bridge
