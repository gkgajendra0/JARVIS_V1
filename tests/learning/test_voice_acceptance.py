"""VAD segmentation, unmatched-speech classification and acceptance verdicts.

Regression for run 20261102T130052Z-3edaf5: 15 VAD segments but 11 accepted
turns, several "no transcript" segments adjacent to accepted ones, and a
misrouted "Okay. Create a project called interview preparation." with a
false "Created project" reply.
"""

import asyncio
import io
import time
import wave

import pytest
import test_project_voice as project_voice_tests
from test_voice_diagnostics import FakeProtector, VoiceRun, frame, report, voice_memory

import jarvis.memory.project_routing as routing
from jarvis.conversation import ConversationRole
from jarvis.voice import voice_diagnostics as vd

lab = project_voice_tests.lab  # shared real-archive fixture


@pytest.fixture
def labdir(tmp_path):
    root = tmp_path / "profile"
    root.mkdir()
    (root / "project-memory.marker").write_text("{}")
    return root


async def segment(run, value, frames=5):
    run.session.emit("user_state_changed", old_state="listening", new_state="speaking")
    run.conversation.begin_user_activity()
    if run.turns is not None:
        run.turns.observe_activity()
    await asyncio.sleep(0)
    for _ in range(frames):
        run.tap(frame(value=value), time.monotonic())
    run.session.emit("user_state_changed", old_state="speaking", new_state="listening")


def samples(data, utterance):
    with wave.open(io.BytesIO(data["audio"][utterance["id"]])) as audio:
        return audio.readframes(audio.getnframes())


@pytest.mark.asyncio
async def test_a_pause_mid_sentence_is_one_utterance_with_complete_audio(labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics)
    await segment(run, value=3)  # "Okay." (local VAD ends after ~0.55 s)
    for _ in range(4):
        run.tap(frame(value=0), time.monotonic())  # the pause itself
    await segment(run, value=5)  # "Create a project called interview preparation."
    run.recognise("Okay. Create a project called interview preparation.")
    run.accept("Okay. Create a project called interview preparation.")
    run.close()
    data, page = await report(diagnostics, labdir)
    (u,) = data["sessions"][0]["utterances"]
    assert len(u["segments"]) == 2 and u["epochs"] == [1, 2]
    assert [a["text"] for a in u["accepted"]] == [
        "Okay. Create a project called interview preparation."
    ]
    assert "no_accepted_transcript" not in u["flags"]
    audio = samples(data, u)
    # Both halves and the pause between them are in the one recording.
    for value in (3, 0, 5):
        assert (value).to_bytes(2, "little") * 160 in audio
    assert audio.index((3).to_bytes(2, "little") * 160) < audio.index(
        (5).to_bytes(2, "little") * 160
    )
    assert u["audio"]["covers_segments"] == 2
    assert "2 speech segments, one utterance" in page


@pytest.mark.asyncio
async def test_a_jarvis_reply_or_a_long_gap_starts_a_new_utterance(labdir):
    diagnostics = vd.VoiceDiagnostics(
        labdir, protector=FakeProtector(), group_gap_seconds=0.05
    )
    run = VoiceRun(diagnostics)
    await segment(run, value=3)
    run.accept("first")
    await run.answer("Reply.")  # Jarvis speaks: the first utterance is complete
    await segment(run, value=4)  # during/after the reply
    run.session.emit("agent_state_changed", old_state="speaking", new_state="listening")
    await asyncio.sleep(0.1)  # longer than the grouping gap
    await segment(run, value=5)
    run.close()
    data, _ = await report(diagnostics, labdir)
    first, second, third = data["sessions"][0]["utterances"]
    assert [len(u["segments"]) for u in (first, second, third)] == [1, 1, 1]
    assert second["overlapped_reply"] is True
    assert second["unmatched_reason"] == "during_jarvis_reply_echo_or_barge_in"
    assert third["unmatched_reason"] == "very_short_segment"


@pytest.mark.asyncio
async def test_unmatched_speech_is_classified_not_assumed_dropped(labdir):
    diagnostics = vd.VoiceDiagnostics(
        labdir, protector=FakeProtector(), group_gap_seconds=0.0
    )
    run = VoiceRun(diagnostics)
    await segment(run, value=3)
    run.recognise("create project called Goa")  # recognised, never accepted
    await asyncio.sleep(0.01)
    await segment(run, value=4)
    run.close()
    data, _ = await report(diagnostics, labdir)
    recognised, short = data["sessions"][0]["utterances"]
    assert recognised["unmatched_reason"] == "recognised_but_not_accepted"
    assert short["unmatched_reason"] == "very_short_segment"
    verdicts = vd.assess(data)
    assert {r["verdict"] for r in verdicts["results"]} == {"REVIEW"}
    assert (
        "unmatched_speech:recognised_but_not_accepted"
        in verdicts["results"][0]["review"]
    )
    assert "dropped" not in str(verdicts)


