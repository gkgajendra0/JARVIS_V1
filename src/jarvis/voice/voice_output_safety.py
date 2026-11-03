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
    r"(?im)^\s*(?:\*\*)?\s*(?:thinking(?: process)?|reasoning|analysis|"
    r"chain[- ]of[- ]thought|internal (?:notes?|monologue)|self[- ]correction)"
    r"\s*(?:\*\*)?\s*:"
)
_ANALYSIS_STEP = re.compile(r"(?m)^\s*(?:\d+\.|[-*])\s+\*\*[^*\n]{2,60}\*\*")

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


def strip_internal_text(text: str) -> str:
    """``text`` without any registered instruction quoted in it verbatim.

    Gemini's output transcription can begin with the generate_reply
    instructions it was given (LiveKit sends them as MODEL-role text), followed
    by what was actually spoken, e.g. "<wake-ack instructions>Standing by."
    (live qualification at 1b13dfb8, 1.17 s of audio). Only the spoken part is
    a reply. Whitespace differences are tolerated; nothing else is rewritten.
    """
    _load_sources()
    cleaned = _normalized(text)
    if not cleaned:
        return ""
    with _lock:
        registered = sorted(_registered, key=len, reverse=True)
    for instruction in registered:
        quoted = _normalized(instruction)
        if quoted and quoted in cleaned:
            cleaned = cleaned.replace(quoted, " ")
    return _normalized(cleaned)


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
