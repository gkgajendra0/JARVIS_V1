"""Owner-activated project memory in normal Jarvis voice (disabled by default).

With JARVIS_PROJECT_MEMORY_MODE off (the default) nothing changes. With it on,
only owner conversation sessions use project memory, unqualified combinations
leave Jarvis running as ordinary voice, and a failed or lapsed Windows Hello
grant never stops voice.
"""

import asyncio
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import PERSISTABLE_SETTINGS
from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.voice import project_voice_production as production
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.project_voice import VoiceProjectMemory
from jarvis.voice.runtime import VoiceRuntimeController

QUALIFIED = replace(
    JarvisConfig(),
    project_memory_mode="voice",
    memory_enabled=True,
    ai_provider="gemini",
)


def test_flag_is_off_by_default_and_persistable(monkeypatch, tmp_path):
    assert JarvisConfig().project_memory_mode == "off"
    assert "JARVIS_PROJECT_MEMORY_MODE" in PERSISTABLE_SETTINGS
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.delenv("JARVIS_PROJECT_MEMORY_MODE", raising=False)
    assert JarvisConfig.from_environment().project_memory_mode == "off"
    monkeypatch.setenv("JARVIS_PROJECT_MEMORY_MODE", " Voice ")
    assert JarvisConfig.from_environment().project_memory_mode == "voice"
    with pytest.raises(ValueError, match="project_memory_mode"):
        replace(JarvisConfig(), project_memory_mode="text")


def test_flag_off_builds_no_project_memory():
    assert production.production_project_memory_factory(JarvisConfig()) is None
    assert production.activation_blockers(JarvisConfig()) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"memory_enabled": False}, "JARVIS_MEMORY_ENABLED"),
        ({"ai_provider": "openai"}, "JARVIS_AI_PROVIDER"),
        ({"gemini_fallback": GeminiFallbackConfig(enabled=True)}, "handoff"),
        ({"personal_context_mode": "apply"}, "JARVIS_PERSONAL_CONTEXT_MODE"),
    ],
)
def test_unqualified_combinations_run_as_ordinary_voice(change, reason, caplog):
    config = replace(QUALIFIED, **change)
    assert any(reason in b for b in production.activation_blockers(config))
    with caplog.at_level(logging.ERROR):
        assert production.production_project_memory_factory(config) is None
    assert "Project memory NOT active" in caplog.text and reason in caplog.text


def test_qualified_flag_builds_non_required_memory():
    assert production.activation_blockers(QUALIFIED) == []
    factory = production.production_project_memory_factory(QUALIFIED)
    memory = factory(SimpleNamespace(), SimpleNamespace())
    assert isinstance(memory, VoiceProjectMemory)
    assert memory.required is False and memory.fast_path is True
    lab = VoiceProjectMemory(None, None, source_clearance=bool)
    assert lab.required is True  # the isolated lab still stops on Hello denial


def test_check_command_reports_blockers(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.setenv("JARVIS_PROJECT_MEMORY_MODE", "voice")
    monkeypatch.setenv("JARVIS_MEMORY_ENABLED", "false")
    assert production.main(["--check"]) == 1
    assert "will NOT activate" in capsys.readouterr().out
    monkeypatch.setenv("JARVIS_PROJECT_MEMORY_MODE", "off")
    assert production.main(["--check"]) == 0
    assert "disabled" in capsys.readouterr().out


# -- runtime wiring ----------------------------------------------------------


class StubMemory:
    required = False

    def __init__(self, *, available=True, start_error=None):
        self._available = available
        self._start_error = start_error
        self.sessions = []
        self.closed = 0

    def available(self):
        return self._available

    def configure_realtime_model(self, llm):
        self.llm = llm

    def session(self, conversation):
        turns = SimpleNamespace(
            bind_session=lambda s: None,
            bind_injection_registry=lambda r: None,
            observe_speech=lambda e: None,
            observe_turn=lambda t: None,
            close=lambda: None,
            start_preload=lambda: None,
        )
        self.sessions.append((conversation, turns))
        return turns

    async def start(self):
        if self._start_error is not None:
            raise self._start_error

    async def aclose(self):
        self.closed += 1


class StubSession:
    llm = object()

    def on(self, name, handler):
        pass


def stub_session_factory(config):
    conversation = SimpleNamespace(turns=[])
    bridge = SimpleNamespace(
        conversation=conversation,
        add_accepted_turn_observer=lambda o: None,
        add_close_observer=lambda o: None,
        register_restored_context=lambda c: None,
    )
    return StubSession(), bridge


def controller(memory):
    return CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(),
        SimpleNamespace(),
        memory_runtime=SimpleNamespace(),
        capability_runtime=SimpleNamespace(),
        project_memory=memory,
        session_factory=stub_session_factory,
    )