@pytest.mark.asyncio
async def test_the_field_failure_is_reported_as_fail(lab, labdir, monkeypatch):
    """Reproduce 3edaf5: the parser misses the command (old behaviour), the turn
    lands in Nepal trip, and Gemini claims the project was created."""
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say("create project called Nepal trip", "Created project Nepal trip.")
    # The 73b1b4d6 router: no lead-in handling, so the prefix check missed too.
    real = routing.parse_project_command
    monkeypatch.setattr(routing, "strip_lead_in", lambda text: text)
    monkeypatch.setattr(routing, "embedded_project_command", lambda text: (None, None))
    monkeypatch.setattr(
        routing,
        "parse_project_command",
        lambda text: (None, None) if text.startswith("Okay.") else real(text),
    )
    await run.say(
        "Okay. Create a project called interview preparation.",
        "Created project interview preparation.",
    )
    monkeypatch.undo()
    run.close()
    data, page = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    bad = verdicts["results"][1]
    assert bad["verdict"] == "FAIL"
    assert "command_misrouted" in bad["fail"] and "false_project_claim" in bad["fail"]
    assert (bad["action"], bad["project"]) == ("continued", "Nepal trip")
    assert "correction_spoken" in bad["review"]
    assert verdicts["verdict"] == "FAIL" and verdicts["counts"]["FAIL"] == 1
    assert 'Acceptance: <span class="FAIL">FAIL</span>' in page


@pytest.mark.asyncio
async def test_unexpected_project_change_is_a_fail(lab, labdir, monkeypatch):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say("create project called Nepal trip", "Created project Nepal trip.")
    real = routing.parse_project_command
    monkeypatch.setattr(
        routing,
        "parse_project_command",
        lambda text: ("Jimny", "create") if "Jimny" in text else real(text),
    )
    await run.say("We will take the Jimny.", "Created project Jimny.")
    monkeypatch.setattr(routing, "parse_project_command", real)
    run.close()
    data, _ = await report(diagnostics, labdir)
    result = vd.assess(data)["results"][1]
    assert "unexpected_project_change" in result["fail"]


@pytest.mark.asyncio
async def test_gate_recovery_unrecovered_and_interruption_checks(lab, labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    run = VoiceRun(diagnostics, voice)
    await run.say("create project called Nepal", "Created project Nepal.")
    # Recovered: withheld, repaired, then played.
    await run.speak()
    run.accept("We will take the Jimny.")
    assert await run.answer("Sure.") is False
    await project_voice_tests.settle(voice)
    await run.turns.prepare()
    assert await run.answer("Noted, the Jimny.") is True
    await project_voice_tests.settle(voice)
    # Unrecovered: withheld and the session ends before any answer.
    await run.speak()
    run.accept("And the permits?")
    assert await run.answer("They are sorted.") is False
    run.close()
    data, _ = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    _, recovered, unrecovered = verdicts["results"]
    assert (
        recovered["verdict"] == "REVIEW"
        and "context_gate_recovered" in recovered["review"]
    )
    assert "withheld_answer_not_recovered" in unrecovered["fail"]
    assert "interruption_not_exercised" in verdicts["run_review"]


@pytest.mark.asyncio
async def test_a_clean_run_with_an_interruption_passes(lab, labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say(
        "Okay, create project called Nepal trip", "Created project Nepal trip."
    )
    await run.say("We will take the Jimny.", "Noted, the Jimny.")
    await run.speak()
    run.recognise("Tell me everything we planned.")
    run.accept("Tell me everything we planned.")
    await run.turns.prepare()
    await run.answer("We planned the Jimny and")
    run.accept(
        "We planned the Jimny and", role=ConversationRole.ASSISTANT, interrupted=True
    )
    await project_voice_tests.settle(run.voice)
    await run.say("Which vehicle?", "The Jimny.")
    run.close()
    data, _ = await report(diagnostics, labdir)
    verdicts = vd.assess(data)
    assert verdicts["run_review"] == []
    assert [r["verdict"] for r in verdicts["results"]] == ["PASS"] * 4
    assert verdicts["not_tested"] == [] and verdicts["capture_anomalies"] == 0
    assert all(
        r["capture"] == "not_verified_listen_to_audio" for r in verdicts["results"]
    )
    assert "does NOT verify" in verdicts["note"]
    assert verdicts["verdict"] == "PASS"
    path = vd.write_report(labdir, FakeProtector())
    machine = (path.parent / "acceptance.json").read_text(encoding="utf-8")
    assert (
        '"verdict": "PASS"' in machine
        and '"schema": "jarvis-voice-acceptance-v1"' in machine
    )
    vd.prune(labdir / "voice-diagnostics", retention_days=7, keep_runs=5)
    assert not (path.parent / "acceptance.json").exists()  # transient like the HTML
