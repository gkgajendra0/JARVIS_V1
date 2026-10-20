"""PI-1C always-off unless explicit owner command; no provider calls in CI."""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from livekit.agents import AgentSession
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.io import AgentInput

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession
from jarvis.voice import livekit_session, personal_context_live_probe
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.personal_context_live_probe import (
    evaluate_probe_response,
    run_live_probe,
)

_ROOT = Path(__file__).resolve().parents[1]


class OfflineProbeSession:
    """Provider transport double; context updates use the real pinned Agent API."""

    def __init__(
        self,
        *,
        failure_stage=None,
        timeout_stage=None,
        answer="brackenfold",
        reply_error=None,
    ):
        self.events = []
        self.failure_stage = failure_stage
        self.timeout_stage = timeout_stage
        self.answer = answer
        self.reply_error = reply_error
        self.agent = None
        self.callback = None
        self.audio_enabled = True
        self.closed = False
        self.input = AgentInput(lambda: None, lambda: None, self._audio_enabled)

    def _audio_enabled(self, enabled):
        self.audio_enabled = enabled

    def on(self, event, callback):
        assert event == "conversation_item_added"
        self.callback = callback

    async def stage(self, name):
        self.events.append(name)
        if self.failure_stage == name:
            raise ValueError("fictional-provider-secret-must-not-be-printed")
        if self.timeout_stage == name:
            await asyncio.Future()

    async def start(self, agent, **kwargs):
        # Bind against the SDK signature rather than accepting invented session APIs.
        inspect.signature(AgentSession.start).bind(self, agent=agent, **kwargs)
        assert not self.audio_enabled
        self.agent = agent
        await self.stage("start")

    def generate_reply(self, **kwargs):
        inspect.signature(AgentSession.generate_reply).bind(self, **kwargs)
        assert self.agent is not None
        assert self.agent.tools == []
        messages = list(self.agent.chat_ctx.messages())
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert "FICTIONAL TEST DATA ONLY" in messages[0].text_content
        assert "brackenfold" in messages[0].text_content
        assert "brackenfold" not in kwargs["instructions"]
        assert kwargs["input_modality"] == "text"
        self.events.append("reply")

        async def wait_for_playout():
            await self.stage("playout")
            # Neither a user canary nor interrupted assistant text is a success.
            for item in (
                ChatMessage(role="user", content=["brackenfold"]),
                ChatMessage(
                    role="assistant", content=["brackenfold"], interrupted=True
                ),
                ChatMessage(role="assistant", content=[self.answer]),
            ):
                self.callback(SimpleNamespace(item=item))

        return SimpleNamespace(
            wait_for_playout=wait_for_playout,
            exception=lambda: self.reply_error,
        )

    async def aclose(self):
        self.events.append("close")
        self.closed = True


@pytest.fixture
def offline_probe(monkeypatch):
    def configure(**kwargs):
        session = OfflineProbeSession(**kwargs)
        conversation = ConversationSession()
        config = JarvisConfig(
            ai_provider="gemini", gemini_realtime_model="gemini-3.8-live"
        )
        monkeypatch.setattr(
            JarvisConfig, "from_environment", classmethod(lambda cls: config)
        )
        monkeypatch.setattr(
            livekit_session,
            "create_voice_session",
            lambda actual: (session, SimpleNamespace(conversation=conversation)),
        )
        real_update = JarvisVoiceAgent.update_chat_ctx

        async def update(agent, chat_ctx, **options):
            assert agent is session.agent
            await session.stage("update")
            await real_update(agent, chat_ctx, **options)

        monkeypatch.setattr(JarvisVoiceAgent, "update_chat_ctx", update)
        return session

    return configure


@pytest.mark.asyncio
async def test_live_probe_delivers_context_through_started_agent(offline_probe):
    session = offline_probe()
    result = await run_live_probe(timeout_seconds=1)
    assert result["status"] == "completed"
    assert result["result"] == "SYNTHETIC_CANARY_OBSERVED"
    assert result["assistant_transcript_present"] is True
    assert result["memory_write"] is False
    assert result["owner_data_access"] is False
    assert session.events == ["start", "update", "reply", "playout", "close"]
    assert session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["start", "update", "playout"])
@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_live_probe_closes_session_on_failure(offline_probe, stage, failure):
    options = {"timeout_stage" if failure == "timeout" else "failure_stage": stage}
    session = offline_probe(**options)
    expected = TimeoutError if failure == "timeout" else ValueError
    with pytest.raises(expected):
        async with asyncio.timeout(1) as watchdog:
            await run_live_probe(timeout_seconds=0.01)
    assert not watchdog.expired()
    assert session.closed
    assert session.events[-1] == "close"
    assert stage in session.events
    if stage != "playout":
        assert "reply" not in session.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "expected", "transcript_present"),
    [("unknown", "CANARY_NOT_OBSERVED", True), ("", "NO_TEXT_TRANSCRIPT", False)],
)
async def test_live_probe_ignores_user_and_interrupted_canaries(
    offline_probe, answer, expected, transcript_present
):
    session = offline_probe(answer=answer)
    result = await run_live_probe(timeout_seconds=1)
    assert result["result"] == expected
    assert result["assistant_transcript_present"] is transcript_present
    assert session.closed


@pytest.mark.asyncio
async def test_live_probe_closes_after_reported_reply_failure(offline_probe):
    session = offline_probe(reply_error=ValueError("fictional-provider-secret"))
    with pytest.raises(RuntimeError, match="^ValueError$"):
        await run_live_probe(timeout_seconds=1)
    assert session.closed


def test_probe_failure_output_omits_provider_details(
    offline_probe, monkeypatch, capsys
):
    session = offline_probe(failure_stage="update")
    monkeypatch.setattr(sys, "argv", ["probe", "--allow-one-real-provider-test"])
    assert personal_context_live_probe.main() == 2
    output = capsys.readouterr().out
    assert "fictional-provider-secret" not in output
    payload = json.loads(output)
    assert payload["status"] == "INCONCLUSIVE_OR_FAILED"
    assert payload["exception_type"] == "ValueError"
    assert session.closed


def test_probe_without_opt_in_never_enters_live_execution(monkeypatch, capsys):
    async def forbidden(**kwargs):
        pytest.fail("default invocation must not enter provider/configuration setup")

    monkeypatch.setattr(personal_context_live_probe, "run_live_probe", forbidden)
    monkeypatch.setattr(sys, "argv", ["probe"])
    assert personal_context_live_probe.main() == 0
    assert json.loads(capsys.readouterr().out)["context_delivery_test"] == "NOT_RUN"


def test_probe_accepts_only_observed_fictional_canary() -> None:
    assert (
        evaluate_probe_response("The synthetic codeword is brackenfold.")
        == "SYNTHETIC_CANARY_OBSERVED"
    )
    assert evaluate_probe_response("unknown") == "CANARY_NOT_OBSERVED"
    assert evaluate_probe_response("") == "NO_TEXT_TRANSCRIPT"


def test_probe_default_requires_opt_in_and_uses_no_network() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(_ROOT / "tools" / "research" / "pi1c_live_context_probe.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert process.returncode == 0
    payload = json.loads(process.stdout)
    assert payload["status"] == "OFFLINE_PREFLIGHT_ONLY"
    assert payload["owner_memory_access"] is False
    assert payload["would_run_live_provider"] is False
    assert payload["context_delivery_test"] == "NOT_RUN"
