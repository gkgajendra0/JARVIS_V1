"""Voice lab support: usage measurement and isolation of the lab runtime."""

import json
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession


class _FakeSession:
    def __init__(self):
        self.handlers = {}

    def on(self, name, handler):
        self.handlers[name] = handler

    def emit(self, name, **fields):
        self.handlers[name](SimpleNamespace(**fields))


class _FakeBridge:
    def __init__(self, conversation):
        self.conversation = conversation
        self.closers = []

    def add_close_observer(self, closer):
        self.closers.append(closer)


def _usage(input_tokens, *, audio=0, text=0, cached=0, output=0):
    return SimpleNamespace(
        model_usage=[
            SimpleNamespace(
                type="llm_usage",
                provider="google",
                model="gemini-3.8-live",
                input_tokens=input_tokens,
                input_cached_tokens=cached,
                input_audio_tokens=audio,
                input_text_tokens=text,
                output_tokens=output,
                output_audio_tokens=output,
                output_text_tokens=0,
            ),
            SimpleNamespace(type="tts_usage"),  # other usage kinds are ignored
        ]
    )


def test_usage_meter_reports_per_response_deltas_without_content(tmp_path, monkeypatch):
    import jarvis.voice.voice_usage_meter as meter_module
    from jarvis.voice.voice_usage_meter import VoiceUsageMeter

    clock = iter([10.0, 10.8, 20.0, 21.5])
    monkeypatch.setattr(meter_module, "monotonic", lambda: next(clock))
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "My secret plan is Goa")
    session, bridge = _FakeSession(), _FakeBridge(conversation)
    meter = VoiceUsageMeter(tmp_path / "usage.jsonl", mode="project_memory")
    meter.attach(session, bridge)
    for _ in range(2):
        session.emit("user_state_changed", old_state="speaking", new_state="listening")
        session.emit("agent_state_changed", old_state="thinking", new_state="speaking")
    # session_usage_updated is cumulative; Gemini's prompt is the whole context.
    session.emit(
        "session_usage_updated", usage=_usage(1000, audio=400, text=600, output=50)
    )
    session.emit(
        "session_usage_updated", usage=_usage(1000, audio=400, text=600, output=50)
    )
    session.emit(
        "session_usage_updated", usage=_usage(3500, audio=900, text=2600, output=120)
    )
    session.emit(
        "function_tools_executed",
        function_calls=[SimpleNamespace(name="prepare_project_turn")],
    )
    bridge.closers[0]()
    text = (tmp_path / "usage.jsonl").read_text()
    row = json.loads(text)
    assert row["latency_ms"]["values"] == [800.0, 1500.0]
    assert row["responses"] == 2 and row["user_turns"] == 1
    assert row["input_per_response"] == {
        "values": [1000, 2500],
        "first": 1000,
        "peak": 2500,
    }
    assert row["tokens"]["input"] == 3500 and row["tokens"]["input_text"] == 2600
    assert row["tokens"]["output"] == 120 and row["usage_updates"] == 2
    assert row["tool_calls"] == {"prepare_project_turn": 1}
    assert "metrics_collected" not in session.handlers  # deprecated in LiveKit 1.8
    assert "Goa" not in text and "secret" not in text
    with pytest.raises(ValueError):
        VoiceUsageMeter(tmp_path / "x", mode="production")


def test_voice_lab_refuses_memory_outside_the_lab_and_disables_paid(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    import jarvis.memory.runtime as memory_runtime
    from jarvis.config import JarvisConfig
    from jarvis.voice.project_voice_lab import require_isolated_memory, voice_lab_config

    lab = tmp_path / "lab"
    lab.mkdir()
    monkeypatch.setattr(
        memory_runtime, "default_memory_database_path", lambda: tmp_path / "memory.db"
    )
    with pytest.raises(RuntimeError, match="not inside the isolated lab"):
        require_isolated_memory(lab)
    monkeypatch.setattr(
        memory_runtime, "default_memory_database_path", lambda: lab / "memory.db"
    )
    assert require_isolated_memory(lab) == (lab / "memory.db").resolve()
    config = voice_lab_config(replace(JarvisConfig(), ai_provider="gemini"))
    assert config.memory_enabled and not config.gemini_fallback.enabled
    assert config.personal_context_mode == "off"
    assert not config.memory_semantic_recall_enabled
    assert not config.work_orchestration_enabled


@pytest.mark.asyncio
async def test_voice_lab_baseline_passes_no_project_memory(tmp_path):
    from jarvis.voice.project_voice_lab import project_memory_factory, run_voice_lab

    calls = []

    class Runtime:
        async def run(self):
            calls.append("run")

    def builder(config, **kwargs):
        calls.append(sorted(kwargs))
        return Runtime()

    await run_voice_lab(object(), tmp_path, baseline=True, runtime_builder=builder)
    await run_voice_lab(object(), tmp_path, baseline=False, runtime_builder=builder)
    assert calls == [
        ["tool_allowlist", "voice_session_observer"],
        "run",
        ["project_memory_factory", "tool_allowlist", "voice_session_observer"],
        "run",
    ]
    assert callable(project_memory_factory)
