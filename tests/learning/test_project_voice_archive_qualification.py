"""Q1 end to end: a distinctive fact beyond the preload window is retrieved
from the archive and graded PASS from the real diagnostics record.

Live run at 1b13dfb8 graded Q1 "search_found_nothing": only six owner rows had
been saved, so the hotel fact sat inside the session preload, the answer came
from the preload, and search (which never resends rows the model already has)
found nothing new. Here the setup pushes the fact out of the preload, so the
archive search itself must find it, and the grader is fed by the same
diagnostics the lab records (not a synthetic record).
"""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import settle
from test_project_voice_fast_path import FakeAgent
from test_project_voice_forget_recall import long_project
from test_voice_diagnostics import FakeProtector, VoiceRun

from jarvis.voice import project_voice_qualification as q
from jarvis.voice import voice_diagnostics as vd

lab = project_voice_tests.lab


@pytest.fixture
def labdir(tmp_path):
    root = tmp_path / "profile"
    root.mkdir()
    (root / "project-memory.marker").write_text("{}")
    return root


async def recall_run(voice, labdir, *, query="hotel Kathmandu"):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice.diagnostics = diagnostics
    run = VoiceRun(diagnostics, voice)
    agent = FakeAgent()
    await run.turns.preload(agent)
    preloaded = "".join(i.text_content for i in agent.chat_ctx.items)
    question = "Which hotel did we book in Kathmandu?"
    await run.speak()
    run.recognise(question)
    run.accept(question)
    found = await run.turns.search_history(query)
    reply = " ".join(r["text"] for r in found.get("history", ()) if "Yeti" in r["text"])
    await run.answer("You booked the Yak and Yeti." if reply else "I don't know.")
    await settle(voice)
    run.close()
    await diagnostics.aclose()
    return preloaded, found, vd.load_run(diagnostics.run_dir, FakeProtector())


@pytest.mark.asyncio
async def test_a_fact_beyond_the_preload_is_found_in_the_archive(lab, clock, labdir):
    voice = await long_project(lab, clock)
    preloaded, found, data = await recall_run(voice, labdir)
    assert "Yeti" not in preloaded  # genuinely outside the preload window
    assert any("Yak and Yeti" in r["text"] for r in found["history"])
    result = q.q1_recall(data)
    assert result["verdict"] == "PASS", result
    assert result["found_outside_preload"] == [
        "Our hotel in Kathmandu is Yak and Yeti."
    ]
    assert result["reply_uses"] == ["yak", "yeti"]


@pytest.mark.asyncio
async def test_a_fact_inside_the_preload_is_not_graded_as_archive_recall(
    lab, clock, labdir
):
    voice = await long_project(lab, clock, filler=2)  # the live setup's shape
    preloaded, found, data = await recall_run(voice, labdir)
    assert "Yak and Yeti" in preloaded
    assert found.get("history", []) == [] or all(
        "Yeti" not in r["text"] for r in found["history"]
    )
    data_reply = data["sessions"][0]["utterances"][0]
    # The model answers from the preload; simulate that answer.
    data_reply["assistant"] = [{"text": "You booked the Yak and Yeti.", "at": "x"}]
    result = q.q1_recall(data)
    assert result["verdict"] == "NOT_RUN"
    assert result["reason"] == "fact_was_in_the_preload_not_an_archive_search"
