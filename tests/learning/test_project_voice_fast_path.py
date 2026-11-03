"""Fast path: ordinary turns answered from preloaded project context.

A wake session preloads the current project's bounded recent history once.
Ordinary speech is then answered in ONE Gemini generation (no tool call, no
second generation). Anything that could change or widen the context - a
project command, another project named, the once-per-runtime "Resuming X."
announcement - is classified deterministically with the router's own rules and
still goes through prepare_project_turn. Every accepted turn is saved by the
application either way. Storage, routing, provenance and grants are real.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_routing import routed
from test_project_routing_decisions import lab as router_lab  # noqa: F401
from test_project_voice import FakeHandle, FakeSession, Wake, settle
from test_voice_acceptance import labdir  # noqa: F401
from test_voice_diagnostics import FakeProtector, VoiceRun, report

from jarvis.memory.project_routing import ProjectRouter, needs_project_routing
from jarvis.voice import project_voice
from jarvis.voice import voice_diagnostics as vd
from jarvis.voice.project_voice import (
    PRELOAD_MAX_CHARS,
    PRELOAD_ROWS,
    REPAIR_ANSWER_INSTRUCTIONS,
    VoiceProjectMemory,
)

lab = project_voice_tests.lab  # shared real-archive fixture

CONTEXT_PREFIX = "jarvis:project-context:"


class FakeAgent:
    """The running LiveKit Agent: only its chat context is used."""

    def __init__(self):
        from livekit.agents.llm import ChatContext

        self.chat_ctx = ChatContext.empty()
        self.updates = 0

    async def update_chat_ctx(self, context):
        self.chat_ctx = context
        self.updates += 1

    def injected(self):
        return [
            item.text_content
            for item in self.chat_ctx.items
            if item.id.startswith(CONTEXT_PREFIX)
        ]


class AgentSession(FakeSession):
    def __init__(self, agent):
        super().__init__()
        self.current_agent = agent


class FastWake(Wake):
    """A wake session with the preload and streaming recognition."""

    def __init__(self, voice):
        super().__init__(voice)
        self.agent = FakeAgent()
        self.session = AgentSession(self.agent)
        self.turns.bind_session(self.session)
        self.registered = []
        self.turns.bind_injection_registry(self.registered.append)

    async def preload(self):
        await self.turns.preload(self.agent)

    def partial(self, text):
        self.turns.observe_transcription(SimpleNamespace(transcript=text))

    async def gate(self):
        handle = FakeHandle()
        self.turns.observe_speech(SimpleNamespace(speech_handle=handle))
        return await self.turns.response_audio_allowed(), handle

    async def fast(self, text, answer, *, reply_first=False):
        """An ordinary turn: recognition streams, Gemini answers directly."""
        self.speech()
        self.partial(text)
        allowed, handle = await self.gate()
        assert allowed and not handle.interrupted
        if reply_first:  # the reply may commit just before the final transcript
            reply = self.reply(answer)
            await asyncio.sleep(0)
            self.transcript(text)
        else:
            self.transcript(text)
            reply = self.reply(answer)
        await settle(self.voice)
        return reply


async def nepal(lab):
    """A runtime with a 'Nepal trip' project and two saved facts."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("We will take the Jimny.", "Noted.")
    await wake.ask("The permits are sorted.", "Good.")
    wake.close()
    return voice


@pytest.mark.asyncio
async def test_ordinary_turn_is_answered_from_preload_without_the_tool(lab):
    voice = await nepal(lab)
    tool_calls = voice.metrics.delivered
    wake = FastWake(voice)  # a new Gemini session in the same runtime
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "Current project: Nepal trip." in context
    assert "owner: We will take the Jimny." in context
    assert "not speech from the owner" in context
    # The bridge knows the injected item, so it is never accepted as a turn.
    (registered,) = wake.registered
    assert [i.text_content for i in registered.items] == [context]

    reply = await wake.fast("Which vehicle are we taking?", "The Jimny.")
    assert voice.metrics.delivered == tool_calls  # no tool call
    assert voice.metrics.fast_path_turns == 1
    assert wake.session.replies == []  # no repair, no second generation
    rows = lab.rows()
    assert rows[-2:] == [
        ("user", "Which vehicle are we taking?", "complete", "Nepal trip"),
        ("assistant", "The Jimny.", "complete", "Nepal trip"),
    ]
    # The reply's evidence is everything Gemini was given (the preload), so
    # forgetting any of those sources later removes this reply too.
    assert {"We will take the Jimny.", "The permits are sorted."} <= lab.evidence(
        reply.text
    )
    wake.close()
    assert voice.metrics.undelivered_user_turns == 0


