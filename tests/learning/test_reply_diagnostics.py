"""Opt-in reply diagnostics and the reproduced missing-turn_complete stall.

Live (Munnar 2026-11-17): Gemini answered before project context, Jarvis held
that answer back and requested a replacement. For the rest of the wake every
answer played but none was transcribed or saved, and each turn logged LiveKit's
"speech not done in time after interruption". Offline, the real LiveKit
AgentSession shows exactly this when Gemini sends generation_complete but no
turn_complete: the plugin closes the message stream only on turn_complete.

These tests drive that sequence through the real AgentSession, Jarvis's real
ProjectAudioGate and a plugin-shaped fake realtime session, and check that the
diagnostics show it, with IDs and timestamps only.
"""

import asyncio
import logging
import re
import time
from types import SimpleNamespace

import pytest
from livekit import rtc
from livekit.agents import Agent, AgentSession, function_tool, llm, utils
from livekit.agents.llm import (
    FunctionCall,
    GenerationCreatedEvent,
    InputSpeechStartedEvent,
    MessageGeneration,
)
from livekit.agents.voice import speech_handle as speech_handle_module
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

from jarvis.voice import reply_diagnostics
from jarvis.voice.project_voice_audio import ProjectAudioGate

RATE = 24000
LINE = re.compile(
    r"^Reply diagnostic \| event=[a-z_]+ reply=(speech_\w+|-) "
    r"generation=(GR_\w+|-) t_ms=\d+$"
)
SECRET = "Hilltop Cottage and the Creta"  # conversation text that must never be logged


@pytest.fixture(autouse=True)
def no_active_trace():
    reply_diagnostics._ACTIVE = None
    yield
    reply_diagnostics._ACTIVE = None


def test_off_by_default():
    assert not reply_diagnostics.enabled({})
    assert not reply_diagnostics.enabled({reply_diagnostics.ENV: "0"})
    assert reply_diagnostics.enabled({reply_diagnostics.ENV: "1"})
    assert reply_diagnostics.enabled({reply_diagnostics.ENV: "true"})
    assert reply_diagnostics.active() is None
    reply_diagnostics.note("early_answer_held_back", SimpleNamespace(id="speech_x"))


def test_production_session_attaches_only_when_enabled():
    import inspect

    from jarvis.voice import livekit_session

    source = inspect.getsource(livekit_session)
    attach = source.index("ReplyDiagnostics().attach(livekit_session)")
    guard = source.rindex("if reply_diagnostics.enabled():", 0, attach)
    assert attach - guard < 300


def test_lines_hold_ids_and_timestamps_only(caplog):
    caplog.set_level(logging.INFO, logger="jarvis.voice.reply_diagnostics")
    trace = reply_diagnostics.ReplyDiagnostics()
    trace.event("playback_started", reply="speech_abc")
    trace.event("turn_complete", generation="GR_def")
    trace.event("input_speech_started")
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 3 and all(LINE.match(line) for line in lines)


# --- a plugin-shaped realtime model ---------------------------------------


class _Generation:
    def __init__(self, gid):
        self.response_id = gid
        self.message_ch = utils.aio.Chan[MessageGeneration]()
        self.function_ch = utils.aio.Chan[FunctionCall]()
        self.text_ch = utils.aio.Chan[str]()
        self.audio_ch = utils.aio.Chan[rtc.AudioFrame]()
        modalities = asyncio.Future()
        modalities.set_result(["audio", "text"])
        self.message_ch.send_nowait(
            MessageGeneration(
                message_id=gid,
                text_stream=self.text_ch,
                audio_stream=self.audio_ch,
                modalities=modalities,
            )
        )


