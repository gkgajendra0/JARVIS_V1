"""LiveKit/provider integration boundary for the Step-1 voice session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as google_types
from livekit.agents import (
    AgentSession,
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    ErrorEvent,
    TurnHandlingOptions,
    UserInputTranscribedEvent,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import google, openai
from openai.types.beta.realtime.session import TurnDetection
from openai.types.realtime import RealtimeTruncationRetentionRatio
from openai.types.realtime.realtime_truncation_retention_ratio import TokenLimits

from jarvis.ai_provider import require_provider_api_key
from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.memory.live_context import LiveContext
from jarvis.runtime_lane import GiccMode
from jarvis.voice.agent import build_instructions

LOGGER = logging.getLogger(__name__)

AcceptedTurnObserver = Callable[[ConversationTurn], None]
ConversationCloseObserver = Callable[[], None]

_OPENAI_REALTIME_POST_INSTRUCTION_TOKEN_LIMIT = 12_000
_OPENAI_REALTIME_RETENTION_RATIO = 0.75


class GeminiLiveProbeError(RuntimeError):
    """Provider-adapter failure while validating a Gemini Live model."""


async def probe_gemini_live_model(
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> None:
    """Require a candidate model to complete a real Gemini Live setup handshake."""

    async def connect_once() -> None:
        client = genai.Client(api_key=api_key)
        try:
            async with client.aio.live.connect(
                model=model,
                config={"response_modalities": ["AUDIO"]},
            ):
                return
        except (genai_errors.APIError, OSError, RuntimeError, ValueError) as exc:
            raise GeminiLiveProbeError(type(exc).__name__) from exc
        finally:
            await client.aio.aclose()

    try:
        await asyncio.wait_for(connect_once(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise GeminiLiveProbeError("timeout") from exc


def _create_realtime_model(config: JarvisConfig):
    api_key = require_provider_api_key(config.ai_provider, purpose="realtime voice")
    if config.ai_provider == "gemini":
        # Gemini 3.8 Live permanently enables proactive audio. Keep provider-native
        # activity/turn completion and explicit start-of-activity barge-in. The
        # JARVIS wake boundary removes already-consumed wake audio before this model
        # sees the conversation stream; Gemini then owns normal conversational VAD.
        return google.realtime.RealtimeModel(
            model=config.gemini_realtime_model,
            voice=config.gemini_realtime_voice,
            api_key=api_key,
            instructions=build_instructions(
                default_media_target=config.default_media_target,
                gicc_apply=config.gicc_mode is GiccMode.APPLY,
            ),
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
                ),
                activity_handling=(
                    google_types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
                ),
            ),
        )

    return openai.realtime.RealtimeModel(
        model=config.realtime_model,
        voice=config.realtime_voice,
        api_key=api_key,
        input_audio_noise_reduction="far_field",
        truncation=RealtimeTruncationRetentionRatio(
            type="retention_ratio",
            retention_ratio=_OPENAI_REALTIME_RETENTION_RATIO,
            token_limits=TokenLimits(
                post_instructions=_OPENAI_REALTIME_POST_INSTRUCTION_TOKEN_LIMIT
            ),
        ),
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
    """Translate final LiveKit USER transcripts and committed items into JARVIS turns."""

    def __init__(
        self,
        session: AgentSession,
        conversation: ConversationSession,
        live_context: LiveContext,
        *,
        show_transcript: bool,
    ) -> None:
        self.livekit_session = session
        self.conversation = conversation
        self.live_context = live_context
        self._show_transcript = show_transcript
        self._seen_item_ids: set[str] = set()
        self._transcript_committed_user_turn_ids: set[str] = set()
        self._accepted_turn_observers: list[AcceptedTurnObserver] = []
        self._close_observers: list[ConversationCloseObserver] = []
        session.on("user_input_transcribed", self._on_user_input_transcribed)
        session.on("conversation_item_added", self._on_conversation_item_added)
        session.on("error", self._on_error)
        session.on("close", self._on_close)

    def add_accepted_turn_observer(self, observer: AcceptedTurnObserver) -> None:
        if not callable(observer):
            raise TypeError("accepted-turn observer must be callable")
        self._accepted_turn_observers.append(observer)

    def add_close_observer(self, observer: ConversationCloseObserver) -> None:
        if not callable(observer):
            raise TypeError("close observer must be callable")
        self._close_observers.append(observer)

    def _notify_accepted_turn(self, turn: ConversationTurn) -> None:
        for observer in tuple(self._accepted_turn_observers):
            try:
                observer(turn)
            except Exception:
                LOGGER.exception(
                    "Accepted-turn observer failed; canonical conversation is unaffected"
                )

    def _notify_close(self) -> None:
        for observer in tuple(self._close_observers):
            try:
                observer()
            except Exception:
                LOGGER.exception(
                    "Conversation-close observer failed; session shutdown is unaffected"
                )

    @staticmethod
    def _normalized_item_id(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _accept_canonical_turn(
        self,
        role: ConversationRole,
        text: str,
        *,
        interrupted: bool = False,
        external_item_id: str | None = None,
    ) -> ConversationTurn:
        turn = self.conversation.accept_turn(
            role,
            text,
            interrupted=interrupted,
            external_item_id=external_item_id,
        )
        if not self.live_context.observe_turn(turn):
            raise RuntimeError(
                "canonical accepted turn was already present in LiveContext"
            )
        if external_item_id is not None:
            self._seen_item_ids.add(external_item_id)
        if self._show_transcript:
            suffix = " [interrupted]" if turn.interrupted else ""
            LOGGER.info("%s: %s%s", turn.role.value, turn.text, suffix)
        self._notify_accepted_turn(turn)
        return turn

    def _current_generation_user_turn(self, text: str) -> ConversationTurn | None:
        generation = self.conversation.user_utterance_generation
        if generation <= 0:
            return None
        return next(
            (
                turn
                for turn in reversed(self.conversation.turns)
                if turn.role is ConversationRole.USER
                and turn.user_utterance_generation == generation
                and turn.text == text
            ),
            None,
        )

    def _consume_transcript_committed_turn(self, text: str) -> bool:
        for turn in reversed(self.conversation.turns):
            if turn.turn_id not in self._transcript_committed_user_turn_ids:
                continue
            if turn.text != text:
                continue
            self._transcript_committed_user_turn_ids.remove(turn.turn_id)
            return True
        return False

    def _confirm_seen_item(self, item_id: str) -> None:
        for turn in reversed(self.conversation.turns):
            if turn.external_item_id != item_id:
                continue
            self._transcript_committed_user_turn_ids.discard(turn.turn_id)
            break

    def _on_user_input_transcribed(self, event: UserInputTranscribedEvent) -> None:
        if not event.is_final:
            return

        text = event.transcript.strip()
        if not text:
            return

        item_id = self._normalized_item_id(getattr(event, "item_id", None))
        if item_id is not None and item_id in self._seen_item_ids:
            return
        if self._current_generation_user_turn(text) is not None:
            if item_id is not None:
                self._seen_item_ids.add(item_id)
            return

        turn = self._accept_canonical_turn(
            ConversationRole.USER,
            text,
            external_item_id=item_id,
        )
        self._transcript_committed_user_turn_ids.add(turn.turn_id)
        LOGGER.debug(
            "Committed canonical USER turn from final transcript | generation=%s | "
            "activity_epoch=%s | item_id=%s",
            turn.user_utterance_generation,
            turn.user_activity_epoch,
            item_id or "unavailable",
        )

    def _on_conversation_item_added(self, event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage):
            return
        item_id = self._normalized_item_id(item.id)
        if item_id is not None and item_id in self._seen_item_ids:
            self._confirm_seen_item(item_id)
            return
        try:
            role = ConversationRole(item.role)
        except ValueError:
            return
        text = item.text_content.strip()
        if not text:
            return

        if role is ConversationRole.USER and self._consume_transcript_committed_turn(
            text
        ):
            if item_id is not None:
                self._seen_item_ids.add(item_id)
            return

        interrupted = bool(item.interrupted and role is ConversationRole.ASSISTANT)
        self._accept_canonical_turn(
            role,
            text,
            interrupted=interrupted,
            external_item_id=item_id,
        )

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
        self.live_context.clear()
        self._notify_close()


def create_voice_session(
    config: JarvisConfig,
) -> tuple[AgentSession, LiveKitConversationBridge]:
    conversation = ConversationSession()
    live_context = LiveContext(max_recent_turns=config.live_context_recent_turns)
    # Realtime Gemini/OpenAI already emit provider-native input-speech start/stop
    # events. LiveKit 1.8.3 maps those events to user speaking/listening state when
    # vad=None, so a second local Silero VAD is redundant here. Explicitly disabling
    # it also avoids constructing/loading an inference VAD on every wake activation.
    livekit_session = AgentSession(
        llm=_create_realtime_model(config),
        vad=None,
        turn_handling=TurnHandlingOptions(
            turn_detection=None,
            interruption={"enabled": True, "min_duration": 0.75, "resume_false_interruption": False},
            preemptive_generation={"enabled": False},
        ),
    )
    bridge = LiveKitConversationBridge(
        livekit_session,
        conversation,
        live_context,
        show_transcript=config.show_transcript,
    )
    return livekit_session, bridge
