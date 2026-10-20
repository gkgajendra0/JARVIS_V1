"""Normal production composition, not the separate delivery experiment."""

import asyncio
from types import SimpleNamespace

import pytest
import test_personal_context_runtime as context_fixtures
from test_long_utterance_activity import _session_pair
from test_personal_context_runtime import Sink
from test_production_hands_voice_wiring import _runtime

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.personal_context_audio import PersonalContextAudioOutput

personal = context_fixtures.personal


def test_cli_override_reaches_normal_runtime_without_persisting(monkeypatch, tmp_path):
    from jarvis.machine_config import save_machine_settings
    from jarvis.voice import production_runtime

    path = tmp_path / "machine.json"
    save_machine_settings({"JARVIS_PERSONAL_CONTEXT_MODE": "off"}, path)
    before = path.read_bytes()
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    assert (
        production_runtime._load_voice_config("apply").personal_context_mode == "apply"
    )
    assert path.read_bytes() == before
    seen = []

    async def run(mode):
        seen.append(mode)

    monkeypatch.setattr(production_runtime, "_run_from_configuration", run)
    assert production_runtime.main(["--personal-context", "apply"]) == 0
    assert seen == ["apply"]


def test_apply_switch_enables_canonical_memory_and_suppresses_transcripts():
    config = JarvisConfig(personal_context_mode="apply", show_transcript=True)
    assert config.memory_enabled and not config.show_transcript
    assert JarvisConfig().personal_context_mode == "off"
    with pytest.raises(ValueError, match="personal_context_mode"):
        JarvisConfig(personal_context_mode="shadow")


@pytest.mark.asyncio
async def test_normal_factory_shares_tools_output_and_pending_consent_guard(personal):
    prototype, service, _, authority, _ = personal
    config = JarvisConfig(
        personal_context_mode="apply", initial_request_timeout_seconds=0.02
    )
    session, bridge = _session_pair()
    sink = Sink()
    capabilities = _runtime()
    for name in (
        "authorize_personal_context",
        "consume_personal_context",
        "validate_personal_context",
        "invalidate_personal_context",
    ):
        setattr(capabilities, name, getattr(authority, name))
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(output=sink),
        session_factory=lambda config: (session, bridge),
        memory_runtime=SimpleNamespace(service=service, retrieval=prototype._retrieval),
        capability_runtime=capabilities,
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    bridge.conversation.start()
    bridge.conversation.accept_turn(ConversationRole.USER, "What should I eat?")
    output = runtime._session_audio_output(bridge, sink)
    assert isinstance(output, PersonalContextAudioOutput)
    tools = {tool.id: tool for tool in runtime._vision_tools.tools}
    assert {
        "personal_context_catalog",
        "read_personal_context",
        "remember_memory",
    } <= tools.keys()
    assert "inspect_memory" not in tools and "recall_memory" not in tools
    assert (
        "personal_context_catalog"
        in JarvisVoiceAgent(tools=list(tools.values())).instructions
    )
    session.emit(
        "agent_state_changed",
        SimpleNamespace(old_state="initializing", new_state="listening"),
    )
    authority.wait.clear()
    task = asyncio.create_task(tools["personal_context_catalog"]())
    await asyncio.to_thread(authority.entered.wait, 1)
    runtime._arm_timeout(0.01)
    await asyncio.sleep(0.03)
    assert not runtime._active_end.is_set()
    authority.wait.set()
    catalog = await task
    packet = await tools["read_personal_context"](catalog["catalog_id"], [0])
    assert packet["status"] == "selected" and "vegetarian" in str(packet)
    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )
    assert runtime._active_end.is_set()
    output.detach()
    runtime._cancel_timeout()


@pytest.mark.asyncio
async def test_apply_mutation_gets_fresh_owner_consent_and_retires(personal):
    session, service, conversation, authority, retired = personal
    conversation.accept_turn(ConversationRole.USER, "Remember my home city is Sagar")
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    await tools.remember(predicate="home city", value="Sagar")
    assert authority.calls[0]["operation"] == "remember"
    assert (await service.inspect_exact(predicate="home city")).record.value == "Sagar"
    session.response_finished()
    assert retired


@pytest.mark.asyncio
async def test_denied_mutation_does_not_write(personal):
    session, service, conversation, authority, _ = personal
    authority.denied = True
    conversation.accept_turn(ConversationRole.USER, "Remember my home city is Sagar")
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with pytest.raises(PermissionError):
        await tools.remember(predicate="home city", value="Sagar")
    from jarvis.memory.service import MemoryNotFoundError

    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="home city")


