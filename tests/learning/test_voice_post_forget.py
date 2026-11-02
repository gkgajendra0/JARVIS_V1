"""Owner run 20261102T142548Z-adcc1a: after forgetting the active project.

1. With no active selection, an ordinary question opens the default General
   workspace. Acceptance must not call that an unexpected project change, but
   a named project created without a command still fails.
2. "...taking to Nepal..." must reference the surviving "Nepal trip" as
   evidence (partial, distinctive-word match) without switching to it;
   ambiguous names reference nothing and are reported as ambiguous.
3. Forgotten content stays inaccessible; Nepal trip stays intact.
"""

import json

import pytest
import test_project_voice as project_voice_tests
from test_project_routing import routed
from test_project_routing_decisions import lab as router_lab  # noqa: F401
from test_project_routing_decisions import live_titles
from test_voice_acceptance import labdir  # noqa: F401
from test_voice_diagnostics import FakeProtector, VoiceRun, report, voice_memory

from jarvis.memory.project_controls import ProjectControls
from jarvis.memory.project_routing import ProjectRouter
from jarvis.voice import voice_diagnostics as vd

lab = project_voice_tests.lab  # shared real-archive fixture

QUESTION = "Which vehicle are we taking to Nepal and what is the permit status?"


async def forget(access, title):
    controls = ProjectControls(access)
    catalog = await access.catalog()
    entry = next(e for e in catalog.entries if e.title == title)
    inspected = await controls.inspect_project(entry.selection.project_id)
    await controls.forget_project(
        entry.selection.project_id, expected_revision=inspected.archive_revision
    )


@pytest.mark.asyncio
async def test_post_forget_question_opens_general_and_reads_nepal_trip(
    lab,
    labdir,  # noqa: F811
):
    # Session 1: two projects; interview preparation is active, then forgotten.
    voice = await lab.runtime()
    wake = project_voice_tests.Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("We will take the Jimny.", "Noted.")
    await wake.ask("The permits are sorted.", "Good.")
    await wake.ask("create project called interview preparation", "Created.")
    await wake.ask("My interview topic is SQL window functions.", "Noted.")
    wake.close()
    await voice.aclose()
    await forget((await lab.runtime()).access, "interview preparation")
    assert lab.titles() == ["Nepal trip"]

    # Session 2 (restart, diagnostics on): no active selection.
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say("What is my interview topic?", "I don't have that.")
    await run.say(QUESTION, "The Jimny, and the permits are sorted.")
    run.close()
    data, _ = await report(diagnostics, labdir)
    us = data["sessions"][0]["utterances"]

    first = next(p for p in us[0]["project"] if p["kind"] == "prepared")
    assert (first["action"], first["project"]) == ("created", "General")
    assert first["previous_selection"] is None
    assert first["announcement"] == ""  # silent General bootstrap, audited as created
    # 3. The forgotten topic is not given to the model, from anywhere.
    delivered = [
        p for u in us for p in u["project"] if p["kind"] == "delivered_to_model"
    ]
    assert "SQL window functions" not in json.dumps(delivered)

    second = next(p for p in us[1]["project"] if p["kind"] == "prepared")
    assert second["project"] == "General" and second["action"] == "continued"
    assert second["references"] == ["Nepal trip"]  # partial "Nepal" -> Nepal trip
    given = next(p for p in us[1]["project"] if p["kind"] == "delivered_to_model")
    texts = {
        r["text"] for r in given["history"] if r.get("from_project") == "Nepal trip"
    }
    assert {"We will take the Jimny.", "The permits are sorted."} <= texts

    verdicts = vd.assess(data)
    first_result, second_result = verdicts["results"]
    assert "unexpected_project_change" not in first_result["fail"]
    assert first_result["info"] == ["default_workspace_opened"]
    assert first_result["verdict"] == "PASS"
    assert second_result["verdict"] == "PASS"
    # 3. Nepal trip intact, nothing switched to it, interview stays forgotten.
    assert lab.titles() == ["General", "Nepal trip"]
    nepal_rows = [r for r in lab.rows() if r[3] == "Nepal trip"]
    assert ("user", "The permits are sorted.", "complete", "Nepal trip") in nepal_rows
    assert all("SQL" not in r[1] for r in lab.rows())


@pytest.mark.asyncio
async def test_general_automatic_bootstrap_and_reuse_are_silent(router_lab):  # noqa: F811
    access = router_lab.access()
    router = ProjectRouter(access)

    # First normal question: General is created but not announced.
    created = await routed(router, "What is my interview preparation topic?")
    assert created.title == "General"
    assert created.create and created.action == "created"
    assert created.announcement == ""

    # Explicit commands still announce their outcomes.
    named = await routed(router, "create project called interview preparation")
    assert named.announcement == "Created project interview preparation."
    explicit_switch = await routed(router, "switch to General")
    assert explicit_switch.action == "switched"
    assert explicit_switch.announcement == "Switched to General."

    # A new voice process resumes existing General silently for normal speech.
    restarted = ProjectRouter(access)
    resumed = await routed(restarted, "Can you help me?")
    assert resumed.title == "General" and resumed.action == "resumed"
    assert resumed.announcement == ""

    # After forgetting a selected project, an existing General is reused
    # silently rather than speaking "Switched to General".
    await routed(restarted, "switch to interview preparation")
    await forget(access, "interview preparation")
    reopened = await routed(restarted, "What is my interview preparation topic?")
    assert reopened.title == "General" and reopened.action == "switched"
    assert reopened.announcement == ""
    assert (await access.catalog()).current == created.selection


