"""Acceptance run 20261102T133034Z-7ab7ad regressions.

Persistence is not capture: a turn saved exactly as accepted can still lack
what the owner said, because LiveKit's Gemini plugin finalises the user
transcript the moment Gemini emits a tool call (``_handle_tool_calls`` ->
``_mark_current_generation_done``), while Gemini's input transcription can
still be catching up with the audio.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_voice_acceptance import labdir  # noqa: F401
from test_voice_diagnostics import FakeProtector, VoiceRun, report, voice_memory

from jarvis.voice import voice_diagnostics as vd
from jarvis.voice.project_voice import FALLBACK_INSTRUCTIONS, REPAIR_INSTRUCTIONS

lab = project_voice_tests.lab  # shared real-archive fixture


@pytest.mark.asyncio
async def test_transcript_cut_at_tool_call_is_a_capture_fail_not_a_pass(
    lab,
    labdir,  # noqa: F811
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say("create project called Nepal trip", "Created project Nepal trip.")
    await run.speak()
    run.recognise("We will take", final=False)
    run.recognise("We will take")  # finalised when Gemini called the tool
    run.accept("We will take")
    await run.turns.prepare()
    # Gemini's transcription catches up afterwards, in a new generation.
    run.recognise("the Jimny.", final=False, item="item-2")
    await run.answer("Understood. The Jimny will be ready.")
    await project_voice_tests.settle(run.voice)
    run.close()
    data, page = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    row = verdicts["results"][1]
    assert row["accepted_transcript"] == "We will take"
    assert row["verdict"] == "FAIL"
    assert "recognised_words_not_saved:jimny" in row["fail"]
    assert "reply_uses_unsaved_names:jimny" in row["review"]
    assert row["capture"] == "anomaly"
    assert verdicts["capture_anomalies"] == 1
    assert "PASS ≠ heard correctly" in page


def test_few_words_for_long_speech_is_flagged_for_listening():
    utterance = {
        "id": "r/s1/u1",
        "segments": [{}],
        "speech_seconds": 3.0,
        "speech_ended_at": "2026-11-02T13:30:00.000+00:00",
        "asr": [],
        "accepted": [{"at": "2026-11-02T13:30:00.500+00:00", "text": "We will take"}],
        "project": [
            {
                "kind": "prepared",
                "status": "ready",
                "action": "continued",
                "project": "Nepal trip",
                "saved_text": "We will take",
                "at": "2026-11-02T13:30:00.600+00:00",
            }
        ],
        "responses": [],
        "assistant": [],
        "flags": [],
        "latency_ms": None,
    }
    data = {
        "run": {"run_id": "r"},
        "sessions": [{"utterances": [utterance], "unmatched": []}],
    }
    row = vd.assess(data)["results"][0]
    assert row["verdict"] == "REVIEW"
    assert "transcript_may_be_incomplete" in row["review"]
    assert row["latency_ms"]["turn_saved"] == 600


@pytest.mark.asyncio
async def test_standby_acknowledgement_passes_the_gate_without_project_repair(
    lab,
    labdir,  # noqa: F811
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    run = VoiceRun(diagnostics, voice)
    await run.say("create project called Nepal trip", "Created project Nepal trip.")
    await run.speak()
    run.recognise("Okay Jarvis, go to sleep.")
    run.accept("Okay Jarvis, go to sleep.")
    # Gemini calls the deterministic control tool, not prepare_project_turn.
    run.session.emit(
        "function_tools_executed",
        function_calls=[SimpleNamespace(name="enter_standby")],
    )
    assert await run.answer("Going quiet. Say the wake word when you need me.")
    await project_voice_tests.settle(voice)
    assert REPAIR_INSTRUCTIONS not in run.session.replies
    assert FALLBACK_INSTRUCTIONS not in run.session.replies
    assert voice.metrics.fallbacks == 0 and voice.metrics.repairs == 0
    # The owner's words are still saved like any accepted turn.
    assert ("user", "Okay Jarvis, go to sleep.", "complete", "Nepal trip") in lab.rows()
    run.close()
    data, _ = await report(diagnostics, labdir)
    row = vd.assess(data)["results"][1]
    assert row["verdict"] == "PASS"


@pytest.mark.asyncio
async def test_other_tools_do_not_bypass_the_context_gate(lab):
    voice = await lab.runtime()
    wake = project_voice_tests.Wake(voice)
    await wake.ask("create project called Nepal trip", "Done.")
    wake.speech()
    wake.transcript("What vehicle are we taking?")
    wake.turns.observe_tools_executed(
        SimpleNamespace(function_calls=[SimpleNamespace(name="search_web")])
    )
    assert wake.response()[0] is False
    await project_voice_tests.settle(voice)
    assert wake.session.replies == [REPAIR_INSTRUCTIONS]


@pytest.mark.asyncio
async def test_wake_acknowledgement_is_an_identified_benign_uncorrelated_event(
    labdir,  # noqa: F811
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics)
    run.accept("Yes?", role=project_voice_tests.ConversationRole.ASSISTANT)
    await run.speak()
    run.accept("What is the capital of Nepal?")
    await run.answer("Kathmandu.")
    run.close()
    data, page = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    (event,) = verdicts["uncorrelated_events"]
    assert event["kind"] == "assistant_before_any_owner_speech" and event["benign"]
    assert not any(r.startswith("uncorrelated_events") for r in verdicts["run_review"])
    assert verdicts["not_tested"] == ["interruption"]
    assert "Not tested in this run:</b> interruption" in page
    assert "assistant_before_any_owner_speech" in page


@pytest.mark.asyncio
async def test_latency_breakdown_shows_where_a_repaired_turn_spent_time(
    lab,
    labdir,  # noqa: F811
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    run = VoiceRun(diagnostics, voice)
    await run.speak()
    run.recognise("create project called Nepal")
    run.accept("create project called Nepal")
    assert await run.answer("Sure!") is False  # answered without the tool
    await project_voice_tests.settle(voice)
    await asyncio.sleep(0.02)
    await run.turns.prepare()
    assert await run.answer("Created project Nepal.") is True
    await project_voice_tests.settle(voice)
    run.close()
    data, _ = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    stages = verdicts["results"][0]["latency_ms"]
    for stage in (
        "final_recognition",
        "transcript_accepted",
        "turn_saved",
        "first_answer_withheld",
        "repair_requested",
        "tool_called",
        "context_delivered",
        "answer_released",
    ):
        assert stage in stages, stage
    assert stages["first_answer_withheld"] <= stages["answer_released"]
    assert stages["repair_requested"] <= stages["tool_called"]
    assert "answer_released" in verdicts["latency_summary_ms"]
