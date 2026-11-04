"""Lab-only end-to-end voice diagnostics.

Events arrive in the real runtime's order: the diagnostics' VAD handler runs
before the runtime advances the activity epoch; frames are the post-wake audio
forwarded to Gemini; Gemini input transcription (partial/final) precedes the
bridge's canonical USER turn. Project routing, recording and read-back are real.
"""

import asyncio
import inspect
import io
import os
import time
import wave
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import FakeHandle, FakeSession, settle

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice import voice_diagnostics as vd
from jarvis.voice.project_voice import VoiceProjectMemory

lab = project_voice_tests.lab  # shared real-archive fixture


class FakeProtector:
    """Reversible stand-in for Windows DPAPI; output is never plaintext."""

    def seal(self, data, *, purpose):
        assert purpose == vd.PURPOSE
        return b"SEALED1" + bytes(b ^ 0x5A for b in data)

    def unseal(self, data, *, purpose):
        assert purpose == vd.PURPOSE and data.startswith(b"SEALED1")
        return bytes(b ^ 0x5A for b in data[7:])


class FakeAgentSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.handlers = {}

    def on(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)

    def emit(self, name, **fields):
        for handler in self.handlers.get(name, ()):
            handler(SimpleNamespace(**fields))


class FakeBridge:
    def __init__(self, conversation):
        self.conversation = conversation
        self.turn_observers = []
        self.close_observers = []

    def add_accepted_turn_observer(self, observer):
        self.turn_observers.append(observer)

    def add_close_observer(self, observer):
        self.close_observers.append(observer)


def frame(value=1, samples=160, rate=16000):
    pcm = (value).to_bytes(2, "little", signed=True) * samples
    return SimpleNamespace(
        data=memoryview(pcm).cast("h"),
        sample_rate=rate,
        num_channels=1,
        samples_per_channel=samples,
    )


