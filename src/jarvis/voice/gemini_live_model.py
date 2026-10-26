"""Paid-only public realtime model; no client exists before durable admission."""

from __future__ import annotations

from livekit.agents import llm

from jarvis.voice.gemini_live_budget import ControlledLiveAdmission
from jarvis.voice.gemini_live_controls import LiveTransportControls
from jarvis.voice.gemini_live_session import ControlledGeminiLiveSession
from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission


class ControlledGeminiLiveModel(llm.RealtimeModel):
    def __init__(self, *, target, voice, state, admission, client_factory):
        if type(admission) not in {ControlledLiveAdmission, OperationalLiveAdmission}:
            raise llm.RealtimeError("Controlled Live admission required")
        if target.model_id != admission.model_id or not callable(client_factory):
            raise llm.RealtimeError("Controlled Live target/client binding invalid")
        super().__init__(
            capabilities=llm.RealtimeCapabilities(
                message_truncation=False,
                turn_detection=False,
                user_transcription=True,
                auto_tool_reply_generation=False,
                audio_output=True,
                manual_function_calls=False,
                can_disable_turn_detection=True,
                mutable_chat_context=True,
            )
        )
        self.target, self.voice, self.state = target, voice, state
        self.admission, self.client_factory = admission, client_factory
        self.operational = type(admission) is OperationalLiveAdmission
        self.sessions = []
        self.closed = False

    @property
    def controls(self):
        # Read the current accepted contract at physical-open/config boundaries,
        # matching the strict adapter's original behavior. Each admitted lease
        # separately pins its own immutable operational binding.
        return (
            LiveTransportControls.from_operational(
                self.admission.policy
            ).bounded_by_experiment(self.admission.experiment_authorization)
            if self.operational
            else LiveTransportControls.from_strict(self.admission.contract)
        )

    @property
    def model(self):
        return self.target.model_id

    @property
    def provider(self):
        return "gemini"

    def session(self, *, turn_detection_disabled=False):
        if self.closed or not self.state.current or not turn_detection_disabled:
            raise llm.RealtimeError(
                "Controlled Live requires current client-owned turns"
            )
        result = ControlledGeminiLiveSession(self)
        self.sessions.append(result)
        return result

    async def aclose(self):
        self.closed = True
        for session in self.sessions:
            await session.aclose()
