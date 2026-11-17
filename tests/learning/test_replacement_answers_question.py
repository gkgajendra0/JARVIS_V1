"""The replacement must answer the owner's question (live 2026-11-17 16:56).

First wake after a restart, owner: "What time is it?". Gemini answered at once,
but the router still owed its once-per-runtime "Resuming Munnar trip." so the
gate held that answer back and repair delivered the project context and
re-requested the answer. The replacement played and finished (#323), but said
"Do not mention project memory, history or the background process. Resuming
Munnar trip. We are taking the Creta." - no time, an instruction to itself,
and a project fact nobody asked for; that text was also saved as the reply.

What Gemini had been sent for the retry (google plugin 1.8.3, gemini-3.8-live):
  user  (audio)  "What time is it?"
  model          its first answer (complete on the server; only playback was cut)
  user           "[Project memory from Jarvis ...] {announcement, history, guidance}"
  model          "Noted."
  model          REPAIR_ANSWER_INSTRUCTIONS   <- generate_reply instructions
  (turn_complete; this model has no "." reply placeholder)
The question was never restated: as far as Gemini could tell it had already
answered it, the newest owner-side turn was the memory block, and the request
to answer arrived as Gemini's OWN words, which it continued as speech.

Now the retry ends with an owner-side turn from Jarvis that quotes the
question, and generate_reply carries no instructions.
"""

import json

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import settle
from test_project_voice_fast_path import FastWake, nepal

from jarvis.voice.voice_output_safety import (
    sanitize_assistant_transcript,
    strip_self_narration,
)

lab = project_voice_tests.lab  # shared real-archive fixture

QUESTION = "What time is it?"
LIVE_REPLY = (
    "Do not mention project memory, history or the background process."
    "Resuming Munnar trip. We are taking the Creta."
)


def gemini_view(wake, before):
    """The turns Gemini holds after the retry, in its own roles: the owner's
    audio question and its unheard first answer (server side), then what the
    application added to the chat context, then generate_reply's turn exactly
    as the google plugin builds it (instructions -> role "model")."""
    from livekit.agents.llm import ChatContext

    added = ChatContext(items=list(wake.agent.chat_ctx.items[before:]))
    turns, _ = added.to_provider_format(
        format="google", inject_dummy_user_message=False
    )
    view = [("user", QUESTION), ("model", "It's 10:26 PM.")]
    view += [(t["role"], "".join(p.get("text", "") for p in t["parts"])) for t in turns]
    for instructions in wake.session.replies:
        if instructions is not None:
            view.append(("model", instructions))
    return view


async def first_turn_after_restart(lab):
    voice = await nepal(lab)
    await voice.aclose()
    restarted = await lab.runtime()
    wake = FastWake(restarted)
    await wake.preload()
    before = len(wake.agent.chat_ctx.items)
    wake.speech()
    wake.partial(QUESTION)
    allowed, handle = await wake.gate()  # answered before "Resuming Nepal trip."
    assert allowed is False and handle.interrupted
    wake.transcript(QUESTION)
    await settle(restarted)
    assert restarted.metrics.repair_deliveries == 1
    return restarted, wake, before


@pytest.mark.asyncio
async def test_the_retry_restates_the_question_as_the_owner_side_turn(lab):
    _voice, wake, before = await first_turn_after_restart(lab)
    view = gemini_view(wake, before)
    role, last = view[-1]
    # Gemini answers the newest owner-side turn: it must be the request, quoting
    # the question, and come after the project memory.
    assert role == "user"
    assert f'"{QUESTION}"' in last
    memory = next(i for i, (r, t) in enumerate(view) if "Project memory" in t)
    assert memory < len(view) - 1
    assert "Resuming Nepal trip." in view[memory][1]
    # Nothing Jarvis wrote is sent as Gemini's own words.
    assert all(text in {"It's 10:26 PM.", "Noted."} for r, text in view if r == "model")
    assert wake.session.replies == [None]  # requested with no instructions


@pytest.mark.asyncio
async def test_the_retry_request_is_not_taken_for_an_owner_turn(lab):
    voice, wake, _before = await first_turn_after_restart(lab)
    request = wake.agent.chat_ctx.items[-1]
    assert request.role == "user" and QUESTION in request.text_content
    # The bridge is told about it, so it is never accepted or saved as speech.
    assert any(request in ctx.items for ctx in wake.registered)
    wake.reply("Resuming Nepal trip. It's 10:26 PM.")
    await settle(voice)
    texts = [r[1] for r in lab.rows()]
    assert texts.count(QUESTION) == 1
    assert not any("Jarvis" in t and QUESTION in t for t in texts)


@pytest.mark.asyncio
async def test_the_request_names_the_source_project_when_one_was_asked_about(lab):
    voice = await nepal(lab)
    await voice.aclose()
    restarted = await lab.runtime()
    wake = FastWake(restarted)
    await wake.preload()
    wake.speech()
    question = "What did we decide in Nepal trip about the vehicle?"
    wake.partial(question)
    await wake.gate()
    wake.transcript(question)
    await settle(restarted)
    request = wake.agent.chat_ctx.items[-1].text_content
    assert f'"{question}"' in request
    delivered = json.loads(wake.agent.injected()[-1].split("] ", 1)[1])
    if delivered.get("source_attribution"):
        assert delivered["source_attribution"] in request


def test_the_live_self_instruction_is_kept_out_of_the_saved_reply():
    saved, reason = sanitize_assistant_transcript(LIVE_REPLY)
    assert saved == "Resuming Munnar trip. We are taking the Creta."
    assert reason == "self_narration_removed"
    # Ordinary speech with the same opening keeps its content.
    kept = "Don't worry, the Creta has room for the bags."
    assert strip_self_narration(kept) == kept