class VoiceRun:
    """One wake session wired like the lab: diagnostics + project memory."""

    def __init__(self, diagnostics, voice=None):
        self.diagnostics = diagnostics
        self.voice = voice
        self.conversation = ConversationSession()
        self.conversation.start()
        self.session = FakeAgentSession()
        self.bridge = FakeBridge(self.conversation)
        diagnostics.attach(self.session, self.bridge)  # voice_session_observer
        self.tap = diagnostics.audio_tap(self.bridge)  # session_audio_tap
        self.turns = None
        if voice is not None:
            self.turns = voice.session(self.conversation)
            self.turns.bind_session(self.session)
            self.bridge.add_accepted_turn_observer(self.turns.observe_turn)
            self.bridge.add_close_observer(self.turns.close)

    async def speak(self, frames=10, value=7):
        for _ in range(3):
            self.tap(frame(value=1), time.monotonic())  # pre-roll
        self.session.emit(
            "user_state_changed", old_state="listening", new_state="speaking"
        )
        self.conversation.begin_user_activity()  # the runtime's own handler
        if self.turns is not None:
            self.turns.observe_activity()
        await asyncio.sleep(0)
        for _ in range(frames):
            self.tap(frame(value=value), time.monotonic())
        self.session.emit(
            "user_state_changed", old_state="speaking", new_state="listening"
        )

    def recognise(self, text, *, final=True, item="item-1"):
        self.session.emit(
            "user_input_transcribed", transcript=text, is_final=final, item_id=item
        )

    def accept(self, text, role=ConversationRole.USER, **kw):
        turn = self.conversation.accept_turn(role, text, **kw)
        for observer in self.bridge.turn_observers:
            observer(turn)
        return turn

    def replay(self, turn):
        for observer in self.bridge.turn_observers:
            observer(turn)

    async def answer(self, text):
        handle = FakeHandle()
        if self.turns is not None:
            self.turns.observe_speech(SimpleNamespace(speech_handle=handle))
            allowed = self.turns.allow_response_audio()
        else:
            allowed = True
        if allowed:
            self.session.emit(
                "agent_state_changed", old_state="thinking", new_state="speaking"
            )
            self.accept(text, role=ConversationRole.ASSISTANT)
        return allowed

    async def say(self, words, reply="Okay.", *, call_tool=True):
        await self.speak()
        self.recognise(words[: max(1, len(words) // 2)], final=False)
        self.recognise(words)
        self.accept(words)
        if call_tool and self.turns is not None:
            await self.turns.prepare()
        await self.answer(reply)
        if self.voice is not None:
            await settle(self.voice)

    def close(self):
        for observer in self.bridge.close_observers:
            observer()


@pytest.fixture
def labdir(tmp_path):
    root = tmp_path / "profile"
    root.mkdir()
    (root / "project-memory.marker").write_text("{}")
    return root


async def report(diagnostics, labdir):
    await diagnostics.aclose()
    data = vd.load_run(diagnostics.run_dir, FakeProtector())
    return data, vd.render_report(data)


async def voice_memory(lab, diagnostics):
    # Same real archive/grant path as test_project_voice, with diagnostics on.
    voice = await lab.runtime()
    voice.diagnostics = diagnostics
    return voice


@pytest.mark.asyncio
async def test_missing_transcript_is_tracked_with_its_audio(labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics)
    await run.speak(frames=5, value=9)  # noise or speech Gemini never transcribed
    run.close()
    data, page = await report(diagnostics, labdir)
    (utterance,) = data["sessions"][0]["utterances"]
    assert (
        utterance["accepted"] == [] and "no_accepted_transcript" in utterance["flags"]
    )
    assert utterance["epochs"] == [1]
    assert utterance["unmatched_reason"] == "very_short_segment"  # instant in tests
    with wave.open(io.BytesIO(data["audio"][utterance["id"]])) as audio:
        assert audio.getframerate() == 16000
        frames = audio.readframes(audio.getnframes())
    # Pre-roll (value 1) followed by the utterance itself (value 9).
    assert frames.startswith((1).to_bytes(2, "little") * 160)
    assert (9).to_bytes(2, "little") * 160 in frames
    assert "without accepted transcript: 1" in page
    assert "— none —" in page


@pytest.mark.asyncio
async def test_misheard_project_name_is_visible_next_to_its_audio(lab, labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    # The owner said "Nepal trip"; recognition heard "Naples trip".
    await run.say("create project called Naples trip", "Created project Naples trip.")
    run.close()
    data, page = await report(diagnostics, labdir)
    (u,) = data["sessions"][0]["utterances"]
    assert [a["text"] for a in u["asr"] if a["final"]] == [
        "create project called Naples trip"
    ]
    assert u["asr"][0]["final"] is False  # the partial is kept too
    prepared = next(p for p in u["project"] if p["kind"] == "prepared")
    assert prepared["action"] == "created" and prepared["project"] == "Naples trip"
    assert prepared["saved_text"] == "create project called Naples trip"
    assert prepared["receipt"]["status"]
    assert u["id"] in data["audio"]
    assert "project_created: Naples trip" in page
    assert "Recognition is not ground truth" in page
    assert '<audio controls src="data:audio/wav;base64,' in page
    assert u["latency_ms"] is not None


@pytest.mark.asyncio
async def test_duplicate_recognition_and_turn_events_are_flagged_saved_once(
    lab,
    labdir,
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    run = VoiceRun(diagnostics, voice)
    await run.speak()
    run.recognise("create project called Goa")
    run.recognise("create project called Goa")  # duplicate final event
    turn = run.accept("create project called Goa")
    run.replay(turn)  # duplicate accepted-turn event
    await run.turns.prepare()
    await settle(voice)
    run.close()
    data, page = await report(diagnostics, labdir)
    (u,) = data["sessions"][0]["utterances"]
    assert [p["kind"] for p in u["project"]].count("prepared") == 1
    assert "duplicate_recognition_event" in page and "duplicate_turn_event" in page
    assert [r[1] for r in lab.rows()] == ["create project called Goa"]


@pytest.mark.asyncio
async def test_misrouting_would_be_visible_question_stays_switch_names_previous(
    lab,
    labdir,
):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics, await voice_memory(lab, diagnostics))
    await run.say("create project called Nepal")
    await run.say("We will take the Jimny.")
    await run.say("create project called Interview")
    await run.say("What's the status of my Nepal trip?", "The Jimny.")
    await run.say("switch to Nepal", "Switched to Nepal.")
    await run.say("switch to tokyo", "Which project?")
    run.close()
    data, page = await report(diagnostics, labdir)
    us = data["sessions"][0]["utterances"]

    def prepared(i):
        return next(p for p in us[i]["project"] if p["kind"] == "prepared")

    assert (
        prepared(3)["action"],
        prepared(3)["project"],
        prepared(3)["references"],
    ) == (
        "continued",
        "Interview",
        ["Nepal"],
    )
    assert (prepared(4)["action"], prepared(4)["previous"]) == ("switched", "Interview")
    assert prepared(5)["status"] == "clarification"
    assert "No project called" in prepared(5)["question"]
    assert "project_switched: Nepal" in page and "(from Interview)" in page
    assert page.count("project_created:") == 2


@pytest.mark.asyncio
async def test_withheld_answer_and_repair_are_recorded(lab, labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    run = VoiceRun(diagnostics, voice)
    await run.speak()
    run.recognise("create project called Nepal")
    run.accept("create project called Nepal")
    assert await run.answer("Sure!") is False  # Gemini skipped the tool
    await settle(voice)
    await run.turns.prepare()
    assert await run.answer("Created project Nepal.") is True
    await settle(voice)
    run.close()
    data, page = await report(diagnostics, labdir)
    (u,) = data["sessions"][0]["utterances"]
    assert [r["kind"] for r in u["responses"]] == [
        "response_withheld",
        "response_played",
    ]
    kinds = [p["kind"] for p in u["project"]]
    assert "repair_requested" in kinds and "delivered_to_model" in kinds
    assert [a["text"] for a in u["assistant"]] == ["Created project Nepal."]
    assert "withheld, played" in page


@pytest.mark.asyncio
async def test_everything_on_disk_is_sealed_and_retention_cleans_up(labdir):
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    run = VoiceRun(diagnostics)
    await run.speak()
    run.recognise("my secret phrase is blue whale")
    run.accept("my secret phrase is blue whale")
    run.close()
    await diagnostics.aclose()
    files = list(diagnostics.run_dir.iterdir())
    assert files and all(f.name.endswith(".sealed") for f in files)
    for f in files:
        content = f.read_bytes()
        assert content.startswith(b"SEALED1")
        assert b"blue whale" not in content and b"RIFF" not in content
    report_path = vd.write_report(labdir, FakeProtector())
    assert "blue whale" in report_path.read_text(encoding="utf-8")
    runs = labdir / "voice-diagnostics" / "runs"
    for i in range(7):  # older runs
        old = runs / f"20200101T00000{i}Z-old{i}"
        old.mkdir()
        os.utime(old, (time.time() - 30 * 86400,) * 2)
    removed = vd.prune(labdir / "voice-diagnostics", retention_days=7, keep_runs=5)
    assert len(removed) == 7 and diagnostics.run_dir.exists()
    assert not report_path.exists()  # plaintext report never outlives a lab start
    assert vd.cleanup(labdir) is True and not (labdir / "voice-diagnostics").exists()
    assert vd.cleanup(labdir) is False


@pytest.mark.asyncio
async def test_audio_is_bounded_per_utterance_and_per_run(labdir):
    diagnostics = vd.VoiceDiagnostics(
        labdir,
        protector=FakeProtector(),
        max_utterance_seconds=0.05,
        max_run_audio_bytes=2_000,
        group_gap_seconds=0.0,  # two separate utterances
    )
    run = VoiceRun(diagnostics)
    await run.speak(frames=20)  # 0.2 s > 0.05 s limit
    await run.speak(frames=20)  # run byte limit reached
    run.close()
    data, _ = await report(diagnostics, labdir)
    first, second = data["sessions"][0]["utterances"]
    assert first["audio_truncated"] and first["audio"]["seconds"] <= 0.07
    assert "audio_not_kept_run_limit" in second["flags"] and second["audio"] is None


def test_diagnostics_are_off_unless_explicitly_requested():
    import jarvis.voice.production_runtime as production
    import jarvis.voice.project_voice_lab as voice_lab
    from jarvis.voice.runtime import VoiceRuntimeController

    for entry in (production.main, production._run_from_configuration):
        source = inspect.getsource(entry)
        for name in ("voice_diagnostics", "VoiceDiagnostics", "record_diagnostics"):
            assert name not in source
        assert "session_audio_tap" not in source
    assert "voice_diagnostics" not in inspect.getsource(production)
    for function in (
        production.build_production_voice_runtime,
        VoiceRuntimeController.__init__,
    ):
        assert (
            inspect.signature(function).parameters["session_audio_tap"].default is None
        )
    assert (
        inspect.signature(voice_lab.run_voice_lab).parameters["diagnostics"].default
        is None
    )
    assert "--record-diagnostics" in inspect.getsource(voice_lab.main)
    assert (
        inspect.signature(VoiceProjectMemory.__init__).parameters["diagnostics"].default
        is None
    )


@pytest.mark.asyncio
async def test_lab_passes_the_audio_tap_only_with_diagnostics(tmp_path, labdir):
    from jarvis.voice.project_voice_lab import run_voice_lab

    seen = []

    class Runtime:
        async def run(self):
            return None

    def builder(config, **kwargs):
        seen.append(sorted(kwargs))
        return Runtime()

    await run_voice_lab(object(), tmp_path, baseline=False, runtime_builder=builder)
    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    await run_voice_lab(
        object(),
        tmp_path,
        baseline=True,
        runtime_builder=builder,
        diagnostics=diagnostics,
    )
    assert "session_audio_tap" not in seen[0]
    assert "session_audio_tap" in seen[1] and "project_memory_factory" not in seen[1]
    assert diagnostics._closed


@pytest.mark.asyncio
async def test_saved_text_is_read_back_from_storage_not_assumed(lab, labdir):
    from dataclasses import replace

    diagnostics = vd.VoiceDiagnostics(labdir, protector=FakeProtector())
    voice = await voice_memory(lab, diagnostics)
    real_snapshot = voice.access.snapshot

    async def snapshot(selection, **kwargs):
        result = await real_snapshot(selection, **kwargs)
        if kwargs.get("source_ids"):
            # What the store returns, not what Jarvis believes it saved.
            altered = tuple(
                replace(s, event=replace(s.event, text=s.event.text + " [stored]"))
                for s in result.sources
            )
            return replace(result, sources=altered)
        return result

    voice.access.snapshot = snapshot
    run = VoiceRun(diagnostics, voice)
    await run.say("create project called Nepal")
    run.close()
    data, page = await report(diagnostics, labdir)
    (u,) = data["sessions"][0]["utterances"]
    prepared = next(p for p in u["project"] if p["kind"] == "prepared")
    assert prepared["saved_text"] == "create project called Nepal [stored]"
    assert "SAVED_TEXT_DIFFERS" in page
