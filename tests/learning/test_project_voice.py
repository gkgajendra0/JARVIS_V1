"""Project conversation memory through the native-voice integration.

The bridge's accepted-turn order is simulated exactly: user activity starts,
Gemini may call ``prepare_project_turn`` before or after the final transcript,
or not at all; the transcript commits a USER turn; a spoken reply commits an
ASSISTANT turn. Storage, provenance, routing and the history grant are real.
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
from jarvis.voice import project_voice
from jarvis.voice.project_memory_lab import standard_history_source
from jarvis.voice.project_voice import (
    FALLBACK_INSTRUCTIONS,
    NO_TRANSCRIPT_INSTRUCTIONS,
    REPAIR_INSTRUCTIONS,
    VoiceProjectMemory,
)


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

        def evidence(self, text):
            with sqlite3.connect(path) as c:
                return {
                    r[0]
                    for r in c.execute(
                        "SELECT s.text FROM conversation_event_dependency d "
                        "JOIN conversation_event e ON e.event_id=d.event_id "
                        "JOIN conversation_event s ON s.event_id=d.source_event_id "
                        "WHERE e.text=?",
                        (text,),
                    )
                }

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


class FakeHandle:
    def __init__(self):
        self.interrupted = False

    def interrupt(self, **_):
        self.interrupted = True

    async def wait_for_playout(self):
        return None


class FakeSession:
    def __init__(self):
        self.replies = []

    def generate_reply(self, **kwargs):
        self.replies.append(kwargs["instructions"])


class Wake:
    """One wake session, driven the way LiveKitConversationBridge drives it."""

    def __init__(self, voice):
        self.voice = voice
        self.conversation = ConversationSession()
        self.conversation.start()
        self.turns = voice.session(self.conversation)
        self.session = FakeSession()
        self.turns.bind_session(self.session)

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

    def response(self):
        """Gemini starts a response: returns whether its audio may play."""
        handle = FakeHandle()
        self.turns.observe_speech(SimpleNamespace(speech_handle=handle))
        return self.turns.allow_response_audio(), handle

    async def ask(self, text, answer=None):
        self.speech()
        self.transcript(text)
        result = await self.turns.prepare()
        if answer is not None:
            assert self.response()[0]
            self.reply(answer)
        await self.voice.drain()
        return result

    def close(self):
        self.turns.close()


async def settle(voice):
    for _ in range(5):
        await voice.drain()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_spoken_turns_are_recorded_with_evidence_and_survive_restart(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    created = await wake.ask("create project called Nepal trip", "Done.")
    assert created["status"] == "ready" and created["action"] == "created"
    assert created["announcement"] == "Created project Nepal trip."
    said = await wake.ask("We will take the Jimny.", "Noted, the Jimny.")
    assert said["announcement"] == "" and said["action"] == "continued"
    wake.close()
    assert lab.rows() == [
        ("user", "create project called Nepal trip", "complete", "Nepal trip"),
        ("assistant", "Done.", "complete", "Nepal trip"),
        ("user", "We will take the Jimny.", "complete", "Nepal trip"),
        ("assistant", "Noted, the Jimny.", "complete", "Nepal trip"),
    ]
    await voice.aclose()
    restarted = await lab.runtime()
    wake = Wake(restarted)
    result = await wake.ask("Which vehicle are we taking?")
    assert result["announcement"] == "Resuming Nepal trip."
    assert result["action"] == "resumed"
    assert any("Jimny" in row["text"] for row in result["history"])
    assert voice.metrics.assistant_recorded == 2


@pytest.mark.asyncio
async def test_turns_are_saved_even_when_gemini_never_calls_the_tool(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    # Two consecutive utterances; Gemini calls the tool for neither.
    wake.speech()
    wake.transcript("create project called Nepal trip")
    wake.speech()
    wake.transcript("We will take the Jimny and the permits are sorted.")
    await settle(voice)
    assert lab.rows() == [
        ("user", "create project called Nepal trip", "complete", "Nepal trip"),
        (
            "user",
            "We will take the Jimny and the permits are sorted.",
            "complete",
            "Nepal trip",
        ),
    ]
    assert voice.metrics.saved_user_turns == 2 and voice.metrics.delivered == 0
    wake.close()
    await voice.aclose()
    # Restart: both survive and are given to the model on the next request.
    wake = Wake(await lab.runtime())
    result = await wake.ask("What is the status of the trip?")
    texts = [row["text"] for row in result["history"]]
    assert "We will take the Jimny and the permits are sorted." in texts


@pytest.mark.asyncio
async def test_tool_for_the_latest_turn_does_not_lose_the_earlier_one(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    wake.transcript("We will take the Jimny.")
    wake.speech()
    wake.transcript("And the permits are sorted.")
    result = await wake.turns.prepare()  # Gemini calls once, for the latest
    assert result["status"] == "ready"
    await settle(voice)
    users = [r[1] for r in lab.rows() if r[0] == "user"]
    assert users == [
        "create project called Nepal",
        "We will take the Jimny.",
        "And the permits are sorted.",
    ]


@pytest.mark.asyncio
async def test_unprepared_answer_is_withheld_then_repaired(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    wake.transcript("create project called Nepal")
    allowed, handle = wake.response()  # Gemini answers without the tool
    assert allowed is False and handle.interrupted
    await settle(voice)
    assert wake.session.replies == [REPAIR_INSTRUCTIONS]
    assert voice.metrics.repairs == 1
    # The repaired response calls the tool first, then answers.
    result = await wake.turns.prepare()
    assert result["announcement"] == "Created project Nepal."
    assert wake.response()[0] is True
    wake.reply("Created project Nepal.")
    await settle(voice)
    assert lab.rows()[-1] == (
        "assistant",
        "Created project Nepal.",
        "complete",
        "Nepal",
    )
    assert voice.metrics.fallbacks == 0


@pytest.mark.asyncio
async def test_second_unprepared_answer_gets_one_honest_fallback(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    wake.transcript("We will take the Jimny.")
    assert wake.response()[0] is False
    await settle(voice)
    assert wake.response()[0] is False  # the repair also skipped the tool
    await settle(voice)
    assert wake.session.replies == [REPAIR_INSTRUCTIONS, FALLBACK_INSTRUCTIONS]
    assert wake.response()[0] is True  # exactly one spoken answer: the fallback
    wake.reply("Sorry, I couldn't load the project memory for that.")
    await settle(voice)
    rows = lab.rows()
    # The user's words are saved; the fallback is not a project-derived reply.
    assert ("user", "We will take the Jimny.", "complete", "Nepal") in rows
    assert all("couldn't load" not in r[1] for r in rows)
    assert voice.metrics.fallbacks == 1


@pytest.mark.asyncio
async def test_no_transcript_gets_a_did_not_catch_that_reply(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "_SOURCE_WAIT_SECONDS", 0.05)
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    assert wake.response()[0] is False
    await asyncio.sleep(0.1)
    await settle(voice)
    assert wake.session.replies == [NO_TRANSCRIPT_INSTRUCTIONS]
    assert wake.response()[0] is True
    assert lab.rows() == []


@pytest.mark.asyncio
async def test_barge_in_cancels_a_pending_repair(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    wake.transcript("We will take the Jimny.")
    assert wake.response()[0] is False
    wake.speech()  # the owner talks again before the repair goes out
    await settle(voice)
    assert wake.session.replies == []
    wake.transcript("Actually the Thar.")
    result = await wake.turns.prepare()
    assert result["status"] == "ready" and wake.response()[0] is True


@pytest.mark.asyncio
async def test_wake_acknowledgement_before_any_speech_plays(lab):
    wake = Wake(await lab.runtime())
    assert wake.response()[0] is True
    assert wake.session.replies == []


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
async def test_only_new_history_is_sent_and_reply_evidence_covers_the_session(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    await wake.ask("We will take the Jimny.", "Okay.")
    wake.close()
    await voice.aclose()
    voice = await lab.runtime()
    wake = Wake(voice)
    first = await wake.ask("What is the plan?", "The Jimny.")
    second = await wake.ask("And the permits?", "Not discussed yet.")
    assert first["earlier_history_already_provided"] == 0
    assert second["earlier_history_already_provided"] >= len(first["history"])
    assert {r["text"] for r in second["history"]}.isdisjoint(
        {r["text"] for r in first["history"]}
    )
    sizes = voice.metrics.delivered_bytes
    assert sizes[1] < sizes[0]
    assert all("source_id" not in r for r in first["history"])
    # The second reply may restate anything given earlier in the session.
    assert "We will take the Jimny." in lab.evidence("Not discussed yet.")


@pytest.mark.asyncio
async def test_switch_result_names_the_previous_project(lab):
    wake = Wake(await lab.runtime())
    await wake.ask("create project called Nepal", "Done.")
    await wake.ask("create project called Interview", "Done.")
    switched = await wake.ask("switch to Nepal", "Switched to Nepal.")
    assert switched["action"] == "switched"
    assert switched["previous_project"] == "Interview"
    assert switched["announcement"] == "Switched to Nepal."
    same = await wake.ask("switch to Nepal")
    assert same["action"] == "continued" and "previous_project" not in same


@pytest.mark.asyncio
async def test_question_about_another_project_reads_it_and_stays(lab):
    wake = Wake(await lab.runtime())
    await wake.ask("create project called Nepal", "Done.")
    await wake.ask("We will take the Jimny.", "Okay.")
    await wake.ask("create project called Interview", "Done.")
    asked = await wake.ask("What's the status of my Nepal trip?", "The Jimny.")
    assert asked["project"] == "Interview" and asked["announcement"] == ""
    assert asked["referenced_projects"] == ["Nepal"]
    # Jimny was already delivered earlier in this session, so it is counted,
    # not resent; on a fresh session it arrives labelled from_project.
    assert lab.titles() == ["Interview", "Nepal"]
    assert lab.rows()[-1] == ("assistant", "The Jimny.", "complete", "Interview")
    fresh = Wake(wake.voice)
    again = await fresh.ask("What's the status of my Nepal trip?")
    labelled = [r for r in again["history"] if r.get("from_project") == "Nepal"]
    assert any("Jimny" in r["text"] for r in labelled)


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
    assert (await asyncio.wait_for(pending, 0.5))["status"] == "unavailable"
    wake.transcript("We will take the Jimny and")
    ready = await wake.turns.prepare()
    assert ready["status"] == "ready"
    assert wake.response()[0] is True
    wake.reply("Got it, the Ji", interrupted=True)
    await voice.drain()
    assert lab.rows()[-1] == ("assistant", "Got it, the Ji", "partial", "Nepal")


@pytest.mark.asyncio
async def test_replies_are_attributed_only_to_their_own_delivered_request(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    wake.transcript("create project called Nepal")
    wake.reply("Let me check.")  # preamble before the tool ran
    await wake.turns.prepare()
    wake.speech()
    wake.transcript("Never mind.")  # newer turn: saved, never delivered
    wake.reply("Okay.")  # belongs to the undelivered turn: not recorded
    await settle(voice)
    assert [(r[0], r[1]) for r in lab.rows()] == [
        ("user", "create project called Nepal"),
        ("user", "Never mind."),
    ]
    assert voice.metrics.assistant_skipped == 2
    wake.close()
    assert voice.metrics.undelivered_user_turns == 1


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
async def test_closing_the_wake_session_does_not_lose_an_in_flight_save(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    wake.speech()
    wake.transcript("Last thing: the permits are sorted.")
    wake.close()  # sleep immediately after speaking
    await voice.aclose()
    assert ("user", "Last thing: the permits are sorted.", "complete", "Nepal") in (
        lab.rows()
    )


@pytest.mark.asyncio
async def test_forget_between_voice_runs_is_respected(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Interview", "Done.")
    await wake.ask("My interview topic is SQL window functions.", "Good luck.")
    await wake.ask("create project called Nepal", "Done.")
    wake.close()
    await voice.aclose()
    fresh = Wake(await lab.runtime())
    recalled = await fresh.ask("What is my interview topic?", "SQL window functions.")
    # Before forgetting, a question naming Interview reads it as labelled evidence.
    assert "SQL window functions" in json.dumps(recalled)
    fresh.close()
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
    assert excluded["status"] == "not_saved" and "history" not in excluded
    assert "salary" not in json.dumps(lab.rows())
    assert voice.metrics.not_saved == 1


def test_realtime_model_is_made_blocking_or_refused():
    calls = []
    llm = SimpleNamespace(update_options=lambda **kw: calls.append(kw))
    VoiceProjectMemory.configure_realtime_model(llm)
    assert list(calls[0]) == ["tool_behavior"]
    value = calls[0]["tool_behavior"]
    assert "BLOCKING" in repr(value) + str(value)
    assert "NON_BLOCKING" not in repr(value) + str(value)
    with pytest.raises(TypeError, match="blocking-tool model"):
        VoiceProjectMemory.configure_realtime_model(SimpleNamespace())


def test_session_bundle_adds_the_project_tool_only_when_enabled(monkeypatch):
    import jarvis.voice.canonical_active_speaker_runtime as active

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
    assert "call prepare_project_turn first" in agent.instructions
    assert "prepare_project_turn" not in JarvisVoiceAgent(tools=[]).instructions


@pytest.mark.skipif(not _real_livekit(), reason="needs the real LiveKit SDK")
@pytest.mark.asyncio
async def test_real_audio_gate_forwards_only_allowed_segments():
    from livekit import rtc
    from livekit.agents.voice.io import AudioOutput

    from jarvis.voice.project_voice_audio import ProjectAudioGate

    class Sink(AudioOutput):
        def __init__(self):
            super().__init__(label="sink", sample_rate=24000, next_in_chain=None)
            self.frames = 0

        async def capture_frame(self, frame):
            await super().capture_frame(frame)
            self.frames += 1

        def flush(self):
            super().flush()

        def clear_buffer(self):
            pass

    decisions = iter([False, True])
    asked = []

    class Turns:
        def allow_response_audio(self):
            asked.append(1)
            return next(decisions)

    sink = Sink()
    gate = ProjectAudioGate(sink, Turns())
    frame = rtc.AudioFrame(b"\0\0" * 240, 24000, 1, 240)
    for _ in range(3):
        await gate.capture_frame(frame)  # blocked segment: decided once
    gate.flush()
    assert sink.frames == 0 and len(asked) == 1
    for _ in range(2):
        await gate.capture_frame(frame)
    gate.flush()
    assert sink.frames == 2 and len(asked) == 2
    assert gate.captured_playout_segments == 1  # only the heard answer counts


@pytest.mark.asyncio
async def test_reply_evidence_includes_rows_delivered_earlier_from_another_project(lab):
    """Gemini still holds rows from earlier results; forgetting them must
    also remove a later reply that may restate them (provenance)."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Interview", "Done.")
    await wake.ask("My interview topic is SQL window functions.", "Good luck.")
    await wake.ask("create project called Nepal", "Done.")
    wake.close()
    await voice.aclose()
    wake = Wake(await lab.runtime())
    await wake.ask("What is my interview topic?", "SQL window functions.")
    later = await wake.ask("We will take the Jimny.", "SQL and the Jimny, noted.")
    assert "referenced_projects" not in later  # this packet has no Interview rows
    assert "My interview topic is SQL window functions." in lab.evidence(
        "SQL and the Jimny, noted."
    )
    wake.close()
    controls = ProjectControls((await lab.runtime()).access)
    catalog = await controls.access.catalog()
    interview = next(e for e in catalog.entries if e.title == "Interview")
    inspected = await controls.inspect_project(interview.selection.project_id)
    await controls.forget_project(
        interview.selection.project_id, expected_revision=inspected.archive_revision
    )
    assert all("SQL" not in r[1] for r in lab.rows())


@pytest.mark.asyncio
async def test_a_blocked_response_is_interrupted_and_counted_once(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.speech()
    wake.transcript("create project called Nepal")
    allowed, _handle = wake.response()
    assert allowed is False
    # Trailing frames of the same response (LiveKit re-decides after clear_buffer).
    assert wake.turns.allow_response_audio() is False
    assert wake.turns.allow_response_audio() is False
    assert voice.metrics.unprepared_responses_blocked == 1
    await settle(voice)
    assert wake.session.replies == [REPAIR_INSTRUCTIONS]


@pytest.mark.asyncio
async def test_new_utterance_without_new_vad_activity_is_still_gated(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal", "Done.")
    # Local VAD missed the start of the next utterance: same activity epoch.
    wake.transcript("We will take the Jimny.")
    assert wake.response()[0] is False
    await settle(voice)
    assert wake.session.replies == [REPAIR_INSTRUCTIONS]
    result = await wake.turns.prepare()
    assert result["status"] == "ready" and wake.response()[0] is True
    assert voice.metrics.saved_user_turns == 2