def test_only_owner_conversation_sessions_use_project_memory():
    memory = StubMemory()
    c = controller(memory)
    _, bridge = c._system_session()  # startup/status/work speech, update approval
    assert memory.sessions == [] and c._project_turns is None
    _, bridge = c._session_factory(c.config)  # a wake conversation
    assert [conv for conv, _ in memory.sessions] == [bridge.conversation]
    assert c._project_turns is memory.sessions[0][1]
    assert c._session_purpose == "conversation"


def test_a_lapsed_history_grant_leaves_the_wake_session_ordinary():
    memory = StubMemory(available=False)
    c = controller(memory)
    c._session_factory(c.config)
    assert memory.sessions == [] and c._project_turns is None


def test_no_project_memory_leaves_sessions_untouched():
    c = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(), SimpleNamespace(), session_factory=stub_session_factory
    )
    c._session_factory(c.config)
    assert c._project_memory is None and c._project_turns is None


async def run_once(c, monkeypatch):
    ran = []

    async def base_run(self):
        ran.append(self._project_memory)

    monkeypatch.setattr(VoiceRuntimeController, "run", base_run)
    c._memory_runtime = SimpleNamespace(start=_async_none, close=_async_none)
    c._capability_runtime = None
    await c.run()
    return ran


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_hello_failure_at_startup_continues_as_ordinary_voice(monkeypatch):
    memory = StubMemory(start_error=PermissionError("helper_timeout"))
    c = controller(memory)
    ran = await run_once(c, monkeypatch)
    assert ran == [None]  # voice ran, without project memory
    assert memory.closed == 1 and c._project_memory is None


@pytest.mark.asyncio
async def test_lab_still_stops_when_hello_is_denied(monkeypatch):
    memory = StubMemory(start_error=PermissionError("denied"))
    memory.required = True
    c = controller(memory)
    with pytest.raises(PermissionError):
        await run_once(c, monkeypatch)
    assert memory.closed == 1  # memory is still released


@pytest.mark.asyncio
async def test_lapsed_grant_is_reported_once_and_counted(caplog):
    memory = VoiceProjectMemory(None, None, source_clearance=bool)
    memory.access = SimpleNamespace(current=lambda: False)
    with caplog.at_level(logging.WARNING):
        assert memory.available() is False
        assert memory.available() is False
    assert caplog.text.count("Voice project memory paused") == 1
    assert memory.metrics.paused_sessions == 2
    await asyncio.sleep(0)


def test_lab_baseline_ignores_a_production_flag(tmp_path):
    """A machine profile with the flag on never adds memory to -Baseline."""
    from jarvis.voice import project_voice_lab

    seen = {}

    def builder(config, **kwargs):
        seen["mode"] = config.project_memory_mode
        seen["kwargs"] = kwargs

        class Runtime:
            async def run(self):
                return None

        return Runtime()

    asyncio.run(
        project_voice_lab.run_voice_lab(
            QUALIFIED, tmp_path, baseline=True, runtime_builder=builder
        )
    )
    assert seen["mode"] == "off"
    assert "project_memory_factory" not in seen["kwargs"]
