"""Network-free contracts for the isolated PI-1C delivery comparison."""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest
from livekit.agents import AgentSession
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.io import AgentInput

from jarvis.config import JarvisConfig
from jarvis.voice import personal_context_delivery_eval as evaluation


class Transport:
    def __init__(
        self,
        path,
        *,
        fail=False,
        delayed_answer=False,
        preamble=False,
        usage_failure=False,
    ):
        self.path = path
        self.fail = fail
        self.delayed_answer = delayed_answer
        self.preamble = preamble
        self.usage_failure = usage_failure
        self.run_calls = 0
        self.agent = None
        self.callbacks = {}
        self.closed = False
        self.audio_enabled = True
        self.turn = 0
        self.before_start = []
        self.input = AgentInput(lambda: None, lambda: None, self.set_audio)

    def set_audio(self, enabled):
        self.audio_enabled = enabled

    def on(self, name, callback):
        self.callbacks[name] = callback

    async def start(self, *, agent):
        inspect.signature(AgentSession.start).bind(self, agent=agent)
        assert not self.audio_enabled
        self.agent = agent
        self.before_start = list(agent.chat_ctx.messages())
        if self.fail:
            raise ValueError("secret-provider-detail")

    def generate_reply(self, **kwargs):
        inspect.signature(AgentSession.generate_reply).bind(self, **kwargs)
        case = evaluation.DELIVERY_CASES[self.turn]
        assert kwargs["user_input"] == case.question
        assert case.canary not in kwargs["user_input"]
        assert "instructions" not in kwargs
        assert kwargs["input_modality"] == "text"
        self.turn += 1

        async def finish():
            if self.usage_failure:
                self.callbacks["metrics_collected"](
                    SimpleNamespace(
                        metrics=SimpleNamespace(
                            type="realtime_model_metrics",
                            input_tokens=100,
                            output_tokens=2,
                            total_tokens=102,
                            ttft=0.2,
                        )
                    )
                )
                raise TimeoutError("private-provider-detail")
            if self.preamble:
                self.callbacks["conversation_item_added"](
                    SimpleNamespace(
                        item=ChatMessage(
                            role="assistant", content=["I will look it up."]
                        )
                    )
                )
            if self.path == "tool_result":
                tools = self.agent.tools
                assert len(tools) == 1
                payload = await tools[0]()
                assert case.canary in json.dumps(payload)
            elif self.path != "baseline":
                assert any(
                    case.canary in m.text_content
                    for m in self.agent.chat_ctx.messages()
                )
            text = "unknown" if self.path == "baseline" else case.canary
            # Only completed assistant output can establish delivery.
            for role, content, interrupted in [
                ("user", case.canary, False),
                ("assistant", case.canary, True),
                ("assistant", text, False),
            ]:
                event = SimpleNamespace(
                    item=ChatMessage(
                        role=role, content=[content], interrupted=interrupted
                    )
                )
                if self.delayed_answer and role == "assistant" and not interrupted:
                    asyncio.get_running_loop().call_later(
                        0.01, self.callbacks["conversation_item_added"], event
                    )
                else:
                    self.callbacks["conversation_item_added"](event)
            self.callbacks["metrics_collected"](
                SimpleNamespace(
                    metrics=SimpleNamespace(
                        type="realtime_model_metrics",
                        ttft=0.25,
                        input_tokens=30,
                        output_tokens=4,
                        total_tokens=34,
                    )
                )
            )

        return SimpleNamespace(wait_for_playout=finish, exception=lambda: None)

    async def run(self, **kwargs):
        inspect.signature(AgentSession.run).bind(self, **kwargs)
        self.run_calls += 1
        handle = self.generate_reply(**kwargs)
        await handle.wait_for_playout()
        if self.delayed_answer:
            await asyncio.sleep(0.02)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_comparison_proves_each_path_with_real_pinned_agent(monkeypatch):
    transports = []

    def create(config):
        assert not config.memory_enabled
        assert not config.show_transcript
        assert config.default_media_target is None
        transport = Transport(evaluation.DELIVERY_PATHS[len(transports)])
        transports.append(transport)
        return transport, SimpleNamespace(
            conversation=SimpleNamespace(start=lambda: None)
        )

    monkeypatch.setattr(evaluation, "create_voice_session", create)
    result = await evaluation.compare_delivery_paths(
        config=JarvisConfig(ai_provider="gemini"), timeout_seconds=1
    )
    assert result["status"] == "DELIVERY_OBSERVED"
    assert len(result["paths"]) == 4
    assert all(t.closed for t in transports)
    assert not transports[0].before_start
    assert len(transports[1].before_start) == len(evaluation.DELIVERY_CASES)
    assert not transports[2].before_start
    assert not transports[3].before_start
    for path in result["paths"]:
        assert len(path["turns"]) == 3
        for turn in path["turns"]:
            assert turn["metrics"][0]["input_tokens"] == 30
            assert turn["answer"] != ""
            assert turn["canary_observed"] == (path["path"] != "baseline")
            assert turn["tool_calls"] == (1 if path["path"] == "tool_result" else 0)
    assert result["billed_cost"] is None
    assert result["personalization_quality"] == "NOT_MEASURED"


