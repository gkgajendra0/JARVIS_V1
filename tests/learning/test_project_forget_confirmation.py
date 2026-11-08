"""A committed forget is confirmed accurately and then ends the wake.

Live run 2026-11-08 17:33:31 (installed de397af7): "Forget Himalayan Lotus."
committed (owner_rows=2, jarvis_rows=1), but 0.4 s after the transcript a short
noise burst (VAD 17:33:31.609-.928) started a new, empty user activity while
Windows Hello was open. Gemini's confirmation was then judged as an answer to
that empty activity: withheld, a repair waited 3 s for a transcript, and
"Sorry, I didn't catch that" was spoken instead. Because no confirmation was
attributed to the forget, the wake never ended and the model kept the forgotten
words in its context (the next reply leaked an instruction-like sentence).

Real archive, history authority and fake Windows Hello; Gemini is simulated.
"""

import asyncio
import sqlite3

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake

from jarvis.voice import project_voice

lab = project_voice_tests.lab

REQUEST = "Forget Himalayan Lotus."


async def _hotel(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("Arundel is Himalayan Lotus.", "Understood.")
    await wake.ask("The permits are sorted.", "Good.")
    wake.close()
    return voice


def _texts(lab):
    with sqlite3.connect(lab.db) as c:
        return [r[0] for r in c.execute("SELECT text FROM conversation_event")]


async def _forget_with_noise_during_approval(wake, words="Himalayan Lotus"):
    wake.speech()
    wake.partial(REQUEST)
    wake.transcript(REQUEST)
    task = asyncio.ensure_future(wake.turns.forget_history(words))
    await asyncio.sleep(0)  # the tool has taken the request's activity
    wake.speech()  # a noise burst: new activity, never transcribed
    return await task


@pytest.mark.asyncio
async def test_noise_during_approval_still_plays_the_confirmation_and_ends_the_wake(
    lab,
):
    voice = await _hotel(lab)
    wake = FastWake(voice)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(1))
    result = await _forget_with_noise_during_approval(wake)
    assert result["status"] == "forgotten", result
    allowed, handle = wake.response()
    assert allowed is True and not handle.interrupted  # was withheld live
    wake.reply(result["confirmation"])
    await settle(voice)
    assert retired == [1]  # the wake ends after the confirmation
    assert wake.session.replies == []  # no "didn't catch that", no repair
    assert result["confirmation"] not in _texts(lab)  # confirmations are not saved
    assert not any("Lotus" in t for t in _texts(lab))


@pytest.mark.asyncio
async def test_confirmation_states_what_was_removed(lab):
    voice = await _hotel(lab)
    wake = FastWake(voice)
    result = await _forget_with_noise_during_approval(wake)
    assert result["your_messages"] == 2  # the statement and the request
    assert result["personal_facts_removed"] == 0
    assert result["confirmation"] == "Done. I removed it from our saved conversations."


@pytest.mark.asyncio
async def test_unheard_confirmation_still_ends_the_wake(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "FORGET_RETIRE_SECONDS", 0.05)
    voice = await _hotel(lab)
    wake = FastWake(voice)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(1))
    result = await _forget_with_noise_during_approval(wake)
    assert result["status"] == "forgotten"
    await asyncio.sleep(0.15)  # Gemini never produced a confirmation
    assert retired == [1]


@pytest.mark.asyncio
async def test_a_new_request_after_the_forget_is_not_taken_as_its_confirmation(lab):
    voice = await _hotel(lab)
    wake = FastWake(voice)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(1))
    result = await _forget_with_noise_during_approval(wake)
    assert result["status"] == "forgotten"
    wake.transcript("Which hotel are we staying at?")  # spoken in the burst
    assert wake.turns._pending_forget_confirmation() is None
    assert retired == []


@pytest.mark.asyncio
async def test_retire_happens_once(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "FORGET_RETIRE_SECONDS", 0.05)
    voice = await _hotel(lab)
    wake = FastWake(voice)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(1))
    result = await _forget_with_noise_during_approval(wake)
    assert wake.response()[0] is True
    wake.reply(result["confirmation"])
    await settle(voice)
    await asyncio.sleep(0.15)
    assert retired == [1]
