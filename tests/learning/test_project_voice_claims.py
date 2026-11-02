"""Jarvis may only claim a project change the application committed."""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle

from jarvis.voice.project_claims import false_project_claims, project_claims

lab = project_voice_tests.lab  # shared real-archive fixture


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("Created project interview preparation.", {"created"}),
        ("I've set up a new project for you.", {"created"}),
        ("Done, the project is ready.", {"created"}),
        ("Switched to Nepal trip.", {"switched"}),
        ("You're now in Nepal trip.", {"switched"}),
        ("No project was created.", set()),
        ("Correction: no project was created or switched. You are in Nepal.", set()),
        ("I didn't switch anything.", set()),
        ("The date changed to Monday.", set()),
        ("We are now in Kathmandu.", set()),
        ("The Jimny and the permits are sorted.", set()),
        ("Resuming Nepal trip.", set()),
    ],
)
def test_claim_detection(text, claims):
    assert project_claims(text) == claims


def test_only_unsupported_claims_are_false():
    assert false_project_claims("Created project Goa.", "created") == set()
    assert false_project_claims("Created project Goa.", "continued") == {"created"}
    assert false_project_claims("Switched to Goa.", None) == {"switched"}
    assert false_project_claims("Switched to Goa.", "switched") == set()


@pytest.mark.asyncio
async def test_the_failing_acceptance_utterance_now_creates_and_saves_correctly(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("Create project called Nepal trip.", "Created project Nepal trip.")
    result = await wake.ask(
        "Okay. Create a project called interview preparation.",
        "Created project interview preparation.",
    )
    assert result["action"] == "created" and result["project_changed"] is True
    await wake.ask("My interview topic is SQL window functions.", "Noted.")
    rows = lab.rows()
    assert (
        "user",
        "My interview topic is SQL window functions.",
        "complete",
        "interview preparation",
    ) in rows
    assert voice.metrics.false_claims == 0 and wake.session.replies == []


@pytest.mark.asyncio
async def test_false_creation_claim_is_corrected_and_not_saved(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    result = await wake.ask("We will take the Jimny.")
    assert (
        result["project_changed"] is False
        and "No project was created" in result["note"]
    )
    assert wake.response()[0] is True
    wake.reply("Created project Jimny for you.")  # the model invents a change
    await settle(voice)
    assert voice.metrics.false_claims == 1 and voice.metrics.corrections == 1
    (correction,) = wake.session.replies
    assert "no project was created or switched" in correction
    assert "Nepal trip" in correction
    assert all("Created project Jimny" not in r[1] for r in lab.rows())
    # The spoken correction itself is accurate and is not re-corrected.
    wake.reply("Correction: no project was created or switched. You are in Nepal trip.")
    await settle(voice)
    assert voice.metrics.false_claims == 1 and len(wake.session.replies) == 1
    assert lab.rows()[-1][1].startswith("Correction: no project was created")


@pytest.mark.asyncio
async def test_false_switch_claim_after_a_clarification_is_corrected(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    asked = await wake.ask("switch to Tokyo")
    assert asked["status"] == "clarification"
    assert wake.response()[0] is True
    wake.reply("Switched to Tokyo.")
    await settle(voice)
    (correction,) = wake.session.replies
    assert (
        "no project was created or switched" in correction
        and "Nepal trip" in correction
    )


@pytest.mark.asyncio
async def test_a_true_switch_announcement_is_not_flagged(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("create project called Goa", "Created project Goa.")
    await wake.ask("Okay, switch to Nepal trip.", "Switched to Nepal trip.")
    assert voice.metrics.false_claims == 0 and wake.session.replies == []
