"""Project conversation memory through the native-voice tool boundary.

The bridge's accepted-turn order is simulated exactly: user activity starts,
Gemini may call ``prepare_project_turn`` before or after the final transcript,
the transcript commits a USER turn, then the spoken reply commits an ASSISTANT
turn. Storage, provenance, routing and the history grant are real.
"""

import asyncio
import inspect
import json
import sqlite3
from types import SimpleNamespace

import pytest
import pytest_asyncio

from jarvis.authority.conversation_history import ConversationHistoryAuthority
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.project_controls import ProjectControls
from jarvis.memory.project_conversation_store import ProjectConversationStore
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.project_memory_lab import standard_history_source
from jarvis.voice.project_voice import VoiceProjectMemory


@pytest_asyncio.fixture
async def lab(tmp_path, authority_parts):
    path = tmp_path / "history.db"
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner().apply(connection)
    writer = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="w")
    reader = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="r")
    issuer = ConversationHistoryAuthority(authority_parts.broker)
    store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)
    memory = SimpleNamespace(
        project_conversations=store,
        bind_conversation_history_authority=store.bind_authority,
    )
    capability = SimpleNamespace(conversation_history_authority=issuer)
    runtimes = []

    class Lab:
        db = path

        async def runtime(self):
            """One voice-runtime process: a new grant over the same archive."""
            voice = VoiceProjectMemory(
                memory, capability, source_clearance=standard_history_source
            )
            await voice.start(
                open_grant=lambda: issuer.open(f"voice-{len(runtimes)}", "gemini")
            )
            runtimes.append(voice)
            return voice

        def rows(self):
            with sqlite3.connect(path) as c:
                return c.execute(
                    "SELECT e.role, e.text, e.delivery, w.title FROM conversation_event e "
                    "JOIN conversation_thread t ON t.thread_id=e.thread_id "
                    "JOIN conversation_workspace w ON w.project_id=t.project_id "
                    "WHERE e.role IN ('user','assistant') ORDER BY e.sequence"
                ).fetchall()

        def titles(self):
            with sqlite3.connect(path) as c:
                return sorted(
                    r[0]
                    for r in c.execute(
                        "SELECT title FROM conversation_workspace WHERE forgotten_at IS NULL"
                    )
                )

    try:
        yield Lab()
    finally:
        for voice in runtimes:
            await voice.aclose()
        await reader.close()
        await writer.close()


class Wake:
    """One wake session, driven the way LiveKitConversationBridge drives it."""

    def __init__(self, voice):
        self.voice = voice
        self.conversation = ConversationSession()
        self.conversation.start()
        self.turns = voice.session(self.conversation)

    def speech(self):
        self.conversation.begin_user_activity()
        self.turns.observe_activity()

    def transcript(self, text):
        turn = self.conversation.accept_turn(ConversationRole.USER, text)
        self.turns.observe_turn(turn)
        return turn

    def reply(self, text, *, interrupted=False):
        turn = self.conversation.accept_turn(
            ConversationRole.ASSISTANT, text, interrupted=interrupted
        )
        self.turns.observe_turn(turn)
        return turn

    async def ask(self, text, answer=None):
        self.speech()
        self.transcript(text)
        result = await self.turns.prepare()
        if answer is not None:
            self.reply(answer)
        await self.voice.drain()
        return result

    def close(self):
        self.turns.close()


