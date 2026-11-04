"""Spoken project commands split into sentences by speech-to-text.

Regression for the 4 Nov production acceptance run: the transcripts
"Okay. Now create a project. Called Nepal trip." and "Create a project.
Called Nepal trip." both got "No project was created or switched."
"""

import pytest
from test_project_routing import routed
from test_project_routing_decisions import lab, live_titles  # noqa: F401

from jarvis.memory.project_routing import ProjectRouter, parse_project_command

PRODUCTION_TRANSCRIPTS = (
    "Okay. Now create a project. Called Nepal trip.",
    "Create a project. Called Nepal trip.",
)


@pytest.mark.parametrize("text", PRODUCTION_TRANSCRIPTS)
def test_the_production_transcripts_are_create_commands(text):
    assert parse_project_command(text) == ("Nepal trip", "create")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Create a project, called Nepal trip.", ("Nepal trip", "create")),
        ("Create a new project. Named Goa.", ("Goa", "create")),
        ("Add a project — called Goa", ("Goa", "create")),
        ("Start a project. Called interview prep.", ("interview prep", "create")),
        ("New project. Called Goa.", ("Goa", "create")),
        ("Please create a project. Called Goa?", ("Goa", "create")),
    ],
)
def test_punctuation_before_called_or_named_is_accepted(text, expected):
    assert parse_project_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Punctuation is only bridged before "called"/"named".
        "Create a project. Nepal trip.",
        # After a break the name gets the strict check: no sentence words.
        "Create a project. Called my mom about it.",
        "Create a project. Called him to discuss the trip.",
        # Not a command at the start of the sentence.
        "I told him to create a project. Called him later.",
        "We talked about the project. Called it a day.",
        "The project. Called Nepal trip.",
    ],
)
def test_unrelated_sentences_are_not_commands(text):
    assert parse_project_command(text) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", PRODUCTION_TRANSCRIPTS)
async def test_router_creates_from_the_production_transcript(lab, text):  # noqa: F811
    router = ProjectRouter(lab.access())
    created = await routed(router, text)
    assert created.action == "created"
    assert created.title == "Nepal trip"
    assert created.announcement == "Created project Nepal trip."
    assert await live_titles(router.access) == ["Nepal trip"]
    follow = await routed(router, "We will take the Jimny.")
    assert follow.selection == created.selection


@pytest.mark.asyncio
async def test_unparsed_split_command_still_asks_and_changes_nothing(lab):  # noqa: F811
    from test_project_routing import accepted

    router = ProjectRouter(lab.access())
    c, t = accepted("Create a project. Called my mom about it.")
    decision = await router.resolve(c, t)
    assert decision.status != "ready"
    assert await live_titles(router.access) == []


# -- personal learning must not store project commands as life facts -------------
# Production 2026-11-04: "Okay. Now create a project. Called Nepal trip." was
# committed to canonical memory as a confirmed plan "Nepal trip".


def _source(text):
    # source_allowed reads only the text of the accepted source.
    from types import SimpleNamespace

    return SimpleNamespace(text=text)


@pytest.mark.parametrize(
    "text",
    [
        *PRODUCTION_TRANSCRIPTS,
        "Create project called Nepal trip.",
        "Okay, switch to Interview prep.",
        "Open project Nepal trip",
    ],
)
def test_project_commands_are_not_learning_sources(text):
    from jarvis.memory.learning_policy import LearningPolicy

    assert LearningPolicy.source_allowed(_source(text)) is False


@pytest.mark.parametrize(
    "text",
    [
        "We will take the Jimny.",
        "Let's plan my Goa trip.",
        "Resume my thesis writing tomorrow.",
        "I told him to create a project called Goa.",
        "My diet preference is vegetarian.",
    ],
)
def test_ordinary_statements_stay_learning_sources(text):
    from jarvis.memory.learning_policy import LearningPolicy

    assert LearningPolicy.source_allowed(_source(text)) is True
