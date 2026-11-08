"""Voice history search stays in the current project unless the owner reaches out.

Live run, owner PC, 2026-11-08T05:56:00Z: in a fresh wake in Interview Prep,
"Which hotel are we staying at?" was answered "You are staying at the Yak and
Yeti hotel." The hotel was said only in Nepal trip. The model called
search_history("hotel"); Interview Prep had no match, so the search widened to
every project and returned the Nepal row (labelled, but the answer was not).
Real voice pipeline and archive; Gemini's tool call is driven by the test.
"""

import pytest
from test_project_voice import Wake
from test_project_voice import lab as voice_lab
from test_project_voice_fast_path import FastWake

from jarvis.memory.project_routing import owner_asked_beyond_current_project

lab = voice_lab


async def live_run_projects(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("Create a project called Nepal trip.", "Created project Nepal trip.")
    await wake.ask("Our hotel is Yak and Yeti.", "Understood.")
    await wake.ask(
        "Create a project called Interview Prep.", "Created project Interview Prep."
    )
    await wake.ask("The interview panel is on Friday at 10:00.", "Understood.")
    wake.close()
    return voice


@pytest.mark.asyncio
async def test_the_live_run_question_finds_nothing_in_interview_prep(lab):
    voice = await live_run_projects(lab)
    wake = FastWake(voice)  # fresh wake; current project: Interview Prep
    await wake.preload()
    assert "Yak" not in "\n".join(wake.agent.injected())
    wake.speech()
    wake.transcript("Which hotel are we staying at?")
    found = await wake.turns.search_history("hotel")
    assert found["status"] == "no_match"
    assert found["history"] == []
    assert "Yak" not in str(found)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Which hotel did we book for the Nepal trip?",
        "Which project has the hotel?",
        "Check my other projects for the hotel.",
    ],
)
async def test_the_owner_can_still_ask_across_projects(lab, question):
    voice = await live_run_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript(question)
    found = await wake.turns.search_history("hotel")
    assert found["status"] == "other_projects"
    assert {r["from_project"] for r in found["history"]} == {"Nepal trip"}
    assert "name that project" in found["guidance"]


@pytest.mark.asyncio
async def test_current_project_hits_never_bring_other_projects(lab):
    voice = await live_run_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Which project has the panel?")
    found = await wake.turns.search_history("panel")
    assert found["status"] != "other_projects"
    assert all("from_project" not in r for r in found["history"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Which hotel are we staying at?", False),
        ("When is the panel?", False),
        ("What's the plan for this project?", False),
        ("Which project has the hotel?", True),
        ("Look in my other projects.", True),
        ("Is it in any project?", True),
        ("Search all my projects for the hotel.", True),
    ],
)
def test_across_project_phrases(text, expected):
    from types import SimpleNamespace

    catalog = SimpleNamespace(entries=(), current=None)
    assert owner_asked_beyond_current_project(catalog, text) is expected
