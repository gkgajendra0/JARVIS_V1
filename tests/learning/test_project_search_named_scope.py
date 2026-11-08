"""A project the owner names bounds voice history search to that project.

Gap after #314: when the owner named another project, the search widened to
EVERY project if the current one had no match, so "Which hotel for the Goa
trip?" (Goa trip has no hotel) could come back with the Nepal trip hotel, a
fact from a third project. And when the owner was in Nepal trip, the current
project's hotel matched first and stood in for the Goa answer.

Real voice pipeline and archive; Gemini's search call is driven by the test.
"""

import pytest
from test_project_voice import Wake
from test_project_voice import lab as voice_lab

from jarvis.memory.project_routing import owner_search_scope

lab = voice_lab


async def three_projects(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("Create a project called Nepal trip.", "Created project Nepal trip.")
    await wake.ask("Our hotel is Yak and Yeti.", "Understood.")
    await wake.ask("Create a project called Goa trip.", "Created project Goa trip.")
    await wake.ask("Our flight to Goa is on Monday.", "Noted.")
    await wake.ask(
        "Create a project called Interview Prep.", "Created project Interview Prep."
    )
    await wake.ask("The interview panel is on Friday at 10:00.", "Understood.")
    wake.close()
    return voice


async def search(voice, question, query, *, switch_to=None):
    wake = Wake(voice)
    if switch_to:
        await wake.ask(f"Switch to {switch_to}.", "Switched.")
    wake.speech()
    wake.transcript(question)
    return await wake.turns.search_history(query)


@pytest.mark.asyncio
async def test_named_project_without_a_match_never_gets_a_third_projects_fact(lab):
    voice = await three_projects(lab)  # current: Interview Prep
    found = await search(
        voice, "Which hotel are we staying at for the Goa trip?", "hotel"
    )
    assert found["status"] == "no_match"
    assert found["history"] == []
    assert "Yak" not in str(found)
    assert "do not answer from any other project" in found["guidance"]


@pytest.mark.asyncio
async def test_the_current_project_does_not_stand_in_for_a_named_one(lab):
    voice = await three_projects(lab)
    found = await search(
        voice,
        "Which hotel are we staying at for the Goa trip?",
        "hotel",
        switch_to="Nepal trip",
    )
    assert found["status"] == "no_match"
    assert "Yak" not in str(found)


@pytest.mark.asyncio
async def test_named_project_with_a_match_returns_only_that_project(lab):
    voice = await three_projects(lab)
    found = await search(voice, "When is the flight for the Goa trip?", "flight Monday")
    assert found["status"] == "other_projects"
    assert {r["from_project"] for r in found["history"]} == {"Goa trip"}


@pytest.mark.asyncio
async def test_naming_the_project_that_has_it_still_works(lab):
    voice = await three_projects(lab)
    found = await search(voice, "Which hotel did we book for the Nepal trip?", "hotel")
    assert found["status"] == "other_projects"
    assert {r["from_project"] for r in found["history"]} == {"Nepal trip"}


@pytest.mark.asyncio
async def test_an_across_projects_question_still_reads_every_project(lab):
    voice = await three_projects(lab)
    found = await search(voice, "Which project has the hotel?", "hotel")
    assert found["status"] == "other_projects"
    assert {r["from_project"] for r in found["history"]} == {"Nepal trip"}


@pytest.mark.asyncio
async def test_a_project_that_does_not_exist_widens_nothing(lab):
    voice = await three_projects(lab)
    found = await search(voice, "Which hotel for the Manali trip?", "hotel")
    assert found["status"] == "no_match"
    assert "Yak" not in str(found)


@pytest.mark.asyncio
async def test_a_question_about_the_current_project_is_unchanged(lab):
    voice = await three_projects(lab)
    found = await search(voice, "When is the panel?", "panel")
    assert found["status"] != "other_projects"
    assert all("from_project" not in r for r in found["history"])
    assert any("Friday" in r["text"] for r in found["history"])


def test_scope_helper():
    from types import SimpleNamespace

    empty = SimpleNamespace(entries=(), current=None)
    assert owner_search_scope(empty, "Which hotel are we staying at?") is None
    assert owner_search_scope(empty, "Which project has the hotel?") == "all"
