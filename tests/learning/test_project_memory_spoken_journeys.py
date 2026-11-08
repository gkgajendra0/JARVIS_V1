"""Project memory journeys driven with transcripts as speech-to-text writes them.

Every earlier production defect passed CI because tests used tidy, typed
phrasing ("create project called Nepal trip"). These journeys use the real
voice pipeline (VoiceProjectMemory, ProjectRouter, ProjectArchiveAccess,
ProjectConversationStore on SQLite schema 7 with FTS5, the real history
authority and Hello/Windows-session fakes) and check the DATABASE, not what
Jarvis said. Only Gemini is simulated.

Production fixtures (owner PC, 2026-11-04):
- "Okay. Now create a project. Called Nepal trip."  -> nothing created
- "Create a project. Called Nepal trip."            -> nothing created
"""

import pytest
from test_project_voice import Wake, settle
from test_project_voice import lab as voice_lab
from test_project_voice_fast_path import FastWake
from test_project_voice_forget_recall import ask_to_forget, index_hits, texts

lab = voice_lab

PRODUCTION_CREATE = (
    "Okay. Now create a project. Called Nepal trip.",
    "Create a project. Called Nepal trip.",
)
SPOKEN_CREATE = (
    *PRODUCTION_CREATE,
    "create a project called nepal trip",
    "Create a project called Nepal trip, please.",
    "Create a project called, Nepal trip.",
    'Create a project named "Nepal trip".',
    "Create a project, um, called Nepal trip.",
    "Create a project. Called. Nepal trip.",
    "Hey Jarvis. Create a project called Nepal trip.",
    "Can you create a project called Nepal trip?",
    "Create a project with the name Nepal trip.",
    "Create a project and call it Nepal trip.",
)
SPOKEN_SWITCH = (
    "Switch to Nepal trip.",
    "switch to nepal trip",
    "Switch to. Nepal trip.",
    "Okay, switch to Nepal trip, please.",
    "Can you switch to Nepal trip?",
    "Let's switch to Nepal trip.",
    "Switch back to Nepal trip.",
    "Switch over to Nepal trip.",
    "Switch to the Nepal trip project.",
    "Switch to project Nepal trip.",
    "Go to Nepal trip.",
    "Open the Nepal trip project.",
)