@pytest.mark.asyncio
async def test_voice_tool_does_not_announce_automatic_general(lab):
    voice = await lab.runtime()
    wake = project_voice_tests.Wake(voice)
    result = await wake.ask("What is my interview preparation topic?")
    assert result["project"] == "General"
    assert result["action"] == "created"
    assert result["project_changed"] is True  # internally committed
    assert result["announcement"] == ""
    assert "do not mention opening" in result["guidance"]
    wake.close()
    await voice.aclose()


def test_named_project_created_without_a_command_still_fails():
    def prepared(project, previous):
        return {
            "kind": "prepared",
            "status": "ready",
            "action": "created",
            "project": project,
            "previous_selection": previous,
            "saved_text": "We will take the Jimny.",
            "at": "2026-11-02T14:30:00.500+00:00",
        }

    def data(*events):
        utterances = [
            {
                "id": f"r/s1/u{i}",
                "segments": [{}],
                "speech_seconds": 1.0,
                "speech_ended_at": "2026-11-02T14:30:00.000+00:00",
                "asr": [],
                "accepted": [
                    {
                        "at": "2026-11-02T14:30:00.400+00:00",
                        "text": "We will take the Jimny.",
                    }
                ],
                "project": [event],
                "responses": [],
                "assistant": [],
                "flags": [],
                "latency_ms": None,
            }
            for i, event in enumerate(events)
        ]
        return {
            "run": {"run_id": "r"},
            "sessions": [{"utterances": utterances, "unmatched": []}],
        }

    results = vd.assess(
        data(
            prepared("Jimny", None),  # a named project, even with no selection
            prepared("General", "Nepal trip"),  # General while a project was active
            prepared("General", None),  # the legal bootstrap
        )
    )["results"]
    assert "unexpected_project_change" in results[0]["fail"]
    assert "unexpected_project_change" in results[1]["fail"]
    assert results[2]["fail"] == [] and results[2]["info"] == [
        "default_workspace_opened"
    ]
    # Older records without the prior selection are never assumed legal.
    legacy = prepared("General", None)
    del legacy["previous_selection"]
    assert "unexpected_project_change" in vd.assess(data(legacy))["results"][0]["fail"]


@pytest.mark.asyncio
async def test_partial_names_reference_without_switching(router_lab):  # noqa: F811
    router = ProjectRouter(router_lab.access())
    nepal = await routed(router, "create project called Nepal trip")
    chores = await routed(router, "create project called weekend chores")
    asked = await routed(router, QUESTION)
    assert asked.selection == chores.selection and asked.action == "continued"
    assert asked.references == (nepal.selection,)
    assert asked.ambiguous_reference_titles == ()
    # Generic words alone never name a project.
    for text in ("How was your trip?", "What is the plan?", "Any travel notes?"):
        generic = await routed(router, text)
        assert generic.references == () and generic.selection == chores.selection
    # Words embedded in other words do not count ("Nepalese" is not "Nepal").
    assert (await routed(router, "Is Nepalese food spicy?")).references == ()
    assert sorted(await live_titles(router.access)) == ["Nepal trip", "weekend chores"]


@pytest.mark.asyncio
async def test_ambiguous_partial_names_reference_nothing(router_lab):  # noqa: F811
    router = ProjectRouter(router_lab.access())
    trip = await routed(router, "create project called Nepal trip")
    await routed(router, "create project called Nepal trek")
    chores = await routed(router, "create project called weekend chores")
    asked = await routed(router, "What did we decide about Nepal?")
    assert asked.selection == chores.selection
    assert asked.references == ()
    assert asked.ambiguous_reference_titles == ("Nepal trek", "Nepal trip")
    # Naming it fully is unambiguous; the exact title wins over the partial one.
    exact = await routed(router, "What did we decide about the Nepal trip?")
    assert exact.references == (trip.selection,)
    assert exact.ambiguous_reference_titles == ()
    assert exact.selection == chores.selection


@pytest.mark.asyncio
async def test_ambiguity_reaches_the_model_and_the_report(lab, labdir):  # noqa: F811
    voice = await lab.runtime()
    wake = project_voice_tests.Wake(voice)
    await wake.ask("create project called Nepal trip", "Done.")
    await wake.ask("create project called Nepal trek", "Done.")
    await wake.ask("create project called weekend chores", "Done.")
    result = await wake.ask("What did we decide about Nepal?")
    assert result["project"] == "weekend chores" and "referenced_projects" not in result
    assert result["ambiguous_projects"] == ["Nepal trek", "Nepal trip"]
    assert "Ask which one" in result["ambiguity_note"]
    assert all(not r.get("from_project") for r in result["history"])
    wake.close()
