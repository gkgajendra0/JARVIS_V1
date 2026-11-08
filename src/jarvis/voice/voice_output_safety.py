"""Defensive boundary: text that is not a user-facing reply is never spoken
again or saved as conversation.

Gemini Live can return a transcript that is not an answer to the owner, for
example an echo of Jarvis's own generate_reply instructions or a reasoning
trace ("Thinking Process: 1. Analyze the context ..."), with no audio. Live
qualification at 8155df0d replayed exactly such a transcript through scripted
TTS. Ownership and lifecycle checks are the primary protection (see
``VoiceProjectTurns.allow_unplayed_reply`` and the runtime's wake
acknowledgement handling); this module is the second, content-level line.

It is deliberately structural, not a single phrase match:

* echo of any registered internal instruction text (word-shingle overlap:
  mostly made of prompt text, or quoting a dozen consecutive prompt words);
* internal control markers (tool names, project-memory framing);
* reasoning-trace structure (a labelled reasoning section, or several
  numbered/bold analysis steps);
* length beyond any spoken reply.
"""

from __future__ import annotations

import logging
import re
import threading

_MAX_SPOKEN_CHARS = 900
_SHINGLE = 5
_ECHO_OVERLAP = 0.4
# At least six consecutive words shared: an ordinary short reply that happens
# to contain one common five-word phrase of a prompt is not an echo.
_ECHO_MIN_SHARED = 2
# A dozen consecutive words of a prompt quoted anywhere, however long the text.
_ECHO_QUOTED = 8

_INTERNAL_MARKERS = (
    "[project memory",
    "not speech from the owner",
    "do not reply to this message",
    "prepare_project_turn",
    "search_project_history",
    "forget_saved_history",
    "system prompt",
    "developer message",
)
_REASONING_LABEL = re.compile(
    r"(?im)(?:^|(?<=[.!?]) )\s*(?:\*\*)?\s*(?:thinking(?: process)?|reasoning|analysis|"
    r"chain[- ]of[- ]thought|internal (?:notes?|monologue)|self[- ]correction)"
    r"\s*(?:\*\*)?\s*:"
)
_ANALYSIS_STEP = re.compile(r"(?m)^\s*(?:\d+\.|[-*])\s+\*\*[^*\n]{2,60}\*\*")
# Narration ABOUT the conversation rather than speech TO the owner: the model
# reasoning in prose ("The user hasn't spoken ... I should remain silent ...
# the system instructions say ..."). Two different kinds of cue are required.
_META_CUES = (
    re.compile(r"\bthe (?:user|owner)(?:'s)?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:I|we) (?:should|must|need to|will|have to|am (?:forced|supposed) to)"
        r"(?: just)? (?:respond|reply|answer|acknowledge|output|remain|stay|say|"
        r"wait|not (?:respond|reply|output|say))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the prompt|system instructions?|developer instructions?|the "
        r"instructions? (?:say|says|said|is|are)|wake[- ](?:word|name)|activation "
        r"residue|generate_reply|tool call)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:let me re-?read|wait, (?:if|the|let)|let's just output|output "
        r"nothing|remain silent)\b",
        re.IGNORECASE,
    ),
)

_lock = threading.Lock()
_registered: dict[str, frozenset[tuple[str, ...]]] = {}


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", (text or "").casefold())


def _shingles(words: list[str]) -> frozenset[tuple[str, ...]]:
    if len(words) < _SHINGLE:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(
        tuple(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)
    )


# Modules whose prompt/instruction text is registered at import. Loaded on the
# first check, so a standalone user (the qualification grader) sees the same
# registry as the running voice runtime.
_SOURCES = ("jarvis.voice.agent", "jarvis.voice.runtime", "jarvis.voice.project_voice")
_sources_loaded = False


def _load_sources() -> None:
    global _sources_loaded
    if _sources_loaded:
        return
    _sources_loaded = True
    import importlib

    for name in _SOURCES:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a missing optional module registers nothing
            logging.getLogger(__name__).debug("Prompt source %s unavailable", name)


def _normalized(text: str) -> str:
    return " ".join((text or "").split())


# Every instruction text Jarvis itself sends with generate_reply (including
# formatted ones, e.g. "Say only this, exactly: '...'"). Used ONLY to strip an
# echo of the instruction from the start of its own generation's transcript,
# never to classify: such an instruction legitimately contains the words that
# are then spoken.
_RECENT_INSTRUCTIONS = 64
_sent: dict[str, tuple[str, ...]] = {}
# An echo shorter than this is not removed (an ordinary reply may share a few
# leading words with an instruction); shorter instructions must match whole.
_PREFIX_MIN_WORDS = 8


