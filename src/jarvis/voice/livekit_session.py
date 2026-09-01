"""LiveKit/provider integration boundary for the Step-1 voice session."""

from __future__ import annotations

import logging
import os

from google.genai import types as google_types
from livekit.agents import (
    AgentSession,
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    ErrorEvent,
    TurnHandlingOptions,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import google, openai
from openai.types.beta.realtime.session import TurnDetection

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.agent import INSTRUCTIONS

LOGGER = logging.getLogger(__name__)


def require_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required before starting voice mode")
    return api_key


def require_google_api_key() -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is required before starting Gemini voice mode"
        )
    return api_key


def _create_realtime_model(config: JarvisConfig):
    if config.realtime_provider == "gemini":
        # Gemini 3.1 + the currently pinned LiveKit Google adapter must retain
        # provider-native activity/turn completion. The paired audio runtime
        # separately gates AEC-clean PCM with local Silero only while JARVIS is
        # speaking, so residual echo is filtered before Gemini's native VAD.
        return google.realtime.RealtimeModel(
            model=config.gemini_realtime_model,
            voice=config.gemini_realtime_voice,
            api_key=require_google_api_key(),
            instructions=INSTRUCTIONS,
            input_audio_transcription={},
            output_audio_transcription={},
            realtime_input_config=google_types.RealtimeInputConfig(
                automatic_activity_detection=google_types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=(
                        google_types.StartSensitivity.START_SENSITIVITY_LOW
                    ),
                    end_of_speech_sensitivity=(
                        google_types.EndSensitivity.END_SENSITIVITY_LOW
                    ),
                    prefix_padding_ms=300,
                    silence_duration_ms=800,
                )
            ),
        )

    return openai.realtime.RealtimeModel(
        model=config.realtime_model,
        voice=config.realtime_voice,
        api_key=require_openai_api_key(),
        input_audio_noise_reduction="far_field",
        turn_detection=TurnDetection(
            type="server_vad",
            threshold=0.8,
            prefix_padding_ms=300,
            silence_duration_ms=500,
            create_response=True,
            interrupt_response=True,
        ),
    )


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
    conversation = ConversationSession()
    livekit_session = AgentSession(
        llm=_create_realtime_model(config),
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
