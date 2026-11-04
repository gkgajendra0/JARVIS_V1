"""Release gate for project memory (#303–#308): one realistic two-project life.

Real archive (SQLite schema 7, FTS5, provenance edges), real history authority
and Windows-session/Hello fakes, real routing, preload, search and forgetting;
only Gemini is simulated (its tool calls and replies are driven by the test).

G1  Separate Nepal-trip and Interview-prep projects: each wake's preload holds
    only the current project's rows.
G2  Cross-project retrieval: a question about the other project finds its rows,
    labelled with their project.
G3  Correction precedence: the newer owner statement comes last and is marked
    current.
G4  Long-term archive search beyond the preload window.
G5  Selective forgetting: only rows holding the words (and Jarvis replies made
    with them) go; the other project and unrelated rows stay, across restart.
G6  Grounding evidence: owner statements and Jarvis suggestions are labelled
    apart, the owner's own certainty words are kept verbatim, and the model is
    told how to treat tentative plans and Jarvis suggestions.
G7  Everything survives a full runtime restart.
"""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake

from jarvis.voice.agent import PROJECT_MEMORY_INSTRUCTIONS

lab = project_voice_tests.lab

NEPAL = "Nepal trip"
INTERVIEW = "Interview prep"


async def two_projects(lab, clock, *, filler=14):
    """The owner's week: a trip being planned and an interview being prepared."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("Our hotel in Kathmandu is Yak and Yeti.", "Noted.")
    await wake.ask("We will take the Jimny.", "Noted, the Jimny.")
    await wake.ask("Maybe we will visit Pokhara, not decided yet.", "Okay.")
    # A Jarvis suggestion the owner never accepted.
    await wake.ask("Any idea for a day trip?", "You could try Nagarkot for sunrise.")
    for number in range(filler):  # pushes the hotel out of the preload window
        wake.speech()
        wake.transcript(f"Packing note {number}: socks and chargers.")
        if number % 5 == 4:
            await settle(voice)
            clock.advance(31)  # read leases expire as real time passes
    await settle(voice)
    await wake.ask(
        "Correction: we will take the Thar, not the Jimny.", "Noted, the Thar."
    )
    await wake.ask(
        "create project called Interview prep", "Created project Interview prep."
    )
    await wake.ask("The interview panel is on Friday at ten.", "Noted.")
    await wake.ask("We decided I will present the caching project.", "Good choice.")
    wake.close()
    return voice


def project_of(lab, needle):
    return {title for _, text, _, title in lab.rows() if needle in text}


def preloaded(wake):
    return "\n".join(wake.agent.injected())


@pytest.mark.asyncio
async def test_g1_projects_are_separate(lab, clock):
    voice = await two_projects(lab, clock)
    assert project_of(lab, "Yak and Yeti") == {NEPAL}
    assert project_of(lab, "interview panel") == {INTERVIEW}
    wake = FastWake(voice)  # resumes the last project: Interview prep
    await wake.preload()
    context = preloaded(wake)
    assert "Current project: Interview prep." in context
    assert "interview panel" in context
    assert "Jimny" not in context and "Thar" not in context and "Pokhara" not in context
    wake.close()
    switch = Wake(voice)
    result = await switch.ask("switch to Nepal trip", "Switched to Nepal trip.")
    assert result["status"] == "ready" and result["action"] == "switched"
    assert result["previous_project"] == INTERVIEW
    assert all("interview" not in r["text"].casefold() for r in result["history"])


@pytest.mark.asyncio
async def test_g2_cross_project_retrieval_is_labelled(lab, clock):
    voice = await two_projects(lab, clock)
    switch = Wake(voice)
    await switch.ask("switch to Nepal trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("When is the interview panel?")
    found = await wake.turns.search_history("interview panel")
    assert found["status"] == "other_projects"
    hits = [r for r in found["history"] if "panel" in r["text"]]
    assert hits and {r["from_project"] for r in hits} == {INTERVIEW}


@pytest.mark.asyncio
async def test_g3_the_newer_correction_wins(lab, clock):
    voice = await two_projects(lab, clock)
    switch = Wake(voice)
    await switch.ask("switch to Nepal trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    # The correction is recent: it is in the preload, after nothing older.
    assert "Correction: we will take the Thar, not the Jimny." in preloaded(wake)
    wake.speech()
    wake.transcript("Which vehicle are we taking?")
    found = await wake.turns.search_history("Jimny")
    owner = [r["text"] for r in found["history"] if r["role"] == "owner"]
    # Search excludes rows already in the conversation (the correction is in
    # the preload), so the older statement comes back as history, and the
    # model already holds the newer correction.
    assert "We will take the Jimny." in owner
    assert "Correction: we will take the Thar, not the Jimny." not in owner
    assert "newest owner statement is current" in found["guidance"]
    rules = " ".join(PROJECT_MEMORY_INSTRUCTIONS.split())
    assert "a newer owner statement replaces an older one" in rules


@pytest.mark.asyncio
async def test_g4_archive_search_reaches_beyond_the_preload(lab, clock):
    voice = await two_projects(lab, clock)
    switch = Wake(voice)
    await switch.ask("switch to Nepal trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    assert "Yak and Yeti" not in preloaded(wake)  # older than the preload window
    assert "older history exists" in preloaded(wake)
    wake.speech()
    wake.transcript("Which hotel did we book in Kathmandu?")
    found = await wake.turns.search_history("hotel Kathmandu")
    assert any("Yak and Yeti" in r["text"] for r in found["history"])
    assert all(not r.get("from_project") for r in found["history"])  # this project


@pytest.mark.asyncio
async def test_g5_selective_forgetting_keeps_everything_else(lab, clock):
    voice = await two_projects(lab, clock)
    # A later Interview session that never had the Jimny row in its context.
    later = FastWake(voice)
    await later.preload()
    assert "Jimny" not in preloaded(later)
    await later.fast("Remind me what I present.", "The caching project.")
    later.close()
    before = lab.rows()
    switch = Wake(voice)
    await switch.ask("switch to Nepal trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Forget that we will take the Jimny.")
    result = await wake.turns.forget_history("Jimny")
    await settle(voice)
    assert result["status"] == "forgotten"
    after = lab.rows()
    texts = [r[1] for r in after]
    assert not any("jimny" in t.casefold() for t in texts)
    # Every owner row WITHOUT the word survives, in both projects.
    kept_owner = [
        r for r in before if r[0] == "user" and "jimny" not in r[1].casefold()
    ]
    for row in kept_owner:
        assert row in after, row
    assert project_of(lab, "interview panel") == {INTERVIEW}
    assert project_of(lab, "Yak and Yeti") == {NEPAL}
    # A Jarvis reply made without the Jimny row in its context is kept. (One
    # made in a session whose model context held it is removed with it, by
    # design, even in another project: it may restate the forgotten words.)
    assert ("assistant", "The caching project.", "complete", INTERVIEW) in after
    # Survives a full restart.
    await voice.aclose()
    restarted = await lab.runtime()
    w = FastWake(restarted)
    await w.preload()
    assert "Jimny" not in preloaded(w)
    w.speech()
    w.transcript("What vehicle?")
    found = await w.turns.search_history("Jimny")
    assert not any("Jimny" in r["text"] for r in found.get("history", ()))


@pytest.mark.asyncio
async def test_g6_grounding_evidence_keeps_who_said_it_and_how_sure(lab, clock):
    voice = await two_projects(lab, clock, filler=0)
    switch = Wake(voice)
    await switch.ask("switch to Nepal trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    context = preloaded(wake)
    # The owner's hedge is kept verbatim, as the owner's.
    assert "owner: Maybe we will visit Pokhara, not decided yet." in context
    # A Jarvis suggestion is labelled as Jarvis's, never as the owner's.
    assert "Jarvis: You could try Nagarkot for sunrise." in context
    assert "owner: You could try Nagarkot" not in context
    # The model is told how to use that evidence.
    rules = " ".join(PROJECT_MEMORY_INSTRUCTIONS.split())
    assert "Jarvis's replies and suggestions are not owner decisions" in rules
    assert "tentative" in rules and "not a decision" in rules
    # Search results carry the same labels.
    wake.speech()
    wake.transcript("Did we decide on Pokhara or Nagarkot?")
    found = await wake.turns.search_history("Pokhara Nagarkot")
    roles = {r["text"]: r["role"] for r in found.get("history", ())}
    for text, role in roles.items():
        if "Nagarkot for sunrise" in text:
            assert role == "Jarvis"
        if "Pokhara, not decided" in text:
            assert role == "owner"


@pytest.mark.asyncio
async def test_g7_both_projects_survive_restart(lab, clock):
    voice = await two_projects(lab, clock)
    await voice.aclose()
    restarted = await lab.runtime()
    wake = Wake(restarted)
    result = await wake.ask("switch to Nepal trip")
    assert result["status"] == "ready"
    assert any("Thar" in r["text"] for r in result["history"])
    wake.close()
    wake = Wake(restarted)
    result = await wake.ask("switch to Interview prep")
    assert any("Friday at ten" in r["text"] for r in result["history"])


# -- activation blockers with the owner's INSTALLED settings ----------------------


def test_the_installed_profile_can_activate_project_memory(
    monkeypatch, tmp_path, capsys
):
    """E:\\Jarvis\\Data\\LocalState\\machine.json today (read-only check):
    paid Gemini fallback on, personal context and learning APPLY. With the
    coexistence change these no longer block the flag (B2/B3 resolved)."""
    import json

    from jarvis.config import JarvisConfig
    from jarvis.voice import project_voice_production as production

    profile = tmp_path / "machine.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "settings": {
                    "JARVIS_AI_PROVIDER": "gemini",
                    "JARVIS_GEMINI_PAID_FALLBACK_ENABLED": "true",
                    "JARVIS_MEMORY_ENABLED": "true",
                    "JARVIS_PERSONAL_CONTEXT_MODE": "apply",
                    "JARVIS_PERSONAL_LEARNING_MODE": "apply",
                    "JARVIS_PROJECT_MEMORY_MODE": "voice",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(profile))
    for name in (
        "JARVIS_AI_PROVIDER",
        "JARVIS_GEMINI_PAID_FALLBACK_ENABLED",
        "JARVIS_MEMORY_ENABLED",
        "JARVIS_PERSONAL_CONTEXT_MODE",
        "JARVIS_PERSONAL_LEARNING_MODE",
        "JARVIS_PROJECT_MEMORY_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    config = JarvisConfig.from_environment()
    assert production.activation_blockers(config) == []
    assert production.production_project_memory_factory(config) is not None
    assert production.main(["--check"]) == 0
    assert "will start with Jarvis" in capsys.readouterr().out