class PluginShapedSession(llm.RealtimeSession):
    """Mirrors the Google plugin's generation lifecycle: output streams close on
    generation_complete, the message stream only on turn_complete."""

    def __init__(self, model):
        super().__init__(model)
        self._chat_ctx = llm.ChatContext.empty()
        self._tools = llm.ToolContext.empty()
        self._current_generation = None
        self.pending = []

    @property
    def chat_ctx(self):
        return self._chat_ctx

    @property
    def tools(self):
        return self._tools

    async def update_instructions(self, instructions):
        pass

    async def update_chat_ctx(self, chat_ctx):
        self._chat_ctx = chat_ctx

    async def update_tools(self, tools):
        self._tools = llm.ToolContext(tools)

    def update_options(self, **kwargs):
        pass

    def push_audio(self, frame):
        pass

    def push_video(self, frame):
        pass

    def generate_reply(self, **kwargs):
        fut = asyncio.get_event_loop().create_future()
        self.pending.append(fut)
        return fut

    def commit_audio(self):
        pass

    def clear_audio(self):
        pass

    def interrupt(self):
        pass

    def truncate(self, **kwargs):
        pass

    async def aclose(self):
        pass

    def serve(self, gid, seconds, *, text, turn_complete):
        """Gemini produces one generation: audio, then its signals."""
        gen = self._current_generation = _Generation(gid)
        event = GenerationCreatedEvent(
            message_stream=gen.message_ch,
            function_stream=gen.function_ch,
            user_initiated=bool(self.pending),
            response_id=gid,
        )
        if self.pending:  # like the plugin: resolve generate_reply, then emit
            self.pending.pop(0).set_result(event)
        self.emit("generation_created", event)
        gen.text_ch.send_nowait(text)
        n = RATE // 10
        for _ in range(int(seconds * 10)):
            gen.audio_ch.send_nowait(
                rtc.AudioFrame(
                    data=b"\x00\x01" * n,
                    sample_rate=RATE,
                    num_channels=1,
                    samples_per_channel=n,
                )
            )
        self._handle_server_content(
            SimpleNamespace(
                generation_complete=True, turn_complete=None, interrupted=None
            )
        )
        if turn_complete:
            self._handle_server_content(
                SimpleNamespace(
                    generation_complete=None, turn_complete=True, interrupted=None
                )
            )

    def serve_tool_call(self, gid, name):
        """Gemini answers a question with a tool call, like the plugin: the
        call goes out on the function stream and the generation closes."""
        gen = self._current_generation = _Generation(gid)
        gen.text_ch.close()
        gen.audio_ch.close()
        self.emit(
            "generation_created",
            GenerationCreatedEvent(
                message_stream=gen.message_ch,
                function_stream=gen.function_ch,
                user_initiated=False,
                response_id=gid,
            ),
        )
        self._handle_tool_calls(
            SimpleNamespace(
                function_calls=[SimpleNamespace(id="call_1", name=name, args={})]
            )
        )

    def _handle_tool_calls(self, tool_call):
        gen = self._current_generation
        for call in tool_call.function_calls:
            gen.function_ch.send_nowait(
                FunctionCall(call_id=call.id, name=call.name, arguments="{}")
            )
        gen.message_ch.close()
        gen.function_ch.close()

    def _handle_server_content(self, server_content):
        gen = self._current_generation
        if gen is None:
            return
        if server_content.generation_complete:
            gen.text_ch.close()
            gen.audio_ch.close()
        if server_content.turn_complete:
            gen.message_ch.close()
            gen.function_ch.close()


class PluginShapedModel(llm.RealtimeModel):
    def __init__(self):
        super().__init__(
            capabilities=llm.RealtimeCapabilities(
                message_truncation=False,
                turn_detection=True,
                user_transcription=True,
                auto_tool_reply_generation=True,
                audio_output=True,
                manual_function_calls=False,
            )
        )
        self.sessions = []

    def session(self, **kwargs):
        session = PluginShapedSession(self)
        self.sessions.append(session)
        return session

    async def aclose(self):
        pass


class VirtualSpeaker(AudioOutput):
    """Plays captured audio in real time and reports start/finish like the device."""

    def __init__(self):
        super().__init__(
            label="virtual-speaker",
            capabilities=AudioOutputCapabilities(pause=False),
            sample_rate=None,
        )
        self._pushed = 0.0
        self._started = None
        self._timer = None

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self._pushed += frame.duration
        if self._started is None:
            self._started = time.monotonic()
            self.on_playback_started(created_at=time.time())

    def flush(self):
        super().flush()
        if not self._pushed:
            return
        pushed = self._pushed
        delay = max(0.0, pushed - (time.monotonic() - self._started))

        def finished():
            self._pushed, self._started, self._timer = 0.0, None, None
            self.on_playback_finished(playback_position=pushed, interrupted=False)

        self._timer = asyncio.get_event_loop().call_later(delay, finished)

    def clear_buffer(self):
        if not self._pushed:
            return
        if self._timer is not None:
            self._timer.cancel()
        position = min(self._pushed, time.monotonic() - self._started)
        self._pushed, self._started, self._timer = 0.0, None, None
        self.on_playback_finished(playback_position=position, interrupted=True)


class EarlyAnswerTurns:
    """VoiceProjectTurns' audio decision for this sequence: the first answer
    came before project context, so it is held back and replaced."""

    def __init__(self):
        self.session = None
        self.replacement = None

    def allow_response_audio(self):
        if self.replacement is None:
            held = self.session.current_speech
            reply_diagnostics.note("early_answer_held_back", held)
            held.interrupt()
            self.replacement = self.session.generate_reply(instructions="answer again")
            reply_diagnostics.note("replacement_requested", self.replacement)
            return False
        return True


