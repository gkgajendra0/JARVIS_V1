"""Spoken project commands with conversational lead-ins.

Regression for the 2 Nov voice acceptance run 20261102T130052Z-3edaf5:
"Okay. Create a project called interview preparation." was routed as
ordinary conversation (continued in Nepal trip) and later turns were saved
there, while the model claimed the project had been created.
"""

import pytest
from test_project_routing import accepted, routed
from test_project_routing_decisions import lab, live_titles  # noqa: F401

from jarvis.memory.project_routing import (
    ProjectRouter,
    embedded_project_command,
    parse_project_command,
    strip_lead_in,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Okay. Create a project called interview preparation.",
            ("interview preparation", "create"),
        ),
        ("OK, create project called Nepal trip", ("Nepal trip", "create")),
        ("Alright, so, create a new project named Goa", ("Goa", "create")),
        ("Hey Jarvis, create a project called Goa.", ("Goa", "create")),
        ("Um, okay, please create a project called Goa", ("Goa", "create")),
        ("Okay then. Switch to Nepal trip.", ("Nepal trip", "select")),
        ("So let's plan my Goa trip", ("Goa trip", "plan")),
        ("Accha, switch to Nepal", ("Nepal", "select")),
        ("Theek hai, create project called Goa", ("Goa", "create")),
        ("Okay — resume Nepal", ("Nepal", "select")),
        ("Let's create a project called Goa", ("Goa", "create")),
        ("I want to create a project called Goa", ("Goa", "create")),
        ("Can we create a project called Goa?", ("Goa", "create")),
    ],
)
def test_lead_ins_before_a_command_are_ignored(text, expected):
    assert parse_project_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Okay.",
        "Okay, what is the status of my Nepal trip?",
        "So the interview is about SQL window functions.",
        "I told him to create a project called Goa.",
        "My friend wants to create a project called Goa",
        "Okay so tell me how to create a project in Jira",
        "Okaying the plan, create project",  # not a lead-in word; no name
        "Sorted. The permits are done.",
        "Right now we are switching hotels",
        "Hello there, my new project ideas are welcome",
    ],
)
def test_ordinary_speech_with_lead_ins_is_not_a_command(text):
    assert parse_project_command(text) == (None, None)


def test_strip_lead_in_is_bounded_and_start_only():
    assert strip_lead_in("Okay. Okay. Okay. Okay. Okay. create project X") != (
        "create project X"
    )  # at most four lead-ins
    assert strip_lead_in("Create okay project") == "Create okay project"
    assert strip_lead_in("okayish create project called X") == (
        "okayish create project called X"
    )


def test_a_command_in_a_later_sentence_is_found_but_not_executed():
    assert embedded_project_command(
        "The trip went well. Create a project called Goa."
    ) == ("Goa", "create")
    assert embedded_project_command("Create a project called Goa.") == (None, None)


@pytest.mark.asyncio
async def test_router_creates_from_the_exact_failing_utterance(lab):  # noqa: F811
    router = ProjectRouter(lab.access())
    await routed(router, "create project called Nepal trip")
    created = await routed(
        router, "Okay. Create a project called interview preparation."
    )
    assert created.action == "created"
    assert created.title == "interview preparation"
    assert created.announcement == "Created project interview preparation."
    follow = await routed(router, "My interview topic is SQL window functions.")
    assert follow.selection == created.selection  # saved under the right project
    back = await routed(router, "Okay, switch to Nepal trip.")
    assert (back.action, back.title) == ("switched", "Nepal trip")
    assert sorted(await live_titles(router.access)) == [
        "Nepal trip",
        "interview preparation",
    ]


@pytest.mark.asyncio
async def test_router_asks_about_a_command_hidden_after_other_content(lab):  # noqa: F811
    router = ProjectRouter(lab.access())
    nepal = await routed(router, "create project called Nepal trip")
    c, t = accepted("The trip went well. Create a project called Goa.")
    decision = await router.resolve(c, t)
    assert decision.status == "clarification"
    assert "Nothing was changed" in decision.question
    assert "create project called Goa" in decision.question
    still = await routed(router, "Okay, what did we decide?")
    assert still.selection == nepal.selection and still.action == "continued"
    assert await live_titles(router.access) == ["Nepal trip"]