async def _two_projects(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("We will take the Jimny.", "Noted.")
    await wake.ask(
        "create project called Interview prep", "Created project Interview prep."
    )
    await wake.ask("The interview panel is on Friday at ten.", "Noted.")
    wake.close()
    return voice


def _project_of(lab, text):
    return {title for _, t, _, title in lab.rows() if t == text}


# -- creation ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", SPOKEN_CREATE)
async def test_spoken_creation_writes_one_clean_project(lab, utterance):
    voice = await lab.runtime()
    wake = Wake(voice)
    result = await wake.ask(utterance, "Created project Nepal trip.")
    assert result["status"] == "ready", result
    assert result["action"] == "created"
    await wake.ask("We will take the Jimny.", "Noted.")
    assert [t.casefold() for t in lab.titles()] == ["nepal trip"]
    assert _project_of(lab, "We will take the Jimny.") == {lab.titles()[0]}
    # Saying it again never creates a duplicate.
    again = await wake.ask(utterance, "Nepal trip is already open.")
    assert again["action"] in {"continued", "resumed", "switched"}
    assert [t.casefold() for t in lab.titles()] == ["nepal trip"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "utterance",
    [
        "Create a project. Called my mom about it.",
        "Create a project. Nepal trip.",
        "Create a project.",
    ],
)
async def test_unreadable_creation_asks_and_writes_no_project(lab, utterance):
    voice = await lab.runtime()
    wake = Wake(voice)
    result = await wake.ask(utterance)
    assert result["status"] == "clarification"
    assert lab.titles() == []
    assert (
        "No project was created or switched" in result.get("spoken", "")
        or "project" in str(result.get("question", "")).casefold()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "utterance",
    [
        "Go back to sleep.",
        "Open the window.",
        "I told him to create a project called Goa.",
        "We should go to Nepal in spring.",
        "Can you continue the explanation?",
    ],
)
async def test_ordinary_speech_creates_or_switches_nothing(lab, utterance):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    result = await wake.ask(utterance, "Okay.")
    assert result["status"] == "ready"
    assert result["action"] in {"continued", "resumed"}
    assert lab.titles() == ["Interview prep", "Nepal trip"]
    assert _project_of(lab, utterance) == {"Interview prep"}


# -- switching, isolation ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", SPOKEN_SWITCH)
async def test_spoken_switch_moves_later_turns_to_that_project(lab, utterance):
    voice = await _two_projects(lab)  # current: Interview prep
    wake = Wake(voice)
    result = await wake.ask(utterance, "Switched to Nepal trip.")
    assert (result["status"], result["action"]) == ("ready", "switched"), result
    await wake.ask("We also need a stove.", "Noted.")
    # The statement is stored in Nepal trip, not the previous project.
    assert _project_of(lab, "We also need a stove.") == {"Nepal trip"}
    assert lab.titles() == ["Interview prep", "Nepal trip"]


@pytest.mark.asyncio
async def test_switch_to_an_unknown_project_changes_nothing(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    result = await wake.ask("Switch to Goa trip.")
    assert result["status"] == "clarification"
    assert lab.titles() == ["Interview prep", "Nepal trip"]


@pytest.mark.asyncio
async def test_new_wake_preload_holds_only_the_current_project(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    await wake.ask("Can you switch to Nepal trip?", "Switched to Nepal trip.")
    wake.close()
    later = FastWake(voice)
    await later.preload()
    context = "\n".join(later.agent.injected())
    assert "Jimny" in context
    assert "interview panel" not in context


# -- corrections --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spoken_correction_is_stored_newest_last_in_its_project(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    await wake.ask("Switch to. Nepal trip.", "Switched to Nepal trip.")
    await wake.ask("Correction, we will take the Thar. Not the Jimny.", "Noted.")
    wake.close()
    rows = [t for _, t, _, title in lab.rows() if title == "Nepal trip"]
    assert rows.index("We will take the Jimny.") < rows.index(
        "Correction, we will take the Thar. Not the Jimny."
    )
    later = FastWake(voice)
    await later.preload()
    context = "\n".join(later.agent.injected())
    assert context.index("We will take the Jimny.") < context.index(
        "Correction, we will take the Thar. Not the Jimny."
    )


# -- forgetting ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "utterance",
    [
        "Forget that we will take the Jimny.",
        "Forget that, we will take the Jimny.",
        "Okay. Please forget. The Jimny.",
        "Delete everything about the Jimny, please.",
    ],
)
async def test_spoken_forget_removes_only_the_named_rows(lab, utterance):
    voice = await _two_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    result = await ask_to_forget(wake, utterance, "Jimny")
    await settle(voice)
    assert result["status"] == "forgotten", result
    assert not any("jimny" in t.casefold() for t in texts(lab))
    assert index_hits(lab, "Jimny") == 0
    assert "The interview panel is on Friday at ten." in texts(lab)
    assert lab.titles() == ["Interview prep", "Nepal trip"]


@pytest.mark.asyncio
async def test_forget_with_words_the_owner_did_not_say_deletes_nothing(lab):
    voice = await _two_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    before = texts(lab)
    result = await ask_to_forget(wake, "Forget that, please.", "Jimny")
    assert result["status"] == "denied"
    assert [t for t in texts(lab) if t != "Forget that, please."] == before
    assert index_hits(lab, "Jimny") > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["canceled", "error", "retries_exhausted"])
async def test_hello_not_verified_never_deletes(lab, authority_parts, status):
    from jarvis.authority.verifier import (
        StrongVerificationResult,
        StrongVerificationStatus,
    )

    def refuse(*, proposal, session_id):
        return StrongVerificationResult(
            StrongVerificationStatus(status),
            "fake-hello",
            "v",
            proposal.fingerprint,
            session_id,
            ("helper_timeout",) if status == "error" else (),
        )

    voice = await _two_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    authority_parts.hello.verify = refuse
    result = await ask_to_forget(wake, "Forget the Jimny.", "Jimny")
    assert result["status"] == "not_forgotten"
    assert "We will take the Jimny." in texts(lab)
    assert index_hits(lab, "Jimny") > 0


# -- restart ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_everything_survives_a_runtime_restart(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    await wake.ask("Create a project. Called Goa.", "Created project Goa.")
    await wake.ask("Maybe we visit in March, not decided yet.", "Okay.")
    wake.close()
    await voice.aclose()
    restarted = await lab.runtime()
    assert lab.titles() == ["Goa", "Interview prep", "Nepal trip"]
    wake = Wake(restarted)
    result = await wake.ask("Okay, switch to Nepal trip, please.", "Switched.")
    assert any("Jimny" in r["text"] for r in result["history"])
    assert not any("March" in r["text"] for r in result["history"])
    wake.close()
    later = FastWake(restarted)
    await later.preload()
    assert "Current project: Nepal trip." in "\n".join(later.agent.injected())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "utterance", ["Switch to Hindi.", "Can you switch to English?"]
)
async def test_switching_language_is_not_a_project_command(lab, utterance):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    result = await wake.ask(utterance, "ठीक है।")
    assert (result["status"], result["action"]) == ("ready", "continued")
    assert lab.titles() == ["Interview prep", "Nepal trip"]