def events(caplog):
    out = []
    for record in caplog.records:
        if record.name == "jarvis.voice.reply_diagnostics":
            message = record.getMessage()
            assert LINE.match(message), message
            assert SECRET not in message
            fields = dict(
                part.split("=", 1) for part in message.split(" | ")[1].split()
            )
            out.append((fields["event"], fields["reply"], fields["generation"]))
    return out


# LiveKit's arbitrary cancellation of the stuck reply (the behaviour under
# test) leaves its tool task unawaited at teardown.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.asyncio
async def test_reproduced_missing_turn_complete_sequence(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(speech_handle_module, "INTERRUPTION_TIMEOUT", 0.3)
    model = PluginShapedModel()
    turns = EarlyAnswerTurns()
    async with AgentSession(llm=model) as session:
        session.output.audio = ProjectAudioGate(VirtualSpeaker(), turns)
        turns.session = session
        reply_diagnostics.ReplyDiagnostics().attach(session)
        await session.start(Agent(instructions="test"))
        rt = model.sessions[-1]

        # 1. Gemini answers before project context; it closes normally.
        rt.serve("GR_early", 0.5, text=SECRET, turn_complete=True)
        for _ in range(300):
            if rt.pending:
                break
            await asyncio.sleep(0.01)
        assert rt.pending, "the replacement was never requested"
        # 2. The replacement: generation_complete, but turn_complete never comes.
        rt.serve("GR_repl", 0.5, text=SECRET, turn_complete=False)
        await asyncio.sleep(1.2)
        replacement = turns.replacement
        assert not replacement.done()  # played, but never finished
        # 3. The owner speaks: the stuck reply is interrupted and force-ended.
        rt.emit("input_speech_started", InputSpeechStartedEvent())
        await asyncio.sleep(0.8)
        assert replacement.done()

    log = events(caplog)
    early, repl = None, replacement.id
    for name, reply, generation in log:
        if name == "generation_linked" and generation == "GR_early":
            early = reply
    assert early is not None and early != repl

    def has(name, reply=None, generation=None):
        return any(
            n == name
            and (reply is None or r == reply)
            and (generation is None or g == generation)
            for n, r, g in log
        )

    assert has("early_answer_held_back", early)
    assert has("replacement_requested", repl)
    assert has("generation_linked", repl, "GR_repl")
    assert has("turn_complete", early, "GR_early")
    assert has("playback_started", repl) and has("playback_finished", repl)
    assert has("generation_complete", repl, "GR_repl")
    assert not has("turn_complete", generation="GR_repl")  # the missing signal
    assert has("input_speech_started")
    assert has("speech_done_interrupted", repl)
    assert has("reply_uncommitted", repl)  # heard, never transcribed or saved
    order = [n for n, r, _ in log if r == repl]
    assert order.index("playback_finished") < order.index("speech_done_interrupted")


# Same teardown note as above.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.asyncio
async def test_tool_answer_that_never_arrives_is_visible(caplog, monkeypatch):
    """Ladakh/Spiti, 2026-11-17 12:19 UTC, in an already stalled wake: Gemini
    called the personal-context tool, it returned four facts, and no answer was
    ever heard. The diagnostics must show the tool call, the tool result handed
    back, and that no answer generation or playback followed."""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(speech_handle_module, "INTERRUPTION_TIMEOUT", 0.3)
    model = PluginShapedModel()
    turns = EarlyAnswerTurns()
    looked_up = []

    @function_tool
    async def read_personal_context_for_question(question: str = "") -> str:
        """Stand-in for the personal-context read."""
        looked_up.append(True)
        return "4 facts"

    async with AgentSession(llm=model) as session:
        session.output.audio = ProjectAudioGate(VirtualSpeaker(), turns)
        turns.session = session
        reply_diagnostics.ReplyDiagnostics().attach(session)
        await session.start(
            Agent(instructions="test", tools=[read_personal_context_for_question])
        )
        rt = model.sessions[-1]
        rt.serve("GR_early", 0.5, text=SECRET, turn_complete=True)
        for _ in range(300):
            if rt.pending:
                break
            await asyncio.sleep(0.01)
        rt.serve("GR_repl", 0.5, text=SECRET, turn_complete=False)  # the stall
        await asyncio.sleep(1.2)
        rt.emit("input_speech_started", InputSpeechStartedEvent())  # next question
        await asyncio.sleep(0.6)
        rt.serve_tool_call("GR_tool", "read_personal_context_for_question")
        await asyncio.sleep(1.0)  # Gemini sends nothing after the tool result
        assert looked_up

    log = events(caplog)
    names = [n for n, _, _ in log]
    assert any(n == "tool_call" and g == "GR_tool" for n, _, g in log)
    assert "tool_output_sent" in names
    after = names[names.index("tool_output_sent") + 1 :]
    assert "generation_created" not in after  # no answer generation
    assert "playback_started" not in after  # nothing reached the speaker
