"""Jarvis may only claim a project change the application committed."""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import FakeSession, Wake, settle

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
        # Zanskar live test 2026-11-16: the owner's vehicle switch, not a project.
        ("You told me you were switching to the Thar on November 16, 2026.", set()),
        ("We're switching to the Fortuner for the trip.", set()),
        ("They switched to a later flight.", set()),
        ("Okay, switching you to Goa.", {"switched"}),
        ("I've switched you to Goa.", {"switched"}),
        ("I switched to Goa for you.", {"switched"}),
        ("Done, we've switched over to the Goa project.", {"switched"}),
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


@pytest.mark.asyncio
async def test_owner_vehicle_switch_in_a_reply_is_not_a_project_claim(lab):
    """The live trigger: no correction, and the accurate reply is saved."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask(
        "create project called Zanskar trip", "Created project Zanskar trip."
    )
    await wake.ask("We are taking the Thar.", "Understood.")
    text = "You told me you were switching to the Thar on November 16, 2026."
    await wake.ask("When did I tell you we were switching to the Thar?", text)
    await settle(voice)
    assert voice.metrics.false_claims == 0 and wake.session.replies == []
    assert lab.rows()[-1][1] == text


class StuckHandle:
    """A LiveKit speech handle whose generation never plays or finishes."""

    def __init__(self, *, finished=False):
        self.finished = finished
        self.interrupts = []

    def done(self):
        return self.finished

    def interrupt(self, **kwargs):
        self.interrupts.append(kwargs)

    async def wait_for_playout(self):
        return None


class HandleSession(FakeSession):
    def __init__(self, handle):
        super().__init__()
        self.handle = handle

    def generate_reply(self, **kwargs):
        super().generate_reply(**kwargs)
        return self.handle


async def false_claim_wake(lab, monkeypatch, handle):
    from jarvis.voice import project_voice

    monkeypatch.setattr(project_voice, "CORRECTION_PLAY_SECONDS", 0.05)
    voice = await lab.runtime()
    wake = Wake(voice)
    wake.session = HandleSession(handle)
    wake.turns.bind_session(wake.session)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(True))
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("We will take the Jimny.")
    assert wake.response()[0] is True
    wake.reply("Switched to Jimny for you.")  # a real false project claim
    await settle(voice)
    (correction,) = wake.session.replies
    assert "no project was created or switched" in correction
    return voice, wake, retired


@pytest.mark.asyncio
async def test_unplayed_correction_is_cancelled_and_the_wake_ends(
    lab, monkeypatch, caplog
):
    handle = StuckHandle()
    voice, _wake, retired = await false_claim_wake(lab, monkeypatch, handle)
    await asyncio.sleep(0.15)
    assert handle.interrupts == [{"force": True}]
    assert retired == [True]  # next wake is a fresh Gemini session
    assert voice.metrics.unplayed_corrections == 1
    assert "correction reply did not play" in caplog.text


@pytest.mark.asyncio
async def test_correction_that_finished_unheard_still_ends_the_wake(lab, monkeypatch):
    handle = StuckHandle(finished=True)
    voice, _wake, retired = await false_claim_wake(lab, monkeypatch, handle)
    await asyncio.sleep(0.15)
    assert handle.interrupts == []  # nothing left to cancel
    assert retired == [True] and voice.metrics.unplayed_corrections == 1


@pytest.mark.asyncio
async def test_correction_that_plays_keeps_the_wake(lab, monkeypatch):
    handle = StuckHandle()
    voice, wake, retired = await false_claim_wake(lab, monkeypatch, handle)
    wake.turns.observe_speech(SimpleNamespace(speech_handle=handle))
    assert wake.turns.allow_response_audio() is True  # its first audio frame
    await asyncio.sleep(0.15)
    assert handle.interrupts == [] and retired == []
    assert voice.metrics.unplayed_corrections == 0


@pytest.mark.asyncio
async def test_owner_speaking_over_a_pending_correction_keeps_the_wake(
    lab, monkeypatch
):
    handle = StuckHandle()
    voice, wake, retired = await false_claim_wake(lab, monkeypatch, handle)
    wake.speech()  # barge-in: LiveKit interrupts the correction itself
    await asyncio.sleep(0.15)
    assert handle.interrupts == [] and retired == []
    assert voice.metrics.unplayed_corrections == 0
