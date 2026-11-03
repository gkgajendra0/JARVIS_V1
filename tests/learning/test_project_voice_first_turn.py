"""First-turn regression from live -Qualification at 3938b428.

Fresh lab, first utterance "Remember that my car is a Jimny.":
remember_memory ran, the turn was saved and routing silently opened the
default General workspace, but no prepare_project_turn call came. The audio
gate then withheld the reply: the preload had no project (None) and routing
had just committed General, so the fast path judged Gemini's context stale.
It was not: a new, empty, silently opened project needs nothing beyond the
live conversation. The tool re-request produced no reply either, and the
session timed out in silence (unprepared_responses_blocked=1, repairs=1,
undelivered_user_turns=1).

Fixed: (1) a silently created empty project keeps the fast path current;
(2) repair delivers the prepared context itself and re-requests the answer;
(3) a re-request with no audible reply speaks the fallback before timeout.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake, nepal

from jarvis.voice import project_voice
from jarvis.voice.project_voice import (
    FALLBACK_INSTRUCTIONS,
    REPAIR_ANSWER_INSTRUCTIONS,
)

lab = project_voice_tests.lab  # shared real-archive fixture

FIRST = "Remember that my car is a Jimny."


def remember_ran(wake, *, error=False):
    wake.turns.observe_tools_executed(
        SimpleNamespace(
            function_calls=[SimpleNamespace(name="remember_memory")],
            function_call_outputs=[SimpleNamespace(is_error=error)],
        )
    )


@pytest.mark.parametrize("saved_before_reply", [True, False])
@pytest.mark.asyncio
async def test_first_turn_with_canonical_remember_is_heard_and_saved_once(
    lab, saved_before_reply
):
    voice = await lab.runtime()  # fresh lab: no project at all
    wake = FastWake(voice)
    await wake.preload()
    assert wake.agent.injected() == []  # nothing to preload yet
    wake.speech()
    wake.partial(FIRST)
    # Gemini finalises the transcript when it calls remember_memory (blocking).
    wake.transcript(FIRST)
    remember_ran(wake)
    if saved_before_reply:
        await settle(voice)  # General opened and the turn saved first
    allowed, handle = await wake.gate()  # the acknowledgement after the tool
    assert allowed is True and not handle.interrupted
    wake.reply("Got it, your car is a Jimny.")
    await settle(voice)
    assert lab.rows() == [
        ("user", FIRST, "complete", "General"),
        ("assistant", "Got it, your car is a Jimny.", "complete", "General"),
    ]
    assert wake.session.replies == []  # no repair, no fallback
    metrics = voice.metrics
    assert metrics.unprepared_responses_blocked == 0 and metrics.repairs == 0
    assert metrics.saved_user_turns == 1
    wake.close()
    assert metrics.undelivered_user_turns == 0
    # The next turn in the same session is still answered on the fast path.


@pytest.mark.asyncio
async def test_the_next_turn_after_the_bootstrap_stays_fast(lab):
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript(FIRST)
    remember_ran(wake)
    await settle(voice)
    assert (await wake.gate())[0] is True
    wake.reply("Noted.")
    await wake.fast("And it is white.", "Noted, white.")
    assert voice.metrics.fast_path_turns == 2
    assert voice.metrics.fast_context_syncs == 1


@pytest.mark.asyncio
async def test_an_explicit_create_still_needs_its_announcement(lab):
    """Only the SILENT default workspace is treated as current context."""
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial("create project called Goa")
    assert (await wake.gate())[0] is False  # needs routing: the tool path
    wake.transcript("create project called Goa")
    await settle(voice)
    # Delivered by the application; the answer then carries the announcement.
    assert wake.session.replies == [REPAIR_ANSWER_INSTRUCTIONS]
    assert "Created project Goa." in wake.agent.injected()[-1]
    assert wake.response()[0] is True


@pytest.mark.asyncio
async def test_repair_delivers_context_without_relying_on_a_tool_call(lab):
    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called garage", "Created.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    question = "What did we decide about Nepal?"
    wake.partial(question)
    allowed, handle = await wake.gate()  # answered before reading Nepal trip
    assert allowed is False and handle.interrupted
    wake.transcript(question)
    await settle(voice)
    delivered = wake.agent.injected()[-1]
    assert "We will take the Jimny." in delivered and "Nepal trip" in delivered
    assert voice.metrics.repair_deliveries == 1 and voice.metrics.tool_path_turns == 0
    assert wake.response()[0] is True
    reply = wake.reply("We are taking the Jimny, from Nepal trip.")
    await settle(voice)
    assert "We will take the Jimny." in lab.evidence(reply.text)
    assert [r[1] for r in lab.rows()].count(question) == 1  # saved exactly once


@pytest.mark.asyncio
async def test_an_unanswered_repair_speaks_the_fallback_before_timeout(
    lab, monkeypatch
):
    monkeypatch.setattr(project_voice, "REPAIR_RESPONSE_SECONDS", 0.05)
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial("switch to General")
    assert (await wake.gate())[0] is False
    wake.transcript("switch to General")
    await settle(voice)
    assert wake.session.replies == [REPAIR_ANSWER_INSTRUCTIONS]
    await asyncio.sleep(0.15)  # Gemini produced nothing audible
    assert wake.session.replies == [REPAIR_ANSWER_INSTRUCTIONS, FALLBACK_INSTRUCTIONS]
    assert voice.metrics.repair_timeouts == 1
    assert wake.response()[0] is True  # the fallback itself is heard


@pytest.mark.asyncio
async def test_an_answered_repair_never_adds_a_fallback(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "REPAIR_RESPONSE_SECONDS", 0.05)
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial("switch to General")
    assert (await wake.gate())[0] is False
    wake.transcript("switch to General")
    await settle(voice)
    assert wake.response()[0] is True  # the repaired answer plays
    await asyncio.sleep(0.15)
    assert wake.session.replies == [REPAIR_ANSWER_INSTRUCTIONS]
    assert voice.metrics.repair_timeouts == 0


@pytest.mark.asyncio
async def test_qualification_exposes_the_normal_tool_set_with_memory(tmp_path):
    from jarvis.voice.project_voice_lab import run_voice_lab

    seen = {}

    def builder(config, **kwargs):
        seen.update(kwargs)

        class Runtime:
            async def run(self):
                return None

        return Runtime()

    class Diagnostics:
        def attach(self, session, bridge):
            pass

        def audio_tap(self, bridge):
            return None

        async def aclose(self):
            pass

    await run_voice_lab(
        object(),
        tmp_path,
        baseline=False,
        runtime_builder=builder,
        diagnostics=Diagnostics(),
        qualification=True,
    )
    assert "tool_allowlist" not in seen  # Hands, research, canonical memory
    assert "project_memory_factory" in seen
    with pytest.raises(ValueError, match="qualification"):
        await run_voice_lab(
            object(),
            tmp_path,
            baseline=False,
            runtime_builder=builder,
            qualification=True,
        )