@pytest.mark.asyncio
async def test_reply_committed_before_its_question_is_archived_after_it(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    await wake.fast("And the permits?", "They are sorted.", reply_first=True)
    assert lab.rows()[-2:] == [
        ("user", "And the permits?", "complete", "Nepal trip"),
        ("assistant", "They are sorted.", "complete", "Nepal trip"),
    ]


@pytest.mark.parametrize(
    "partial",
    [
        "create project called Goa",
        "Okay, switch to General",
        "We said that. Create project called Goa.",  # embedded: clarified
        "What did we decide about Nepal?",  # another project, partial name
    ],
)
@pytest.mark.asyncio
async def test_commands_and_other_projects_still_go_through_the_tool(lab, partial):
    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called weekend chores", "Created.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial(partial)
    allowed, handle = await wake.gate()  # Gemini answered without the tool
    assert allowed is False and handle.interrupted
    assert voice.metrics.fast_path_turns == 0
    wake.transcript(partial)
    await settle(voice)
    # Repair by delivery: the application gives Gemini exactly the context the
    # tool would have returned, then re-requests the answer.
    assert wake.session.replies == [REPAIR_ANSWER_INSTRUCTIONS]
    assert voice.metrics.repair_deliveries == 1
    repaired = wake.agent.injected()[-1]
    assert "for the owner's last request" in repaired
    assert '"status": "ready"' in repaired or '"status": "clarification"' in repaired
    # A late tool call returns the same, already delivered result.
    result = await wake.turns.prepare()
    assert result["status"] in {"ready", "clarification"}
    assert wake.response()[0] is True


@pytest.mark.asyncio
async def test_first_turn_after_restart_keeps_its_resume_announcement(lab):
    voice = await nepal(lab)
    await voice.aclose()
    restarted = await lab.runtime()
    wake = FastWake(restarted)
    await wake.preload()
    wake.speech()
    wake.partial("Which vehicle are we taking?")
    allowed, _ = await wake.gate()
    assert allowed is False  # "Resuming Nepal trip." must be delivered first
    wake.transcript("Which vehicle are we taking?")
    result = await wake.turns.prepare()
    assert result["announcement"] == "Resuming Nepal trip."
    # Preloaded rows are not sent again by the tool; only the new question is.
    assert [r["text"] for r in result["history"]] == ["Which vehicle are we taking?"]
    assert result["earlier_history_already_provided"] >= 6
    wake.reply("Resuming Nepal trip. The Jimny.")
    await settle(restarted)
    # Later ordinary turns take the fast path.
    await wake.fast("And the permits?", "Sorted.")
    assert restarted.metrics.fast_path_turns == 1


@pytest.mark.asyncio
async def test_no_recognition_yet_waits_briefly_then_uses_the_tool(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "_FAST_PATH_TEXT_WAIT_SECONDS", 0.05)
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    # Recognition arrives while the first response frame waits for it.
    wake.speech()
    pending = asyncio.ensure_future(wake.gate())
    await asyncio.sleep(0)
    wake.partial("Which vehicle?")
    allowed, _ = await pending
    assert allowed is True
    wake.transcript("Which vehicle?")
    wake.reply("The Jimny.")
    await settle(voice)
    # No recognition at all: withheld, and the tool path takes over.
    wake.speech()
    allowed, handle = await wake.gate()
    assert allowed is False and handle.interrupted
    wake.close()


@pytest.mark.asyncio
async def test_late_command_is_announced_and_context_preloaded_again(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial("Create")  # recognition incomplete when the answer started
    allowed, _ = await wake.gate()
    assert allowed is True
    wake.transcript("Create project called Goa")
    await settle(voice)
    assert wake.session.replies == ["Say only this, exactly: 'Created project Goa.'"]
    assert voice.metrics.late_routing == 1
    contexts = wake.agent.injected()
    assert len(contexts) == 2 and "Current project: Goa." in contexts[-1]
    assert wake.turns._fast_selection == wake.turns._committed_selection
    # The next ordinary turn is answered from Goa's context.
    await wake.fast("What should we pack?", "Light clothes.")
    # rows() orders by per-thread sequence, so compare Goa's thread alone.
    assert [r for r in lab.rows() if r[3] == "Goa"] == [
        ("user", "Create project called Goa", "complete", "Goa"),
        ("user", "What should we pack?", "complete", "Goa"),
        ("assistant", "Light clothes.", "complete", "Goa"),
    ]


@pytest.mark.asyncio
async def test_preload_is_bounded_deduplicated_and_isolated(lab):
    await (await nepal(lab)).aclose()
    voice = await lab.runtime()  # a fresh grant: each grant has a child budget
    wake = Wake(voice)
    await wake.ask("create project called Goa", "Created.")
    for number in range(14):
        wake.speech()
        wake.transcript(f"Goa note {number}: " + "beach " * 20)
    wake.speech()
    wake.transcript("Huge note: " + "sand " * 700)  # larger than the whole budget
    await settle(voice)
    wake.close()
    await voice.aclose()
    wake = FastWake(await lab.runtime())
    await wake.preload()
    (context,) = wake.agent.injected()
    lines = [line for line in context.splitlines() if line.startswith("- ")]
    assert 1 <= len(lines) <= PRELOAD_ROWS
    assert len(context) <= PRELOAD_MAX_CHARS + 300
    assert "Goa note 13" in context and "Goa note 0:" not in context  # newest
    assert "older history exists" in context
    assert "Huge note" not in context  # never shortened, so not preloaded
    # Project isolation: nothing from Nepal trip is preloaded.
    assert "Jimny" not in context and "permits" not in context
    # A second preload in the same Gemini session sends nothing twice.
    await wake.preload()
    assert "- " not in wake.agent.injected()[-1]


@pytest.mark.asyncio
async def test_fast_turn_adds_no_archive_reads(lab):
    """Each archive read holds one of the grant's bounded leases; a fast
    ordinary turn uses exactly the reads the tool path's save already did."""
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    calls = []
    real = voice.access.catalog

    async def counted():
        calls.append(1)
        return await real()

    voice.access.catalog = counted
    await wake.fast("Which vehicle?", "The Jimny.")
    assert len(calls) == 2  # turn preparation + routing, as before the fast path


@pytest.mark.asyncio
async def test_turns_with_equal_timestamps_preload_in_spoken_order(lab, monkeypatch):
    """Windows CI regression: the coarse clock gives quick successive turns the
    same accepted_at; recent history must still be in the order spoken."""
    import jarvis.conversation as conversation_module

    real = conversation_module.datetime
    tick = real.now(conversation_module.UTC)  # one clock tick for every turn

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return Frozen.combine(tick.date(), tick.timetz())

    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called Goa", "Created.")
    monkeypatch.setattr(conversation_module, "datetime", Frozen)
    spoken = [f"Goa step {n}." for n in range(6)]
    for text in spoken:
        wake.speech()
        wake.transcript(text)
    await settle(voice)
    monkeypatch.setattr(conversation_module, "datetime", real)
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    positions = [context.index(text) for text in spoken]
    assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_preload_requires_a_current_grant(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    voice.access.authority.revoke(voice.access.grant, "test")
    await wake.turns._safe_preload(wake.agent)
    assert wake.agent.updates == 0 and wake.turns._fast_ready is False
    wake.speech()
    wake.partial("Which vehicle?")
    assert (await wake.gate())[0] is False  # tool path (which also fails closed)
    wake.close()


@pytest.mark.asyncio
async def test_tool_only_mode_never_preloads(lab):
    voice = await nepal(lab)
    voice.fast_path = False
    wake = FastWake(voice)
    wake.turns.start_preload()
    await settle(voice)
    assert wake.agent.updates == 0
    from jarvis.voice.project_voice_lab import project_memory_factory

    assert project_memory_factory(None, None, fast_path=False).fast_path is False
    assert VoiceProjectMemory(None, None, source_clearance=bool).fast_path is True


def test_fixed_project_mode_prompt_and_schema_stay_small():
    """Fixed tokens added to EVERY Gemini response in project-memory mode."""
    from jarvis.voice.agent import PROJECT_MEMORY_INSTRUCTIONS

    # Roughly 4 characters per token. Before the performance pass: 1,059 +
    # 435 + 724. The instructions include the voice grounding rules (#303).
    assert len(PROJECT_MEMORY_INSTRUCTIONS) <= 1250  # + search/forget routing
    assert len(project_voice._TOOL_DESCRIPTION) <= 260
    assert len(project_voice._GUIDANCE) <= 460


@pytest.mark.asyncio
async def test_local_preparation_and_preload_are_fast(lab):
    """Local cost only (no model): save + routing + packet, and the preload."""
    voice = await nepal(lab)
    wake = FastWake(voice)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await wake.preload()
    preload_ms = (loop.time() - started) * 1000
    await wake.fast("Which vehicle?", "The Jimny.")
    prepare = voice.metrics.snapshot()["prepare_ms"]
    assert preload_ms < 500 and prepare["max"] < 500  # generous for CI runners


@pytest.mark.asyncio
async def test_needs_project_routing_matches_the_router(router_lab):  # noqa: F811
    access = router_lab.access()
    router = ProjectRouter(access)
    await routed(router, "create project called Nepal trip")
    await routed(router, "create project called weekend chores")
    catalog = await access.catalog()
    ordinary = [
        "What should I buy for the weekend?",
        "How was your trip?",  # generic words never name a project
        "Is Nepalese food spicy?",
        "What did we say about weekend chores?",  # the current project itself
        "Remind me what I said earlier.",
    ]
    routing = [
        "",
        "create project called Goa",
        "Okay. Create a project called interview preparation.",
        "switch to Nepal trip",
        "new conversation in Nepal trip",
        "select project 123",
        "create a project",  # unreadable command: must be clarified
        "We said that. Create project called Goa.",  # embedded command
        "What did we decide about Nepal?",  # partial name of another project
    ]
    assert [needs_project_routing(t, catalog) for t in ordinary] == [False] * 5
    assert [needs_project_routing(t, catalog) for t in routing] == [True] * 9
    # The classifier agrees with the router: ordinary text never changes
    # the selection or reads another project.
    for text in ordinary:
        decision = await routed(router, text)
        assert decision.title == "weekend chores" and decision.references == ()
    assert router.announces_next_turn(await access.catalog()) is False
    restarted = ProjectRouter(access)
    assert restarted.announces_next_turn(await access.catalog()) is True


@pytest.mark.asyncio
async def test_fast_path_is_audited_in_diagnostics(lab, labdir):  # noqa: F811
    voice = await nepal(lab)
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice.diagnostics = diagnostics
    run = VoiceRun(diagnostics, voice)
    await run.turns.preload(FakeAgent())
    await run.say("Which vehicle are we taking?", "The Jimny.", call_tool=False)
    run.close()
    data, _ = await report(diagnostics, labdir)
    (preloaded,) = [
        e for e in data["sessions"][0]["unmatched"] if e["kind"] == "context_preloaded"
    ]
    assert preloaded["project"] == "Nepal trip" and preloaded["rows"] == 6
    (result,) = vd.assess(data)["results"]
    # "Jimny" came from the preload, so it is supported evidence, not REVIEW.
    assert result["verdict"] == "PASS", result
    assert result["info"] == ["answered_from_preloaded_context"]
    assert "fast_path_decided" in result["latency_ms"]
    assert "tool_called" not in result["latency_ms"]