def test_off_does_not_advertise_personal_context():
    assert "personal_context_catalog" not in JarvisVoiceAgent().instructions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question", ["What should I eat?", "Aaj kya khaun?", "आज खाने में क्या खाऊँ?"]
)
async def test_normal_voice_session_runs_real_context_tools_and_guard(
    personal, question
):
    from livekit import rtc
    from livekit.agents.llm import ChatMessage, FunctionCall
    from livekit.agents.voice.speech_handle import SpeechHandle

    prototype, service, _, authority, _ = personal
    session, bridge = _session_pair()
    session.input = SimpleNamespace()
    session.output = SimpleNamespace()
    sink = Sink()
    routing = []
    audio = SimpleNamespace(
        output=sink,
        activate_session=lambda value: routing.append("active"),
        deactivate_session=lambda: routing.append("inactive"),
    )
    capabilities = _runtime()
    for name in (
        "authorize_personal_context",
        "consume_personal_context",
        "validate_personal_context",
        "invalidate_personal_context",
    ):
        setattr(capabilities, name, getattr(authority, name))
    config = JarvisConfig(personal_context_mode="apply", ai_provider="gemini")
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        audio,
        session_factory=lambda config: (session, bridge),
        memory_runtime=SimpleNamespace(service=service, retrieval=prototype._retrieval),
        capability_runtime=capabilities,
    )
    seen = {}

    async def start(*, agent, record):
        seen["record"] = record
        assert isinstance(session.output.audio, PersonalContextAudioOutput)
        session.emit(
            "conversation_item_added",
            SimpleNamespace(item=ChatMessage(role="user", content=[question])),
        )
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="listening", new_state="thinking"),
        )
        tools = {tool.id: tool for tool in agent.tools}
        catalog_handle = SpeechHandle.create()
        session.emit("speech_created", SimpleNamespace(speech_handle=catalog_handle))
        catalog_handle._item_added(
            [
                FunctionCall(
                    name="personal_context_catalog", call_id="catalog", arguments="{}"
                )
            ]
        )
        catalog = await tools["personal_context_catalog"]()
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="thinking", new_state="listening"),
        )
        assert not runtime._active_end.is_set()
        catalog_handle._mark_done()
        await asyncio.sleep(0)
        read_handle = SpeechHandle.create()
        session.emit("speech_created", SimpleNamespace(speech_handle=read_handle))
        read_handle._item_added(
            [FunctionCall(name="read_personal_context", call_id="read", arguments="{}")]
        )
        packet = await tools["read_personal_context"](
            catalog["catalog_id"], [catalog["facets"].index("diet_preference")]
        )
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="thinking", new_state="listening"),
        )
        assert not runtime._active_end.is_set()
        read_handle._mark_done()
        await asyncio.sleep(0)
        final_handle = SpeechHandle.create()
        session.emit("speech_created", SimpleNamespace(speech_handle=final_handle))
        seen["packet"] = packet
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="thinking", new_state="speaking"),
        )
        await session.output.audio.capture_frame(rtc.AudioFrame.create(16000, 1, 160))
        session.output.audio.flush()
        sink.on_playback_finished(playback_position=0.01, interrupted=False)
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="speaking", new_state="listening"),
        )
        assert not runtime._active_end.is_set()
        final_handle._item_added(
            [ChatMessage(role="assistant", content=["A vegetarian meal."])]
        )
        final_handle._mark_done()
        await asyncio.sleep(0)

    async def close():
        session.emit("close", SimpleNamespace(error=None, reason=None))

    session.start = start
    session.aclose = close
    await asyncio.wait_for(runtime._run_one_session(), timeout=3)
    assert seen["record"] is False
    assert seen["packet"]["status"] == "selected" and "vegetarian" in str(
        seen["packet"]
    )
    assert authority.calls[0]["question"] == question
    assert routing == ["active", "inactive"] and len(sink.frames) == 1


@pytest.mark.asyncio
async def test_queued_write_rechecks_request_before_transaction(personal):
    import threading

    session, service, conversation, authority, _ = personal
    blocked = threading.Event()
    release = threading.Event()

    def hold(connection):
        blocked.set()
        release.wait(2)

    blocker = asyncio.create_task(service._lifecycle._writer.run(hold))
    await asyncio.to_thread(blocked.wait, 1)
    conversation.accept_turn(ConversationRole.USER, "Remember my home city is Sagar")
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    task = asyncio.create_task(tools.remember(predicate="home city", value="Sagar"))
    await asyncio.to_thread(authority.entered.wait, 1)
    await asyncio.sleep(0.03)
    conversation.begin_user_activity()
    session.observe_activity()
    release.set()
    await blocker
    with pytest.raises(PermissionError):
        await task
    from jarvis.memory.service import MemoryNotFoundError

    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="home city")


@pytest.mark.asyncio
async def test_apply_uses_explicit_local_vad_for_provider_activity_separation(
    monkeypatch,
):
    from livekit.agents import inference
    from livekit.agents.llm import InputSpeechStartedEvent
    from livekit.agents.voice.agent_activity import AgentActivity

    from jarvis.voice.livekit_session import create_voice_session

    monkeypatch.setattr(
        "jarvis.voice.livekit_session._create_realtime_model", lambda config: None
    )
    monkeypatch.setattr(inference, "VAD", lambda **kwargs: object())
    session, _ = create_voice_session(JarvisConfig(personal_context_mode="apply"))
    assert session._using_default_vad is False
    events = []
    session.on("user_state_changed", lambda event: events.append(event.new_state))
    activity = object.__new__(AgentActivity)
    activity._session = session
    activity._agent = JarvisVoiceAgent()
    activity._rt_session = None
    activity._rt_overlapping_speech_enabled = False
    activity.interrupt = lambda **kwargs: None
    activity._on_input_speech_started(InputSpeechStartedEvent())
    assert events == []
    session._update_user_state("speaking")
    assert events == ["speaking"]
