"""The model narrating its own reply never reaches saved history or scripted TTS.

Live run 2026-11-08 07:19:20 (R2-B, repair path): Gemini's transcript was
"So I just need to output the answer.You are staying at the Yak and Yeti."
The instruction-echo filter removed the echo but kept the narration, and it was
saved with Jarvis's reply in Interview Prep history. Playback lasted 2.05 s,
about the length of the answer alone.

Paths covered:
- saved transcript: ``sanitize_assistant_transcript`` (what the LiveKit bridge
  accepts as Jarvis's turn; the bridge itself is tested in
  ``tests/test_livekit_reply_cleanup.py``);
- scripted TTS: silent-audio recovery replays only the cleaned reply;
- Gemini's own audio: the streaming guard does NOT cut the speech for a
  narration sentence (that would cut the answer that follows), but still stops
  a real reasoning trace. Words already spoken by Gemini cannot be unsaid.
"""

import pytest
from test_project_voice_unvoiced_reply import (
    Output,
    Speech,
    assistant,
    finish,
    recovery,
)
from test_voice_output_safety import LIVE_TRACE, _chunked, _transcribe

import jarvis.voice.agent  # noqa: F401 - registers Jarvis's prompt text
from jarvis.voice.project_voice import REPAIR_ANSWER_INSTRUCTIONS
from jarvis.voice.voice_output_safety import (
    SpokenTextGuard,
    note_generation_instructions,
    sanitize_assistant_transcript,
    strip_self_narration,
)

LIVE = "So I just need to output the answer.You are staying at the Yak and Yeti."
ANSWER = "You are staying at the Yak and Yeti."

NARRATED = [
    (LIVE, ANSWER),
    ("So I just need to output the answer. " + ANSWER, ANSWER),
    (
        "I should respond briefly. The panel is on Friday at ten.",
        "The panel is on Friday at ten.",
    ),
    ("Okay, I'll just give the answer. Friday at ten.", "Friday at ten."),
    (
        "Now I will simply provide the requested information. Your flight is at 9.",
        "Your flight is at 9.",
    ),
    (ANSWER + " I should just output that.", ANSWER),
    ("I need to answer directly. You chose the Thar.", "You chose the Thar."),
]

ORDINARY = [
    "I need to check the permits.",
    "I'll say it again: the hotel is Yak and Yeti.",
    "We should state the facts clearly in the email.",
    "I answer to you, sir.",
    "We will reply tomorrow.",
    "I will give you the list after lunch.",
    "So you need to output the file as a PDF.",
    "Main jawab de raha hoon: aapka hotel Yak and Yeti hai.",
    "Done. I removed it from our saved conversations and your personal memory.",
]


@pytest.mark.parametrize(("text", "answer"), NARRATED)
def test_saved_transcript_keeps_only_the_answer(text, answer):
    saved, reason = sanitize_assistant_transcript(text)
    assert saved == answer
    assert reason == "self_narration_removed"


def test_the_live_repair_transcript_with_its_instruction_echo():
    """The live turn also began with the repair instruction echo."""
    note_generation_instructions(REPAIR_ANSWER_INSTRUCTIONS)
    saved, reason = sanitize_assistant_transcript(REPAIR_ANSWER_INSTRUCTIONS + LIVE)
    assert saved == ANSWER
    assert reason == "instruction_echo_removed+self_narration_removed"


def test_narration_alone_is_never_saved():
    assert sanitize_assistant_transcript("So I just need to output the answer.") == (
        "",
        "self_narration_removed",
    )


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_replies_are_untouched(text):
    assert sanitize_assistant_transcript(text) == (text, None)
    assert strip_self_narration(text) == text


# -- what can reach audio ---------------------------------------------------------


@pytest.mark.asyncio
async def test_scripted_tts_replays_only_the_answer():
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: True)
    r.observe_turn(assistant(LIVE))
    await finish(r)
    assert speech.spoken == [ANSWER]


@pytest.mark.asyncio
async def test_scripted_tts_never_speaks_narration_alone():
    output = Output()
    speech = Speech(output)
    r = recovery(output, speech, allow=lambda t: True, replayed=pytest.fail)
    r.observe_turn(assistant("So I just need to output the answer."))
    await finish(r)
    assert speech.spoken == []


def _guard(chunks):
    guard = SpokenTextGuard()
    return [reason for chunk in chunks if (reason := guard.feed(chunk))]


def test_streaming_guard_lets_the_answer_after_a_narration_play():
    assert _guard(_chunked(LIVE)) == []
    assert _guard(_chunked("So I just need to output the answer.")) == []


def test_streaming_guard_still_stops_a_reasoning_trace_after_a_narration():
    assert _guard(_chunked("So I just need to output the answer. " + LIVE_TRACE))


@pytest.mark.asyncio
async def test_gemini_audio_is_not_cut_for_a_narration_sentence():
    interrupts, _ = await _transcribe(_chunked(LIVE))
    assert interrupts == 0
