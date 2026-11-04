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
    assert non_user_facing_reason(plain) in {"instruction_echo", "meta_narration"}


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


# -- b418aa91 follow-up: every transcript path, and audio -----------------------
#
# The verbatim-only strip at b418aa91 missed echoes that differ in case or
# punctuation, partial echoes, echoes of formatted (dynamic) instructions, and
# reasoning in plain prose. And it only cleaned the saved transcript: the audio
# of a generation that turned into internal text kept playing.


def test_an_echo_differing_in_case_and_punctuation_is_removed():
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS
    from jarvis.voice.voice_output_safety import strip_internal_text

    echoed = _WAKE_ACK_INSTRUCTIONS.lower().replace(".", ",").replace(";", "")
    assert strip_internal_text(echoed + " Standing by.") == "Standing by."
    assert strip_internal_text("Yes? " + _WAKE_ACK_INSTRUCTIONS) == "Yes?"


def test_a_partial_echo_followed_by_reasoning_is_rejected_whole():
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS
    from jarvis.voice.voice_output_safety import sanitize_assistant_transcript

    first = " ".join(_WAKE_ACK_INSTRUCTIONS.split()[:12])
    text = (
        first + " The user has not given a request yet, so I should just "
        "acknowledge briefly. Wait, let me re-read the instructions."
    )
    assert sanitize_assistant_transcript(text) == ("", "meta_narration")
    assert sanitize_assistant_transcript(first + " Standing by.") == (
        "Standing by.",
        "instruction_echo_removed",
    )


def test_formatted_instructions_jarvis_sent_are_recognised_but_never_censor_the_reply():
    from jarvis.voice.voice_output_safety import (
        note_generation_instructions,
        strip_internal_text,
    )

    said = "Sorry, I couldn't load the project memory for that. Please say it again."
    instruction = "Say only this, briefly: '" + said + "' Do not answer the request."
    note_generation_instructions(instruction)
    assert strip_internal_text(instruction + said) == said  # echo, then speech
    assert strip_internal_text(said) == said  # the reply itself is untouched
    assert is_user_facing(said)


@pytest.mark.parametrize(
    "text",
    [
        "The user hasn't said anything new. I should remain silent and wait.",
        "Since the owner only said my wake word, I will just acknowledge.",
        "The instructions say to respond briefly, so the owner gets one sentence.",
        LIVE_TRACE.replace("Thinking Process:", "").replace("**", ""),
    ],
)
def test_reasoning_in_plain_prose_is_internal(text):
    from jarvis.voice.voice_output_safety import internal_text_reason

    assert internal_text_reason(text) is not None


def test_long_ordinary_replies_are_never_internal():
    from jarvis.voice.voice_output_safety import internal_text_reason

    report = (
        "Today in Kathmandu, expect mostly clear and sunny skies with a high near "
        "24 degrees Celsius and a low near 12. " * 12
    )
    assert len(report) > 900
    assert internal_text_reason(report) is None
    for text in LEGITIMATE:
        assert internal_text_reason(text) is None


class _Speech:
    def __init__(self):
        self.interrupts = 0

    def done(self):
        return False

    def interrupt(self, *, force=False):
        self.interrupts += 1


class _Agent:
    def __init__(self):
        from types import SimpleNamespace

        self.speech = _Speech()
        self.session = SimpleNamespace(current_speech=self.speech)


async def _stream(chunks):
    for chunk in chunks:
        yield chunk


async def _transcribe(chunks):
    from jarvis.voice.agent import guarded_transcription

    agent = _Agent()
    out = [c async for c in guarded_transcription(agent, _stream(chunks), None)]
    return agent.speech.interrupts, "".join(out)


def _chunked(text, size=3):
    words = text.split(" ")
    return [" ".join(words[i : i + size]) + " " for i in range(0, len(words), size)]


@pytest.mark.asyncio
async def test_speech_stops_as_soon_as_the_generation_turns_into_reasoning():
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS

    chunks = _chunked(_WAKE_ACK_INSTRUCTIONS) + _chunked(LIVE_TRACE)
    interrupts, forwarded = await _transcribe(chunks)
    assert interrupts == 1  # the rest of the audio is never played
    assert "Thinking Process" not in forwarded and "Analyze" not in forwarded


@pytest.mark.asyncio
async def test_an_instruction_echo_then_a_real_acknowledgement_plays():
    """The live 11:52:52Z shape: echo + "Standing by." (1.17 s of audio)."""
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS

    interrupts, _ = await _transcribe(
        _chunked(_WAKE_ACK_INSTRUCTIONS) + ["Standing by."]
    )
    assert interrupts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("text", list(LEGITIMATE) + ["Today in Kathmandu. " * 80])
async def test_ordinary_replies_stream_untouched(text):
    interrupts, forwarded = await _transcribe(_chunked(text))
    assert interrupts == 0 and forwarded.strip() == text.strip()
