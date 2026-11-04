"""Replies Gemini transcribed but never voiced (live lab at c55898fb).

"Remember that my car is a Suzuki Jimny." -> remember_memory committed once and
the turn was saved, Gemini's tool follow-up "Understood, I've noted that." was
committed as transcript, but no PCM ever reached the speaker (output_audio=0,
no playback-started event, no gate withhold). Silent-audio recovery only knew
completed near-silent segments and gave up ("could not correlate"), so the
session timed out in silence.

Now: a committed, uninterrupted assistant turn with no playback segment at all
is replayed once through scripted TTS, only if the project response gate
approves it, and is then saved once. Gemini is never asked again, so no tool
runs twice and nothing is spoken twice.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake, nepal

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.voice import silent_audio_recovery as recovery_module
from jarvis.voice.media_devices_audio import PlaybackQualitySnapshot
from jarvis.voice.silent_audio_recovery import SilentRealtimeAudioRecovery

lab = project_voice_tests.lab  # shared real-archive fixture

REPLY = "Understood, I've noted that."


class Output:
    """The physical output: counts playback segments that started."""

    def __init__(self):
        self.started_segment_sequence = 0
        self.last_completed_quality = None

    def play(self, *, rms=-20.0, peak=12000):
        self.started_segment_sequence += 1
        self.last_completed_quality = PlaybackQualitySnapshot(
            sequence=self.started_segment_sequence,
            duration_seconds=1.0,
            peak_abs=peak,
            rms_dbfs=rms,
            interrupted=False,
        )


class Speech:
    def __init__(self, output, *, fail=False):
        self.output, self.fail, self.spoken = output, fail, []

    async def speak(self, output, text):
        if self.fail:
            raise RuntimeError("tts unavailable")
        self.spoken.append(text)
        self.output.play()

    async def aclose(self):
        pass


def recovery(output, speech, **policy):
    r = SilentRealtimeAudioRecovery(
        JarvisConfig(), output_getter=lambda: output, speech_factory=lambda _: speech
    )
    if policy:
        r.bind_unplayed_turn_policy(**policy)
    return r


def assistant(text=REPLY, *, interrupted=False):
    return ConversationTurn(ConversationRole.ASSISTANT, text, interrupted=interrupted)


async def finish(r):
    while r._tasks:
        await asyncio.gather(*tuple(r._tasks))


@pytest.fixture(autouse=True)
def short_grace(monkeypatch):
    monkeypatch.setattr(recovery_module, "_NO_AUDIO_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(recovery_module, "_QUALITY_WAIT_SECONDS", 0.2)


# -- silent-audio recovery ----------------------------------------------------


@pytest.mark.asyncio
async def test_text_only_reply_is_replayed_once_when_the_gate_allows():
    output = Output()
    speech = Speech(output)
    replayed = []
    r = recovery(output, speech, allow=lambda t: True, replayed=replayed.append)
    turn = assistant()
    r.observe_turn(turn)
    await finish(r)
    assert speech.spoken == [REPLY] and replayed == [turn]
    # The replay's own segment is not mistaken for the next turn's audio.
    nxt = assistant("Anything else?")
    r.observe_turn(nxt)
    await finish(r)
    assert speech.spoken == [REPLY, "Anything else?"]


@pytest.mark.asyncio
async def test_a_reply_the_gate_withheld_is_never_replayed():
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: False, replayed=pytest.fail)
    r.observe_turn(assistant())
    await finish(r)
    assert speech.spoken == []


@pytest.mark.asyncio
async def test_a_played_reply_is_not_replayed():
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: True, replayed=pytest.fail)
    output.play()  # Gemini's audio played normally
    r.observe_turn(assistant())
    await finish(r)
    assert speech.spoken == []


@pytest.mark.asyncio
async def test_an_interrupted_reply_is_not_replayed():
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: True, replayed=pytest.fail)
    r.observe_turn(assistant(interrupted=True))
    await finish(r)
    assert speech.spoken == []


@pytest.mark.asyncio
async def test_failed_tts_uses_the_single_fallback():
    output = Output()
    spoken = []
    r = recovery(
        output,
        Speech(output, fail=True),
        allow=lambda t: True,
        replayed=lambda t: None,
        fallback=spoken.append,
    )
    r.observe_turn(assistant())
    await finish(r)
    assert spoken == [REPLY]


@pytest.mark.asyncio
async def test_without_project_memory_recovery_is_unchanged():
    """Flag off: nothing binds the policy and no-playback turns are left alone,
    exactly as before (only near-silent completed audio is replayed)."""
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech)
    r.observe_turn(assistant())
    await finish(r)
    assert speech.spoken == []
    output.play(rms=-70.0, peak=50)  # near-silent PCM: the existing recovery
    r.observe_turn(assistant("Yes?"))
    await finish(r)
    assert speech.spoken == ["Yes?"]


# -- the project gate's decision and recording ----------------------------------


def remember_ran(wake):
    wake.turns.observe_tools_executed(
        SimpleNamespace(
            function_calls=[SimpleNamespace(name="remember_memory")],
            function_call_outputs=[SimpleNamespace(is_error=False)],
        )
    )


@pytest.mark.asyncio
async def test_tool_follow_up_without_audio_is_replayed_and_saved_once(lab):
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    output = Output()
    speech = Speech(output)
    r = recovery(
        output,
        speech,
        allow=wake.turns.allow_unplayed_reply,
        replayed=wake.turns.observe_replayed,
        fallback=wake.turns.speak_text,
    )
    said = "Remember that my car is a Suzuki Jimny."
    wake.speech()
    wake.partial(said)
    wake.transcript(said)  # finalised at the remember_memory call
    remember_ran(wake)
    await settle(voice)
    # Gemini's follow-up is committed as transcript; no frame reached the gate.
    turn = wake.reply(REPLY)
    r.observe_turn(turn)
    await finish(r)
    await settle(voice)
    assert speech.spoken == [REPLY]  # one audible acknowledgement
    assert wake.session.replies == []  # Gemini was not asked again
    assert lab.rows() == [
        ("user", said, "complete", "General"),
        ("assistant", REPLY, "complete", "General"),
    ]
    assert voice.metrics.unplayed_replays == 1
    wake.turns.observe_replayed(turn)  # a duplicate callback saves nothing more
    await settle(voice)
    assert len(lab.rows()) == 2


@pytest.mark.asyncio
async def test_unvoiced_reply_to_a_withheld_utterance_is_not_replayed(lab):
    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called garage", "Created.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial("What did we decide about Nepal?")
    assert (await wake.gate())[0] is False  # withheld by the context gate
    turn = wake.reply("We decided nothing.")
    assert wake.turns.allow_unplayed_reply(turn) is False
    wake.close()


@pytest.mark.asyncio
async def test_a_stale_reply_after_new_speech_is_not_replayed(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    await wake.fast("Which vehicle?", "The Jimny.")
    turn = wake.reply("An unvoiced extra reply.")
    wake.speech()  # the owner already speaks again
    wake.transcript("And the permits?")
    assert wake.turns.allow_unplayed_reply(turn) is False


@pytest.mark.asyncio
async def test_unplayed_reply_is_not_attributed_to_an_earlier_utterance(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    await wake.fast("Which vehicle?", "The Jimny.")
    wake.speech()
    wake.transcript("Remember that the permits are sorted.")
    await settle(voice)
    # No audio, no gate decision for this utterance: the earlier fast epoch must
    # not claim the reply.
    wake.reply("Noted, unvoiced.")
    await settle(voice)
    assert ("assistant", "Noted, unvoiced.", "complete", "Nepal trip") not in lab.rows()