def note_generation_instructions(text: str) -> None:
    """Record instructions Jarvis is about to send to the realtime model."""
    words = tuple(_words(text))
    if not words:
        return
    with _lock:
        _sent.pop(text, None)
        _sent[text] = words
        while len(_sent) > _RECENT_INSTRUCTIONS:
            _sent.pop(next(iter(_sent)))


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (m.group(0).casefold(), m.start(), m.end())
        for m in re.finditer(r"[^\W_]+", text or "")
    ]


# A whole sentence in which the model tells itself to produce the reply
# ("So I just need to output the answer.", "I should respond briefly.") rather
# than speaking to the owner. Live run 2026-11-08 07:19:20 (repair path):
# "So I just need to output the answer.You are staying at the Yak and Yeti."
# Only a sentence made of nothing else matches: "I'll say it again: the hotel is
# ..." or "I need to check the permits" keep their content.
_NARRATION_SENTENCE = re.compile(
    r"(?i)(?:^|(?<=[.!?]))[ \t]*"
    r"(?:(?:so|okay|ok|alright|all right|right|now|well|then|fine)[,\s]+)*"
    r"(?:I|we)(?:'ll|'m going to|'d|\s+will|\s+am going to|\s+shall)?"
    r"(?:\s+(?:just|simply|only|now|then|directly|briefly|basically))*"
    r"(?:\s+(?:(?:need|have|want|ought|am going|are going|got)\s+to|should|must|"
    r"can|will|shall|'ll))?"
    r"(?:\s+(?:just|simply|only|now|then|directly|briefly|basically))*"
    r"\s+(?:output|give|provide|state|deliver|produce|respond|reply|answer|"
    r"return)"
    r"(?:\s+(?:with|to|that|this|it|the|an?|my|our|their|his|her|owner'?s?|user'?s?|"
    r"final|direct|short|brief|actual|requested|correct|concise|just|only))*"
    r"(?:\s+(?:answer|response|reply|result|information|fact|facts|details?|"
    r"question|request|it|that|this|them|now|then|briefly|directly|only))?"
    r"[ \t]*[.!?]+"
)


# A whole sentence that is a style instruction to the model, not speech to the
# owner. Live run 2026-11-08 17:34:10 (repair path): "Never say 'Based on your
# recent request', 'According to project memory' or equivalent phrasing. Keep to
# one or two sentences.I don't have information about which hotel ..." The
# sentence is not Jarvis prompt text (so echo removal could not match it): an
# imperative opening plus wording about phrasing, sentence count or "the
# user/owner" marks it. "Don't worry, it's safe." has neither cue and is kept.
_DIRECTIVE_SENTENCE = re.compile(
    r"(?i)(?:^|(?<=[.!?]))[ \t]*"
    r"(?:never|always|do not|don't|avoid|keep|use|respond|reply|answer|speak|"
    r"be|only|refer)\b"
    r"[^.!?]{0,240}?"
    r"(?:\bphrasing\b|\bwording\b|\bpreamble\b|"
    r"\b(?:one|two|three|a few|short|full|complete)(?: or (?:one|two|three))?"
    r" sentences?\b|\bthe (?:user|owner)\b)"
    r"[^.!?]*[.!?]+"
)


def strip_self_narration(text: str) -> str:
    """``text`` without sentences in which the model narrates producing its
    reply or states a style instruction to itself. Nothing else is rewritten."""
    original = text or ""
    cleaned = _NARRATION_SENTENCE.sub(" ", original)
    cleaned = _DIRECTIVE_SENTENCE.sub(" ", cleaned)
    if cleaned == original:
        return original
    return _tidy(cleaned)


def strip_internal_text(text: str) -> str:
    """``text`` without echoes of Jarvis's own instructions or the model's
    narration of producing the reply (:func:`strip_self_narration`)."""
    return strip_self_narration(_strip_instruction_echoes(text))


def _strip_instruction_echoes(text: str) -> str:
    """``text`` without echoes of Jarvis's own instructions.

    Gemini's output transcription can begin with the generate_reply
    instructions it was given (LiveKit sends them as MODEL-role text, and Gemini
    continues that turn), followed by what was actually spoken, e.g.
    "<wake-ack instructions>Standing by." (live qualification at 1b13dfb8, 1.17 s
    of audio). Removed: any run of words that reproduces an instruction FROM ITS
    START (at least eight words, or the whole of a shorter one), wherever it
    begins, ignoring case, spacing and punctuation. Nothing else is rewritten;
    paraphrases are left for :func:`internal_text_reason`.
    """
    _load_sources()
    original = text or ""
    with _lock:
        candidates = {tuple(_words(t)) for t in _registered} | set(_sent.values())
    candidates = sorted((c for c in candidates if c), key=len, reverse=True)
    for _ in range(4):  # an instruction may be echoed more than once
        spans = _word_spans(original)
        words = [w for w, _, _ in spans]
        cut = None
        for instruction in candidates:
            need = min(_PREFIX_MIN_WORDS, len(instruction))
            first = instruction[0]
            for start, word in enumerate(words):
                if word != first:
                    continue
                k = 0
                while (
                    start + k < len(words)
                    and k < len(instruction)
                    and words[start + k] == instruction[k]
                ):
                    k += 1
                if k >= need:
                    cut = (spans[start][1], spans[start + k - 1][2])
                    break
            if cut is not None:
                break
        if cut is None:
            break
        original = original[: cut[0]] + " " + original[cut[1] :]
    return _tidy(original)


