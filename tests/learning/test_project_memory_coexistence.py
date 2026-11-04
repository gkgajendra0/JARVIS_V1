"""Project memory together with Gemini paid fallback and personal context APPLY.

B2 (provider handoff) runs the REAL GeminiLiveHandoff, LiveKit AgentSession and
bridge against the real project archive; only the provider transport is fake
(tests.gemini_fallback.live_helpers). B3 (personal context / learning APPLY)
runs the REAL PersonalContextSession on canonical SQLite memory, sharing one
conversation with the real VoiceProjectTurns.

B2  A model switch (quota -> paid, paid -> free recovery, fresh-session
    recovery) gives the new model the same BLOCKING tool behaviour and the
    project context this session already holds, as one inert completed
    exchange; canonical turns, archive rows and tool runs are not duplicated;
    forgotten rows are never restored; an unconfigurable model aborts the
    switch instead of running with non-blocking tools.
B3  Replies built from released personal facts are not saved to project
    history (the question is); a response the project gate withheld never
    retires the personal session; a barge-in still does; the production
    activation check no longer refuses fallback or APPLY.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from google.genai.errors import APIError
from livekit.agents import UserInputTranscribedEvent, llm
from test_project_voice import FakeHandle, Wake, settle
from test_project_voice_fast_path import nepal

from jarvis.voice.project_voice import HANDOFF_CONTEXT_MAX_CHARS

lab = project_voice_tests.lab


# -- B2: provider handoff -----------------------------------------------------


def blocking_models(models):
    """Provider models that record model-level options (tool behaviour)."""
    from tests.gemini_fallback.live_helpers import ProviderModel

    from jarvis.voice.gemini_transport import GuardedGeminiRealtimeModel

    class OptionModel(ProviderModel):
        def __init__(self, slot):
            super().__init__(slot)
            self.options = {}

        def update_options(self, **kwargs):
            self.options.update(kwargs)

    def factory(config, *, target, transport_state):
        new = OptionModel("paid" if ".paid." in target.target_id else "free")
        wrapped = GuardedGeminiRealtimeModel(new, transport_state)
        models.append((target, new, wrapped))
        return wrapped

    return factory


async def handoff_wake(lab, tmp_path, monkeypatch):
    from tests.gemini_fallback.test_live_handoff import setup

    voice = await nepal(lab)  # "Nepal trip": "We will take the Jimny." ...
    session, bridge, raw, handoff, models, _admission, _observer = await setup(
        tmp_path, monkeypatch
    )
    models.clear()
    handoff.model_factory = blocking_models(models)
    turns = voice.session(bridge.conversation)
    turns.bind_session(session)
    turns.bind_injection_registry(bridge.register_restored_context)
    bridge.add_accepted_turn_observer(turns.observe_turn)
    session.on("speech_created", turns.observe_speech)
    # Exactly the production wiring (CanonicalActiveSpeakerRuntimeController).
    handoff.add_model_configurer(voice.configure_realtime_model)
    handoff.add_context_provider(
        turns.handoff_context_items, turns.observe_transport_switch
    )
    await turns.preload(session.current_agent)
    return SimpleNamespace(
        voice=voice,
        session=session,
        bridge=bridge,
        raw=raw,
        handoff=handoff,
        models=models,
        turns=turns,
    )


def project_items(agent):
    return [
        m.text_content
        for m in agent.chat_ctx.messages()
        if m.id.startswith("jarvis:project-context:")
    ]


def quota(raw):
    error = llm.RealtimeModelError(
        timestamp=1, label="synthetic quota", error=APIError(429, {}), recoverable=False
    )
    raw.sessions[0].emit("error", error)
    return error


async def say(w, text):
    w.session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(transcript=text, is_final=True, item_id=text),
    )
    await settle(w.voice)


@pytest.mark.asyncio
async def test_b2_paid_fallback_keeps_project_context_and_blocking_tools(
    lab, tmp_path, monkeypatch
):
    w = await handoff_wake(lab, tmp_path, monkeypatch)
    try:
        assert "We will take the Jimny." in "".join(
            project_items(w.session.current_agent)
        )
        rows_before = lab.rows()
        await say(w, "Which vehicle are we taking?")
        turns_before = list(w.bridge.conversation.turns)
        error = quota(w.raw)
        assert error.recoverable
        await asyncio.wait_for(w.handoff.task, 2)
        ((target, new_model, _),) = w.models
        assert target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        # Same blocking tool behaviour on the new model, before it connects.
        assert str(new_model.options["tool_behavior"]).endswith("BLOCKING")
        # The new model holds the project rows the gate believes it has.
        restored = project_items(w.session.current_agent)
        assert restored and "We will take the Jimny." in restored[-1]
        assert "Current project: Nepal trip." in restored[-1]
        assert w.turns.metrics.handoff_restores == 1
        # Nothing duplicated: canonical turns, archive rows, the request.
        assert list(w.bridge.conversation.turns) == turns_before
        await settle(w.voice)
        assert lab.rows() == rows_before + [
            ("user", "Which vehicle are we taking?", "complete", "Nepal trip")
        ]
        await asyncio.wait_for(new_model.sessions[0].reply_started.wait(), 1)
        assert new_model.sessions[0].replies == 1  # one continuation, no replay
        # The restored context is inert: never accepted as a turn.
        assert all("Project memory" not in t.text for t in w.bridge.conversation.turns)
    finally:
        w.handoff.close()
        await w.session.aclose()


@pytest.mark.asyncio
async def test_b2_fresh_session_recovery_also_restores_project_context(
    lab, tmp_path, monkeypatch
):
    """Same key (free), new physical session after a 1011 transport fault."""
    w = await handoff_wake(lab, tmp_path, monkeypatch)
    try:
        await say(w, "Which vehicle are we taking?")
        w.handoff._completed_tools = True  # answered already: no continuation
        error = llm.RealtimeModelError(
            timestamp=1,
            label="disconnect",
            error=APIError(1011, {"message": "Internal error encountered"}),
            recoverable=False,
        )
        w.raw.sessions[0].emit("error", error)
        await asyncio.wait_for(w.handoff.task, 3)
        ((target, new_model, _),) = w.models
        assert target.credential_ref == "GOOGLE_API_KEY"
        assert str(new_model.options["tool_behavior"]).endswith("BLOCKING")
        assert "We will take the Jimny." in project_items(w.session.current_agent)[-1]
        assert new_model.sessions[0].replies == 0  # no replay of the request
        assert w.turns.metrics.handoff_restores == 1
    finally:
        w.handoff.close()
        await w.session.aclose()


@pytest.mark.asyncio
async def test_b2_forgotten_rows_are_never_restored_by_a_handoff(
    lab, tmp_path, monkeypatch
):
    w = await handoff_wake(lab, tmp_path, monkeypatch)
    try:
        await say(w, "Forget that we will take the Jimny.")
        result = await w.turns.forget_history("Jimny")
        assert result["status"] == "forgotten"
        items = w.turns.handoff_context_items()
        assert items and "Jimny" not in items[0].text_content
        assert "The permits are sorted." in items[0].text_content
    finally:
        w.handoff.close()
        await w.session.aclose()


@pytest.mark.asyncio
async def test_b2_an_unconfigurable_new_model_aborts_the_switch(
    lab, tmp_path, monkeypatch
):
    from tests.gemini_fallback.live_helpers import ProviderModel

    from jarvis.voice.gemini_transport import GuardedGeminiRealtimeModel

    w = await handoff_wake(lab, tmp_path, monkeypatch)
    plain = []

    def factory(config, *, target, transport_state):  # no update_options at all
        wrapped = GuardedGeminiRealtimeModel(ProviderModel("paid"), transport_state)
        plain.append(wrapped)
        return wrapped

    w.handoff.model_factory = factory
    try:
        await say(w, "Which vehicle are we taking?")
        old_agent = w.session.current_agent
        quota(w.raw)
        await asyncio.wait_for(w.handoff.task, 2)
        assert plain and plain[0].state.active is False  # retired, never used
        assert w.handoff.last_reason == "handoff_unavailable"
        assert w.session.current_agent is old_agent or w.session.current_agent is None
    finally:
        w.handoff.close()
        await w.session.aclose()


@pytest.mark.asyncio
async def test_b2_restored_context_is_bounded_and_gate_stays_truthful(lab):
    voice = await nepal(lab)
    wake = Wake(voice)
    for number in range(400):  # far more than any handoff should resend
        wake.turns._remember_delivered(
            [f"row-{number}"],
            [
                {
                    "role": "user",
                    "date": "2026-11-03",
                    "text": f"Note {number}: " + "x" * 40,
                }
            ],
        )
    (message, ack) = wake.turns.handoff_context_items()
    assert len(message.text_content) <= HANDOFF_CONTEXT_MAX_CHARS + 300
    assert "Note 399" in message.text_content  # newest kept
    assert "Note 0:" not in message.text_content
    # What was not resent is no longer counted as given: the gate resends it.
    assert "row-0" not in wake.turns._delivered_ids
    assert "row-399" in wake.turns._delivered_ids
    assert ack.role == "assistant" and ack.text_content == "Noted."
    # Deterministic ids: a transport replaying the context again is not new.
    again = wake.turns.handoff_context_items()
    assert again[0].id == message.id


def test_b2_initial_guarded_model_accepts_blocking_tools():
    """Production with fallback ON wraps the model: project memory configures
    it at wake (previously a TypeError: the wrapper had no update_options)."""
    from tests.gemini_fallback.live_helpers import ProviderModel

    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )
    from jarvis.voice.project_voice import VoiceProjectMemory

    class OptionModel(ProviderModel):
        options = None

        def update_options(self, **kwargs):
            self.options = kwargs

    inner = OptionModel()
    guarded = GuardedGeminiRealtimeModel(
        inner, GeminiTransportState(epoch=0, current_epoch=lambda: 0)
    )
    VoiceProjectMemory.configure_realtime_model(guarded)
    assert str(inner.options["tool_behavior"]).endswith("BLOCKING")
    with pytest.raises(TypeError):
        VoiceProjectMemory.configure_realtime_model(
            GuardedGeminiRealtimeModel(
                ProviderModel(), GeminiTransportState(epoch=0, current_epoch=lambda: 0)
            )
        )


def test_b2_controlled_paid_sessions_are_blocking_and_say_so():
    from jarvis.voice.gemini_live_model import ControlledGeminiLiveModel

    model = object.__new__(ControlledGeminiLiveModel)
    from google.genai import types

    model.update_options(tool_behavior=types.Behavior.BLOCKING)
    with pytest.raises(TypeError):
        model.update_options(tool_behavior=types.Behavior.NON_BLOCKING)


# -- B3: personal context / learning APPLY ---------------------------------------


async def personal_wake(lab, tmp_path):
    import sqlite3

    from tests.test_personal_context_runtime import NOW, Authority, source

    from jarvis.memory.lifecycle import MemoryLifecycleService
    from jarvis.memory.migration_runner import MemoryMigrationRunner
    from jarvis.memory.query import CanonicalMemoryReader
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.memory.service import MemoryService
    from jarvis.memory.worker import SerialConnectionWorker
    from jarvis.voice.personal_context import PersonalContextSession

    path = tmp_path / "canonical.db"
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner(clock=lambda: NOW).apply(connection)

    def connect():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    writer = SerialConnectionWorker(connect, thread_name="b3-writer")
    reader = SerialConnectionWorker(connect, thread_name="b3-reader")
    service = MemoryService(
        MemoryLifecycleService(writer), CanonicalMemoryReader(reader)
    )
    await service.remember_text(
        predicate="diet preference", value="vegetarian", source=source("diet")
    )
    voice = await nepal(lab)
    wake = Wake(voice)
    retired = []
    personal = PersonalContextSession(
        conversation=wake.conversation,
        retrieval=SemanticRetrievalService(reader),
        authority=Authority(),
        retire=lambda: retired.append(personal.retirement_reason),
    )
    # Exactly the production wiring.
    personal.add_release_observer(wake.turns.observe_personal_release)
    return SimpleNamespace(
        voice=voice,
        wake=wake,
        personal=personal,
        retired=retired,
        close=lambda: (reader.close(), writer.close()),
    )


@pytest.mark.asyncio
async def test_b3_personal_answers_are_not_saved_to_project_history(lab, tmp_path):
    b = await personal_wake(lab, tmp_path)
    wake = b.wake
    try:
        question = "What should I eat on the Nepal trip?"
        wake.speech()
        wake.transcript(question)
        catalog = await b.personal.catalog()  # owner facts released (permit)
        packet = await b.personal.read(catalog["catalog_id"], [0])
        assert "vegetarian" in str(packet)
        assert (await wake.turns.prepare())["status"] == "ready"
        assert wake.response()[0] is True
        wake.reply("As a vegetarian, try dal bhat in Kathmandu.")
        await settle(b.voice)
        texts = [r[1] for r in lab.rows()]
        assert question in texts  # the owner's question is project history
        assert not any("vegetarian" in t for t in texts)  # the released fact is not
        assert b.voice.metrics.personal_replies_not_saved == 1
        # A later ordinary answer in the same wake is saved as usual.
        await wake.ask("And the permits?", "The permits are sorted.")
        assert ("assistant", "The permits are sorted.", "complete", "Nepal trip") in (
            lab.rows()
        )
    finally:
        b.personal.close()


@pytest.mark.asyncio
async def test_b3_canonical_corrections_stay_canonical_and_survive_restart(
    lab, tmp_path
):
    """A correction committed through personal context: the owner's words are
    project history, the confirmation that restates the fact is not; after a
    restart the project preload holds no released personal fact."""
    b = await personal_wake(lab, tmp_path)
    wake = b.wake
    try:
        said = "Correction: my diet preference is vegan now."
        wake.speech()
        wake.transcript(said)
        b.personal.mutation_committed()  # canonical correction committed
        assert (await wake.turns.prepare())["status"] == "ready"
        assert wake.response()[0] is True
        wake.reply("Updated: your diet preference is vegan.")
        await settle(b.voice)
        texts = [r[1] for r in lab.rows()]
        assert said in texts
        assert "Updated: your diet preference is vegan." not in texts
        wake.close()
        await b.voice.aclose()
        restarted = await lab.runtime()
        fresh = Wake(restarted)
        result = await fresh.ask("Remind me where we are.")
        joined = " ".join(r["text"] for r in result["history"])
        assert "Updated: your diet" not in joined and "vegetarian" not in joined
    finally:
        b.personal.close()


@pytest.mark.asyncio
async def test_b3_a_project_withheld_response_never_retires_the_personal_session(
    lab, tmp_path
):
    from jarvis.voice.canonical_active_speaker_runtime import personal_speech_finished

    b = await personal_wake(lab, tmp_path)
    wake = b.wake
    try:
        wake.speech()
        wake.transcript("create project called Interview prep")  # needs the tool
        await b.personal.catalog()
        assert b.personal.protected
        allowed, handle = wake.response()  # Gemini answered without the tool
        assert allowed is False and handle.interrupted
        handle.chat_items = []
        personal_speech_finished(b.personal, wake.turns, handle, provider="gemini")
        assert b.retired == []  # not retired by the withheld response
        # The repaired answer plays and finishes: now the session retires.
        await wake.turns.prepare()
        allowed, repaired = wake.response()
        assert allowed is True
        repaired.chat_items = []
        repaired.interrupted = False
        assert await b.personal.allow_audio()
        b.personal.playback_finished()
        personal_speech_finished(b.personal, wake.turns, repaired, provider="gemini")
        assert b.retired == ["response_completed"]
    finally:
        b.personal.close()


@pytest.mark.asyncio
async def test_b3_a_barge_in_still_retires_a_protected_session(lab, tmp_path):
    from jarvis.voice.canonical_active_speaker_runtime import personal_speech_finished

    b = await personal_wake(lab, tmp_path)
    try:
        b.wake.speech()
        b.wake.transcript("What should I eat?")
        await b.personal.catalog()
        handle = FakeHandle()
        handle.chat_items = []
        handle.interrupt()  # the owner barged in on an audible answer
        personal_speech_finished(b.personal, b.wake.turns, handle, provider="gemini")
        assert b.retired == ["invalidated"]
    finally:
        b.personal.close()


def test_b3_activation_no_longer_refuses_fallback_or_apply():
    from dataclasses import replace

    from jarvis.config import JarvisConfig
    from jarvis.model_routing.gemini import GeminiFallbackConfig
    from jarvis.voice import project_voice_production as production

    installed = replace(
        JarvisConfig(),
        project_memory_mode="voice",
        memory_enabled=True,
        ai_provider="gemini",
        gemini_fallback=GeminiFallbackConfig(enabled=True),
        personal_context_mode="apply",
        personal_learning_mode="apply",
    )
    assert production.activation_blockers(installed) == []
    assert production.production_project_memory_factory(installed) is not None


@pytest.mark.asyncio
async def test_b3_canonical_runtime_wires_both_features_into_one_wake(monkeypatch):
    """The real controller session factory with project memory, personal
    context APPLY and a Gemini handoff on the same bridge."""
    from dataclasses import replace

    from jarvis.config import JarvisConfig
    from jarvis.voice.canonical_active_speaker_runtime import (
        CanonicalActiveSpeakerRuntimeController,
    )

    calls = []

    class Turns(SimpleNamespace):
        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name)

    turns = Turns()
    memory = SimpleNamespace(
        required=False,
        available=lambda: True,
        configure_realtime_model=lambda llm: calls.append("configure"),
        session=lambda conversation: turns,
    )
    handoff = SimpleNamespace(
        configurers=[],
        providers=[],
        add_model_configurer=lambda c: handoff.configurers.append(c),
        add_context_provider=lambda p, o=None: handoff.providers.append((p, o)),
    )

    class Session:
        llm = object()

        def on(self, *a):
            pass

    def factory(config):
        from jarvis.conversation import ConversationSession

        conversation = ConversationSession()
        conversation.start()
        bridge = SimpleNamespace(
            conversation=conversation,
            gemini_handoff=handoff,
            add_accepted_turn_observer=lambda o: None,
            add_close_observer=lambda o: None,
            register_restored_context=lambda c: None,
        )
        return Session(), bridge

    releases = []

    class Personal:
        def __init__(self, **kwargs):
            pass

        def add_release_observer(self, observer):
            releases.append(observer)

        def observe_turn(self, turn):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "jarvis.voice.canonical_active_speaker_runtime.PersonalContextSession", Personal
    )
    config = replace(JarvisConfig(), personal_context_mode="apply")
    c = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(),
        memory_runtime=SimpleNamespace(retrieval=None, topic_checkpoints=None),
        capability_runtime=SimpleNamespace(personal_learning_authority=None),
        project_memory=memory,
        session_factory=factory,
    )
    c._session_factory(c.config)
    assert "configure" in calls  # the session's first model
    assert handoff.configurers == [memory.configure_realtime_model]
    assert handoff.providers and handoff.providers[0][0] is not None
    assert len(releases) == 1  # personal releases reach project memory