@pytest.mark.asyncio
async def test_spoken_turns_are_recorded_with_evidence_and_survive_restart(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    created = await wake.ask("create project called Nepal trip", "Done.")
    assert created["status"] == "ready"
    assert created["announcement"] == "Created project Nepal trip."
    said = await wake.ask("We will take the Jimny.", "Noted, the Jimny.")
    assert said["announcement"] == ""
    wake.close()
    assert lab.rows() == [
        ("user", "create project called Nepal trip", "complete", "Nepal trip"),
        ("assistant", "Done.", "complete", "Nepal trip"),
        ("user", "We will take the Jimny.", "complete", "Nepal trip"),
        ("assistant", "Noted, the Jimny.", "complete", "Nepal trip"),
    ]
    await voice.aclose()
    # Restart: new process, new grant, same encrypted archive.
    restarted = await lab.runtime()
    wake = Wake(restarted)
    result = await wake.ask("Which vehicle are we taking?")
    assert result["announcement"] == "Resuming Nepal trip."
    assert "Jimny" in json.dumps(result["context"])
    assert result["context"]["project_title"] == "Nepal trip"
    assert restarted.metrics.assistant_recorded == 0
    assert voice.metrics.assistant_recorded == 2


@pytest.mark.asyncio
async def test_tool_called_before_the_transcript_waits_for_the_committed_words(lab):
    wake = Wake(await lab.runtime())
    wake.speech()
    pending = asyncio.create_task(wake.turns.prepare())
    await asyncio.sleep(0.05)
    assert not pending.done()  # never answers from the model's restatement
    wake.transcript("create project called Goa")
    result = await pending
    assert result["announcement"] == "Created project Goa."
    assert lab.titles() == ["Goa"]


@pytest.mark.asyncio
async def test_duplicate_tool_calls_and_reply_events_record_once(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    first = await wake.ask("create project called Nepal")
    again = await wake.turns.prepare()
    assert again is first
    reply = wake.reply("Created it.")
    wake.turns.observe_turn(reply)  # a duplicate committed-item event
    wake.turns.observe_turn(wake.conversation.turns[0])  # duplicate transcript
    await voice.drain()
    assert [r[0] for r in lab.rows()] == ["user", "assistant"]
    assert voice.metrics.duplicate_calls == 1
    assert voice.metrics.user_turns == 1
    assert voice.metrics.assistant_recorded == 1


@pytest.mark.asyncio
async def test_question_about_another_project_reads_it_and_stays(lab):
    wake = Wake(await lab.runtime())
    await wake.ask("create project called Nepal", "Done.")
    await wake.ask("We will take the Jimny.", "Okay.")
    await wake.ask("create project called Interview", "Done.")
    asked = await wake.ask("What's the status of my Nepal trip?", "The Jimny.")
    assert asked["project"] == "Interview" and asked["announcement"] == ""
    assert asked["context"]["routing"]["referenced_projects"] == ["Nepal"]
    labelled = [
        r for r in asked["context"]["sources"] if r.get("from_project") == "Nepal"
    ]
    assert any("Jimny" in r["text"] for r in labelled)
    assert lab.titles() == ["Interview", "Nepal"]
    # The answer is recorded in the project the owner stayed in.
    assert lab.rows()[-1] == ("assistant", "The Jimny.", "complete", "Interview")


@pytest.mark.asyncio
async def test_ordinary_questions_and_unknown_switches_never_create(lab):
    wake = Wake(await lab.runtime())
    await wake.ask("create project called Nepal", "Done.")
    plain = await wake.ask("What is the status of my Tokyo trip?", "I don't know.")
    assert plain["status"] == "ready" and plain["project"] == "Nepal"
    unknown = await wake.ask("switch to tokyo", "Which project?")
    assert unknown["status"] == "clarification"
    assert "No project called 'tokyo'" in unknown["question"]
    assert lab.titles() == ["Nepal"]
    # A clarification's spoken reply is not attributed to any project context.
    assert ("assistant", "Which project?", "complete", "Nepal") not in lab.rows()


@pytest.mark.asyncio
async def test_barge_in_before_transcript_and_interrupted_reply(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    pending = asyncio.create_task(wake.turns.prepare())
    await asyncio.sleep(0.01)
    wake.speech()  # the owner starts speaking again before the transcript
    # Released at once by the new activity, not by the 3 s source timeout.
    assert (await asyncio.wait_for(pending, 0.5))["status"] == "unavailable"
    wake.transcript("We will take the Jimny and")
    ready = await wake.turns.prepare()
    assert ready["status"] == "ready"
    wake.reply("Got it, the Ji", interrupted=True)
    await voice.drain()
    assert lab.rows()[-1] == ("assistant", "Got it, the Ji", "partial", "Nepal")
    assert voice.metrics.interrupted == 1


@pytest.mark.asyncio
async def test_replies_are_attributed_only_to_their_own_prepared_request(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    wake.transcript("create project called Nepal")
    wake.reply("Let me check.")  # preamble before the tool ran
    await wake.turns.prepare()
    wake.speech()
    wake.transcript("Never mind.")  # newer turn, never prepared
    wake.reply("Okay.")  # belongs to the unprepared turn: not recorded
    await voice.drain()
    assert [(r[0], r[1]) for r in lab.rows()] == [
        ("user", "create project called Nepal")
    ]
    assert voice.metrics.assistant_skipped == 2
    wake.close()
    assert voice.metrics.unprepared_user_turns == 1


@pytest.mark.asyncio
async def test_cancelled_tool_and_failed_response_leave_a_usable_session(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    pending = asyncio.create_task(wake.turns.prepare())
    await asyncio.sleep(0.01)
    pending.cancel()  # Gemini cancelled the function call
    with pytest.raises(asyncio.CancelledError):
        await pending
    wake.transcript("The permits are sorted.")
    assert (await wake.turns.prepare())["status"] == "ready"
    # Gemini fails to answer: no ASSISTANT turn. The next turn still works.
    nxt = await wake.ask("And the Jimny?", "Jimny it is.")
    assert nxt["status"] == "ready"
    assert [r[1] for r in lab.rows()] == [
        "create project called Nepal",
        "Done.",
        "The permits are sorted.",
        "And the Jimny?",
        "Jimny it is.",
    ]


@pytest.mark.asyncio
async def test_forget_between_voice_runs_is_respected(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Interview", "Done.")
    await wake.ask("My interview topic is SQL window functions.", "Good luck.")
    await wake.ask("create project called Nepal", "Done.")
    recalled = await wake.ask("What is my interview topic?", "SQL window functions.")
    # Before forgetting, a question naming Interview reads it as labelled evidence.
    assert "SQL window functions" in json.dumps(recalled["context"])
    wake.close()
    await voice.aclose()
    # The owner forgets Interview in the text lab between voice runs.
    controls = ProjectControls((await lab.runtime()).access)
    catalog = await controls.access.catalog()
    interview = next(e for e in catalog.entries if e.title == "Interview")
    inspected = await controls.inspect_project(interview.selection.project_id)
    await controls.forget_project(
        interview.selection.project_id, expected_revision=inspected.archive_revision
    )
    wake = Wake(await lab.runtime())
    after = await wake.ask("What is my interview topic?")
    assert "SQL window functions" not in json.dumps(after)
    assert after["project"] == "Nepal"
    assert lab.titles() == ["Nepal"]


@pytest.mark.asyncio
async def test_excluded_source_is_not_saved_and_not_given_context(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    excluded = await wake.ask("My salary is 50 lakh.", "Okay.")
    assert excluded["status"] == "not_saved" and "context" not in excluded
    assert "salary" not in json.dumps(lab.rows())
    assert voice.metrics.not_saved == 1


@pytest.mark.asyncio
async def test_unprepared_turns_are_counted_and_never_recorded(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    wake.transcript("Hello Jarvis")
    wake.reply("Hello!")  # Gemini answered without calling the tool
    await voice.drain()
    wake.close()
    assert lab.rows() == [] and lab.titles() == []
    snapshot = voice.metrics.snapshot()
    assert snapshot["unprepared_user_turns"] == 1
    assert snapshot["prepared"] == 0


def test_session_bundle_adds_the_project_tool_only_when_enabled(monkeypatch):
    import jarvis.voice.canonical_active_speaker_runtime as active
    from jarvis.voice import project_voice

    conversation = object()
    marker = object()

    class FakeTools:
        def __init__(self, turns):
            self.turns = turns

        @property
        def tools(self):
            return [(marker, self.turns)]

    monkeypatch.setattr(project_voice, "VoiceProjectTools", FakeTools)

    def bundle(getter):
        return active._SessionToolBundle(
            None,
            lambda: conversation,
            memory_runtime=None,
            memory_query_coordinator=None,
            research_service=None,
            capability_runtime=None,
            project_turns_getter=getter,
        )

    assert bundle(lambda: None).tools == []
    turns = object()
    assert bundle(lambda: turns).tools == [(marker, turns)]
    # Default: no getter, no project tool (normal Jarvis).
    default = active._SessionToolBundle(
        None,
        lambda: conversation,
        memory_runtime=None,
        memory_query_coordinator=None,
        research_service=None,
        capability_runtime=None,
    )
    assert default.tools == []


def test_production_entry_point_never_enables_project_voice():
    import jarvis.voice.production_runtime as production

    for entry in (production.main, production._run_from_configuration):
        source = inspect.getsource(entry)
        assert "project_memory" not in source and "voice_session_observer" not in source
    assert "project_voice" not in inspect.getsource(production)
    signature = inspect.signature(production.build_production_voice_runtime)
    assert signature.parameters["project_memory_factory"].default is None
    assert signature.parameters["voice_session_observer"].default is None


def _real_livekit():
    from livekit.agents import function_tool

    return inspect.isfunction(function_tool)


@pytest.mark.skipif(not _real_livekit(), reason="needs the real LiveKit SDK")
def test_real_tool_schema_and_agent_instructions():
    from jarvis.voice.agent import JarvisVoiceAgent
    from jarvis.voice.project_voice import VoiceProjectTools

    tools = VoiceProjectTools(object()).tools
    assert [t.id for t in tools] == ["prepare_project_turn"]
    agent = JarvisVoiceAgent(tools=tools)
    assert "prepare_project_turn first" in agent.instructions
    assert "prepare_project_turn" not in JarvisVoiceAgent(tools=[]).instructions


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


def test_usage_meter_records_latency_tokens_and_tools_without_content(
    tmp_path, monkeypatch
):
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
    session.emit(
        "metrics_collected",
        metrics=SimpleNamespace(
            type="realtime_model_metrics",
            input_tokens=900,
            output_tokens=120,
            total_tokens=1020,
            input_token_details=SimpleNamespace(audio_tokens=300, text_tokens=600),
        ),
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
    assert row["tokens"] == {
        "input": 900,
        "output": 120,
        "total": 1020,
        "audio_in": 300,
        "text_in": 600,
    }
    assert row["tool_calls"] == {"prepare_project_turn": 1}
    assert "Goa" not in text and "secret" not in text
    with pytest.raises(ValueError):
        VoiceUsageMeter(tmp_path / "x", mode="production")


def test_voice_lab_refuses_memory_outside_the_lab_and_disables_paid(
    tmp_path, monkeypatch
):
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
    config = voice_lab_config(replace_config(JarvisConfig(), ai_provider="gemini"))
    assert config.memory_enabled and not config.gemini_fallback.enabled
    assert config.personal_context_mode == "off"
    assert not config.memory_semantic_recall_enabled
    assert not config.work_orchestration_enabled


def replace_config(config, **changes):
    from dataclasses import replace

    return replace(config, **changes)


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