def _tidy(text: str) -> str:
    """Spacing tidied (line breaks kept: they carry reasoning structure), and
    punctuation orphaned by a removal dropped."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in (text or "").split("\n")]
    tidy = "\n".join(lines).strip()
    tidy = re.sub(r"(?m)(?<=\S) +[.,;:]+(?= |$)", "", tidy)
    return tidy.lstrip(" .,;:!?-—–\n")


def register_internal_text(*texts: str) -> None:
    """Instruction/prompt text that must never be spoken back to the owner."""
    with _lock:
        for text in texts:
            if text and len(_words(text)) >= _SHINGLE:
                _registered[text] = _shingles(_words(text))


def non_user_facing_reason(text: str) -> str | None:
    """Why ``text`` must not be replayed or saved as a reply, else None."""
    _load_sources()
    stripped = (text or "").strip()
    if not stripped:
        return "empty"
    folded = stripped.casefold()
    for marker in _INTERNAL_MARKERS:
        if marker in folded:
            return "internal_marker"
    if _REASONING_LABEL.search(stripped) or len(_ANALYSIS_STEP.findall(stripped)) >= 2:
        return "reasoning_trace"
    if sum(1 for cue in _META_CUES if cue.search(stripped)) >= 2:
        return "meta_narration"
    words = _words(stripped)
    reply = _shingles(words)
    if reply:
        with _lock:
            registered = tuple(_registered.values())
        for instruction in registered:
            shared = len(reply & instruction)
            # Overlap relative to the shorter text: a reply that repeats a
            # large part of an instruction, or is mostly made of one.
            if shared >= _ECHO_QUOTED or (
                shared >= _ECHO_MIN_SHARED
                and shared / min(len(reply), len(instruction)) >= _ECHO_OVERLAP
            ):
                return "instruction_echo"
    if len(stripped) > _MAX_SPOKEN_CHARS:
        return "too_long_for_a_spoken_reply"
    return None


def is_user_facing(text: str) -> bool:
    return non_user_facing_reason(text) is None


# Content that is internal by what it SAYS (not merely long or empty).
_INTERNAL_REASONS = frozenset(
    {"internal_marker", "reasoning_trace", "meta_narration", "instruction_echo"}
)


def internal_text_reason(text: str) -> str | None:
    """Why ``text`` (already stripped of instruction echoes) is internal text
    that must never be shown, saved or spoken as a reply; None for an ordinary
    reply of any length."""
    reason = non_user_facing_reason(text)
    return reason if reason in _INTERNAL_REASONS else None


def sanitize_assistant_transcript(text: str) -> tuple[str, str | None]:
    """(user-facing text, why something was removed or rejected).

    Instruction echoes are removed; if what remains is still internal text the
    whole transcript is rejected (returns ""), since it is not what Jarvis
    should have said to the owner.
    """
    unechoed = _strip_instruction_echoes(text)
    spoken = strip_self_narration(unechoed)
    labels = []
    if _normalized(unechoed) != _normalized(text):
        labels.append("instruction_echo_removed")
    if _normalized(spoken) != _normalized(unechoed):
        labels.append("self_narration_removed")
    removed = "+".join(labels) or None
    if not spoken:
        return "", removed or "empty"
    reason = internal_text_reason(spoken)
    if reason is not None:
        return "", reason
    return spoken, removed


class SpokenTextGuard:
    """Watches a generation's transcription as it streams (with its audio).

    ``feed`` returns a reason ONCE when the text, after removing instruction
    echoes, turns out to be internal (reasoning, prompt echo, internal
    markers): the caller then stops that speech so the rest is never played.
    A partial instruction echo still streaming (under eight words) is not
    judged yet.
    """

    def __init__(self) -> None:
        self.text = ""
        self.reason: str | None = None

    def feed(self, delta: str) -> str | None:
        if self.reason is not None:
            return None
        self.text += str(delta)
        unechoed = _strip_instruction_echoes(self.text)
        if _DIRECTIVE_SENTENCE.match(unechoed.lstrip()):
            # A style instruction to the model is being SPOKEN (live
            # 2026-11-08 17:34:10, about 11 s of audio): stop it now. The
            # answer that may follow is lost with it; the owner can ask again.
            self.reason = "style_instruction"
            return self.reason
        spoken = strip_self_narration(unechoed)
        if len(_words(spoken)) < _PREFIX_MIN_WORDS and not _REASONING_LABEL.search(
            spoken
        ):
            return None
        self.reason = internal_text_reason(spoken)
        return self.reason
