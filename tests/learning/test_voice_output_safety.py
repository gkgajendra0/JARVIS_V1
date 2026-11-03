"""Internal Gemini text must never be spoken (live qualification at 8155df0d).

During the first wake after a Windows Hello renewal, the wake acknowledgement's
generation came back as a TEXT-ONLY transcript: an echo of Jarvis's own prompt
plus a "Thinking Process" reasoning trace (below, verbatim from the lab log).
Silent-audio recovery treated it as an unvoiced reply and replayed it through
scripted TTS ("replay=scripted_tts"). Earlier the same day another wake
acknowledgement was transcribed as "Do not offer help or ask a question."

Two independent protections, both tested here:

1. Ownership/lifecycle: only a reply to an accepted owner utterance of the
   current activity, not yet answered audibly, may ever be replayed. A wake
   acknowledgement (epoch 0, a system generation) never is.
2. Content boundary (``voice_output_safety``): prompt echoes, internal markers
   and reasoning-trace structure are never replayed or saved as conversation,
   even if ownership were wrong.
"""

import asyncio

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import settle
from test_project_voice_fast_path import FastWake
from test_project_voice_unvoiced_reply import (
    Output,
    Speech,
    assistant,
    finish,
    recovery,
)

import jarvis.voice.agent  # registers Jarvis's prompt text
import jarvis.voice.runtime  # noqa: F401 - registers the wake-ack instructions
from jarvis.voice import silent_audio_recovery as recovery_module
from jarvis.voice.voice_output_safety import is_user_facing, non_user_facing_reason

lab = project_voice_tests.lab

# Verbatim assistant transcript, lab log 2026-11-03T10:16:12Z (turn e0f0078b).
LIVE_TRACE = (
    "Neither claim that a greeting is required nor describe its purpose.\n\n"
    "Thinking Process:\n\n"
    "1.  **Analyze the context:** The user's prompt is a \"[Project memory from "
    'Jarvis, not speech from the owner. Do not reply to this message.]" block. '
    "The user hasn't spoken anything new *after* the provided history. Wait, the "
    "prompt implies the actual user input isn't present in this specific "
    "interaction block other than the history. Oh, let me re-read the "
    'environment instructions. "A standalone wake-name utterance is activation '
    "residue... When the audio contains only your wake name, remain silent and "
    "wait for the owner's actual request\".\n"
    "2.  **Evaluate for action:** There is no new user request. The user is just "
    "providing project memory.\n"
    "3.  **Determine response:** I should remain silent as there is no request to "
    'respond to. Wait, the system instructions say "A standalone wake-name '
    "utterance is activation residue... When the audio contains only your wake "
    "name, remain silent and wait for the owner's actual request\". Since the "
    "user input provided is merely the system-provided project memory and no "
    "actual user speech, I do not output anything until the user actually "
    "addresses me.\n\n"
    "Wait, if I am forced to output *something* because the prompt requires a "
    "response, or if I should just output nothing. Let's just output nothing or "
    'remain silent. The developer instructions say "remain silent and wait for '
    "the owner's actual request\"."
)
# Verbatim, lab log 2026-11-03T09:55:23Z (turn 3c9d13e7): a prompt paraphrase.
LIVE_ECHO = "Do not offer help or ask a question."

LEGITIMATE = (
    "The Jimny.",
    "Added a stove to the packing list.",
    "Your hotel in Kathmandu is Yak and Yeti.",
    "It's 22 degrees Celsius in Kathmandu right now.",
    "Haan, stove packing list mein add kar diya.",
    "Don't worry, it's saved.",
    "Yes?",
    "1. Passport. 2. Permits. 3. The stove.",
    "Notepad is open.",
    "I removed that, and it's gone from our saved conversation too.",
)


