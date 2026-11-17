"""Opt-in reply-lifecycle diagnostics for the realtime voice session.

Investigates the live voice stall (Zanskar 2026-11-16, Munnar 2026-11-17).
After a Jarvis-requested reply, answers kept playing but none was transcribed or
saved, and every turn hit LiveKit's "speech not done in time after
interruption". An offline reproduction showed that this happens exactly when
Gemini stops sending turn_complete: the Google plugin closes a generation's
message stream only on turn_complete, and LiveKit commits the reply only after
that.

Off by default. Enable with JARVIS_VOICE_REPLY_DIAGNOSTICS=1. Every line holds
an event name, reply and generation IDs and a timestamp. It never holds
conversation text, audio or memory contents.

reply      LiveKit speech-handle id (one per spoken reply)
generation Gemini generation id (GR_...), linked to its reply when known

Events:
  speech_created           a reply was scheduled
  generation_created       Gemini opened a generation (server- or Jarvis-requested)
  generation_linked        a generation was matched to its reply
  early_answer_held_back   Jarvis withheld an answer given before project context
  replacement_requested    Jarvis asked Gemini for a replacement answer
  correction_requested     Jarvis asked Gemini for a false-claim correction
  playback_started / playback_finished / playback_interrupted
  generation_complete / turn_complete / server_interrupted   Gemini signals
  input_speech_started     Gemini reported the owner speaking
  tool_call                Gemini asked for a tool (closes that generation)
  tool_output_sent         tool results were handed back for an automatic reply
  speech_done / speech_done_interrupted
  reply_uncommitted        a reply ended without a committed assistant message
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque

LOGGER = logging.getLogger("jarvis.voice.reply_diagnostics")
ENV = "JARVIS_VOICE_REPLY_DIAGNOSTICS"
_ACTIVE: ReplyDiagnostics | None = None


def enabled(environ=None) -> bool:
    value = (os.environ if environ is None else environ).get(ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def active() -> ReplyDiagnostics | None:
    return _ACTIVE


def note(event: str, handle=None) -> None:
    """Record a Jarvis-side event for a reply; a no-op when diagnostics are off."""
    trace = _ACTIVE
    if trace is not None:
        trace.event(event, reply=_speech_id(handle))


def _speech_id(handle) -> str | None:
    value = getattr(handle, "id", None)
    return value if isinstance(value, str) else None


class ReplyDiagnostics:
    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._t0 = clock()
        self._unlinked_speeches: deque[str] = deque(maxlen=8)
        self._unlinked_generations: deque[str] = deque(maxlen=8)
        self._reply_of: dict[str, str] = {}
        self._rt_sessions: set[int] = set()
        self._outputs: set[int] = set()
        self._session = None

    # --- logging -----------------------------------------------------------

    def event(self, name: str, *, reply=None, generation=None) -> None:
        if reply is None and generation is not None:
            reply = self._reply_of.get(generation)
        LOGGER.info(
            "Reply diagnostic | event=%s reply=%s generation=%s t_ms=%d",
            name,
            reply or "-",
            generation or "-",
            round((self._clock() - self._t0) * 1000),
        )

    # --- wiring ------------------------------------------------------------

    def attach(self, session) -> ReplyDiagnostics:
        """Attach to a LiveKit AgentSession. The realtime session and audio
        output are found lazily, so model handoffs and per-wake outputs are
        covered."""
        global _ACTIVE
        _ACTIVE = self
        self._session = session
        session.on("speech_created", self._on_speech_created)
        # The realtime session exists once the agent starts listening; the
        # first generation of a wake must not be missed.
        session.on("agent_state_changed", lambda _ev: self._refresh())
        session.on("user_state_changed", lambda _ev: self._refresh())
        session.on("conversation_item_added", lambda _ev: self._refresh())
        # Tool results are handed back to Gemini; with automatic tool replies
        # the spoken answer must then arrive as a new generation.
        session.on(
            "function_tools_executed",
            lambda _ev: self.event("tool_output_sent", reply=self._current()),
        )
        return self

    def _refresh(self) -> None:
        session = self._session
        if session is None:
            return
        try:
            rt = session.current_agent.realtime_llm_session
        except Exception:  # noqa: BLE001 - no agent or no realtime session yet
            rt = None
        if rt is not None:
            self.attach_realtime(rt)
        output = getattr(getattr(session, "output", None), "audio", None)
        if output is not None:
            self.attach_output(output)

    def attach_realtime(self, rt) -> None:
        if id(rt) in self._rt_sessions:
            return
        self._rt_sessions.add(id(rt))
        rt.on("generation_created", self._on_generation_created)
        rt.on("input_speech_started", lambda _ev: self.event("input_speech_started"))
        plugin = rt
        for _ in range(4):  # unwrap Jarvis's guarded session to the plugin
            if hasattr(plugin, "_handle_server_content"):
                break
            plugin = getattr(plugin, "inner", None)
            if plugin is None:
                return
        if hasattr(plugin, "_handle_server_content"):
            self._wrap_server_content(plugin)
        if hasattr(plugin, "_handle_tool_calls"):
            self._wrap_tool_calls(plugin)

    def _wrap_tool_calls(self, plugin) -> None:
        """Gemini asked for a tool. The plugin closes that generation here,
        without turn_complete; the answer must come in a later generation."""
        original = plugin._handle_tool_calls
        if getattr(original, "_jarvis_reply_diagnostics", False):
            return

        def traced(tool_call):
            generation = getattr(plugin, "_current_generation", None)
            gid = getattr(generation, "response_id", None)
            self.event("tool_call", generation=gid)
            return original(tool_call)

        traced._jarvis_reply_diagnostics = True
        plugin._handle_tool_calls = traced

    def _wrap_server_content(self, plugin) -> None:
        original = plugin._handle_server_content
        if getattr(original, "_jarvis_reply_diagnostics", False):
            return

        def traced(server_content):
            generation = getattr(plugin, "_current_generation", None)
            gid = getattr(generation, "response_id", None)
            try:
                return original(server_content)
            finally:
                if getattr(server_content, "generation_complete", None):
                    self.event("generation_complete", generation=gid)
                if getattr(server_content, "interrupted", None):
                    self.event("server_interrupted", generation=gid)
                if getattr(server_content, "turn_complete", None):
                    self.event("turn_complete", generation=gid)

        traced._jarvis_reply_diagnostics = True
        plugin._handle_server_content = traced

    def attach_output(self, output) -> None:
        if id(output) in self._outputs:
            return
        self._outputs.add(id(output))
        output.on(
            "playback_started",
            lambda _ev: self.event("playback_started", reply=self._current()),
        )
        output.on(
            "playback_finished",
            lambda ev: self.event(
                "playback_interrupted"
                if getattr(ev, "interrupted", False)
                else "playback_finished",
                reply=self._current(),
            ),
        )

    def _current(self) -> str | None:
        session = self._session
        try:
            return _speech_id(session.current_speech) if session is not None else None
        except Exception:  # noqa: BLE001 - diagnostics never fail the session
            return None

    # --- reply / generation pairing ----------------------------------------

    def _on_speech_created(self, ev) -> None:
        self._refresh()
        handle = getattr(ev, "speech_handle", None)
        reply = _speech_id(handle)
        if reply is None:
            return
        self.event("speech_created", reply=reply)
        self._unlinked_speeches.append(reply)
        self._link()
        try:
            handle.add_done_callback(self._on_speech_done)
        except Exception:  # noqa: BLE001 - diagnostics never fail the session
            LOGGER.debug("Reply diagnostic could not watch speech completion")

    def _on_generation_created(self, ev) -> None:
        gid = getattr(ev, "response_id", None)
        if not isinstance(gid, str):
            return
        self.event("generation_created", generation=gid)
        self._unlinked_generations.append(gid)
        self._link()

    def _link(self) -> None:
        while self._unlinked_speeches and self._unlinked_generations:
            reply = self._unlinked_speeches.popleft()
            gid = self._unlinked_generations.popleft()
            self._reply_of[gid] = reply
            self.event("generation_linked", reply=reply, generation=gid)

    def _on_speech_done(self, handle) -> None:
        reply = _speech_id(handle)
        self.event(
            "speech_done_interrupted"
            if getattr(handle, "interrupted", False)
            else "speech_done",
            reply=reply,
        )
        try:
            items = list(handle.chat_items)
        except Exception:  # noqa: BLE001
            items = []
        if not any(getattr(item, "role", None) == "assistant" for item in items):
            self.event("reply_uncommitted", reply=reply)