@pytest.mark.asyncio
async def test_failure_closes_session_and_stops_comparison(monkeypatch):
    transport = Transport("baseline", fail=True)
    monkeypatch.setattr(
        evaluation,
        "create_voice_session",
        lambda config: (
            transport,
            SimpleNamespace(conversation=SimpleNamespace(start=lambda: None)),
        ),
    )
    result = await evaluation.compare_delivery_paths(
        config=JarvisConfig(ai_provider="gemini"), timeout_seconds=0.1
    )
    assert transport.closed
    assert result["status"] == "INCONCLUSIVE"
    assert result["paths"][0]["exception_type"] == "ValueError"
    assert "secret-provider-detail" not in json.dumps(result)
    assert len(result["paths"]) == 1


def test_default_cli_does_not_load_configuration_or_connect(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["comparison"])

    def forbidden(cls):
        pytest.fail("offline default must not read machine configuration")

    monkeypatch.setattr(JarvisConfig, "from_environment", classmethod(forbidden))
    assert evaluation.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OFFLINE_PREFLIGHT_ONLY"


@pytest.mark.asyncio
async def test_timeout_always_closes_transport(monkeypatch):
    transport = Transport("baseline")

    async def wait_forever(**kwargs):
        await asyncio.Future()

    transport.start = wait_forever
    monkeypatch.setattr(
        evaluation,
        "create_voice_session",
        lambda config: (
            transport,
            SimpleNamespace(conversation=SimpleNamespace(start=lambda: None)),
        ),
    )
    result = await evaluation.compare_delivery_paths(
        config=JarvisConfig(ai_provider="gemini"), timeout_seconds=0.01
    )
    assert transport.closed
    assert result["status"] == "INCONCLUSIVE"
    assert result["paths"][0]["exception_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_tool_result_waits_for_separate_automatic_answer(monkeypatch):
    transport = Transport("tool_result", delayed_answer=True)
    monkeypatch.setattr(
        evaluation,
        "create_voice_session",
        lambda config: (
            transport,
            SimpleNamespace(conversation=SimpleNamespace(start=lambda: None)),
        ),
    )
    result = await evaluation._run_path(
        "tool_result", JarvisConfig(ai_provider="gemini"), 1
    )
    assert result["status"] == "COMPLETED"
    assert all(turn["canary_observed"] for turn in result["turns"])
    assert transport.closed


def test_hindi_label_transliteration_is_reported_separately_from_literal_match():
    case = evaluation.DELIVERY_CASES[1]
    assert evaluation.observe_canary(case, "लेबल एम्बरव्हिसल है।") == (True, False)
    assert evaluation.observe_canary(case, "label amberwhistle hai") == (True, True)
    assert evaluation.observe_canary(case, "अज्ञात") == (False, False)


@pytest.mark.asyncio
async def test_preamble_does_not_hide_the_separate_automatic_tool_answer(monkeypatch):
    transport = Transport("tool_result", delayed_answer=True, preamble=True)
    monkeypatch.setattr(
        evaluation,
        "create_voice_session",
        lambda config: (
            transport,
            SimpleNamespace(conversation=SimpleNamespace(start=lambda: None)),
        ),
    )
    result = await evaluation._run_path(
        "tool_result", JarvisConfig(ai_provider="gemini"), 1
    )
    assert result["status"] == "COMPLETED"
    assert all(turn["canary_observed"] for turn in result["turns"])
    assert transport.run_calls == 3


@pytest.mark.asyncio
async def test_failed_turn_preserves_reported_session_and_partial_usage(monkeypatch):
    transport = Transport("baseline", usage_failure=True)
    monkeypatch.setattr(
        evaluation,
        "create_voice_session",
        lambda config: (
            transport,
            SimpleNamespace(conversation=SimpleNamespace(start=lambda: None)),
        ),
    )
    result = await evaluation._run_path(
        "baseline", JarvisConfig(ai_provider="gemini"), 1
    )
    assert result["status"] == "INCONCLUSIVE"
    assert result["session_metrics"][0]["total_tokens"] == 102
    assert result["failed_turn"]["metrics"][0]["total_tokens"] == 102
    assert result["usage_capture_complete"] is False
    assert "private-provider-detail" not in json.dumps(result)
    assert transport.closed