@pytest.fixture(autouse=True)
def short_grace(monkeypatch):
    monkeypatch.setattr(recovery_module, "_NO_AUDIO_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(recovery_module, "_QUALITY_WAIT_SECONDS", 0.2)


# -- the content boundary -------------------------------------------------------


def test_the_live_reasoning_trace_is_not_user_facing():
    assert non_user_facing_reason(LIVE_TRACE) is not None


def test_each_layer_catches_the_trace_on_its_own():
    """Not a single phrase match: with the label and markers removed, the
    step structure still identifies it; with that removed too, the prompt echo
    does."""
    no_label = LIVE_TRACE.replace("Thinking Process:", "")
    assert non_user_facing_reason(no_label) is not None
    no_markers = no_label.replace(
        "[Project memory from Jarvis, not speech from the owner. Do not reply to "
        "this message.]",
        "memory",
    )
    assert non_user_facing_reason(no_markers) == "reasoning_trace"
    first_step = no_markers.split("2.  **")[0].split("1.  **Analyze the context:** ")[1]
    plain = first_step.replace("*", "")
    assert non_user_facing_reason(plain) == "instruction_echo"


def test_a_paraphrase_of_jarvis_prompt_is_not_user_facing():
    assert non_user_facing_reason(LIVE_ECHO) == "instruction_echo"


@pytest.mark.parametrize("text", LEGITIMATE)
def test_ordinary_replies_are_user_facing(text):
    assert is_user_facing(text), non_user_facing_reason(text)


# -- silent-audio recovery ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [LIVE_TRACE, LIVE_ECHO])
async def test_recovery_never_speaks_internal_text_even_if_the_gate_allows(text):
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: True, replayed=pytest.fail)
    r.observe_turn(assistant(text))
    await finish(r)
    assert speech.spoken == []


@pytest.mark.asyncio
async def test_near_silent_recovery_never_speaks_internal_text():
    """Project memory off (production): the existing near-silent replay path."""
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech)
    output.play(rms=-70.0, peak=21)  # the live segment: pcm_peak=21
    r.observe_turn(assistant(LIVE_TRACE))
    await finish(r)
    assert speech.spoken == []
    output.play(rms=-70.0, peak=21)
    r.observe_turn(assistant("Yes?"))  # a genuine reply is still recovered
    await finish(r)
    assert speech.spoken == ["Yes?"]


# -- ownership in the project gate ------------------------------------------------


@pytest.mark.asyncio
async def test_a_wake_acknowledgement_transcript_is_never_replayed(lab):
    """Epoch 0: no owner speech yet, so the turn answers nobody. Even an
    innocent-looking acknowledgement text is not replayed by recovery."""
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    for text in (LIVE_TRACE, LIVE_ECHO, "Yes?"):
        turn = wake.reply(text)
        assert wake.turns.allow_unplayed_reply(turn) is False
    await settle(voice)
    assert lab.rows() == []  # and nothing was saved as conversation


@pytest.mark.asyncio
async def test_internal_text_after_owner_speech_is_neither_replayed_nor_saved(lab):
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    said = "create project called Nepal trip"
    wake.speech()
    wake.transcript(said)
    assert (await wake.turns.prepare())["status"] == "ready"
    turn = wake.reply(LIVE_TRACE)
    assert wake.turns.allow_unplayed_reply(turn) is False
    await settle(voice)
    assert [r[0] for r in lab.rows()] == ["user"]  # only the owner's words


@pytest.mark.asyncio
async def test_an_utterance_answered_audibly_is_never_replayed_again(lab):
    voice = await lab.runtime()
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("create project called Nepal trip")
    assert (await wake.turns.prepare())["status"] == "ready"
    assert wake.response()[0] is True  # Gemini's audio played
    turn = wake.reply("Created project Nepal trip.")
    assert wake.turns.allow_unplayed_reply(turn) is False  # no duplicate speech
    await asyncio.sleep(0)


def test_instruction_text_is_stripped_from_a_transcript_verbatim_only():
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS
    from jarvis.voice.voice_output_safety import strip_internal_text

    assert (
        strip_internal_text(_WAKE_ACK_INSTRUCTIONS + "Standing by.") == "Standing by."
    )
    spaced = _WAKE_ACK_INSTRUCTIONS.replace(". ", ".\n  ") + "  Standing by."
    assert strip_internal_text(spaced) == "Standing by."
    assert strip_internal_text(_WAKE_ACK_INSTRUCTIONS) == ""
    for text in LEGITIMATE:
        assert strip_internal_text(text) == text
