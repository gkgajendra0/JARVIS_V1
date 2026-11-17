"""A Jarvis-requested reply must reach the speaker (the voice stall).

Live (Zanskar 2026-11-16; Munnar, Ladakh and the #321 diagnostic run
2026-11-17): after Jarvis requested a reply itself (a replacement for an
answer given before project context, a correction, a forget nudge), that
reply never played and never finished, every later reply ended only when
LiveKit force-cancelled it, nothing was transcribed or saved, and tool results
were never handed back to Gemini.

Cause: GuardedGeminiRealtimeSession fenced (epoch-stamped) the streams of
generations Gemini started, but a requested reply reaches LiveKit through the
generate_reply future, unfenced. GeminiEpochAudioOutput then dropped all of its
audio after ProjectAudioGate and PersonalContextAudioOutput had counted the
segment, so that segment never reported playback_finished and every later
wait_for_playout waited on it.

These tests run the production audio chain, including the real shared
MediaDevicesAudioOutput, with a plugin-shaped Gemini session.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
import test_reply_diagnostics as fakes
from livekit.agents import Agent, AgentSession, function_tool
from livekit.agents.llm import InputSpeechStartedEvent

from jarvis.voice import reply_diagnostics
from jarvis.voice.gemini_transport import (
    GeminiEpochAudioOutput,
    GeminiTransportState,
    GuardedGeminiRealtimeModel,
)
from jarvis.voice.media_devices_audio import MediaDevicesAudioOutput
from jarvis.voice.personal_context_audio import PersonalContextAudioOutput
from jarvis.voice.project_voice_audio import ProjectAudioGate

EPOCH = "jarvis_transport_epoch"


@pytest.fixture(autouse=True)
def no_active_trace():
    reply_diagnostics._ACTIVE = None
    yield
    reply_diagnostics._ACTIVE = None


def guarded_model(*, output_sample_rate=None):
    state = GeminiTransportState(
        epoch=0, current_epoch=lambda: 0, output_sample_rate=output_sample_rate
    )
    return GuardedGeminiRealtimeModel(fakes.PluginShapedModel(), state)


@pytest.mark.asyncio
async def test_requested_reply_audio_carries_the_transport_epoch():
    model = guarded_model()
    session = model.session()
    pending = session.generate_reply(instructions="answer again")
    session.inner.serve("GR_repl", 0.2, text="answer", turn_complete=True)
    event = await asyncio.wait_for(pending, 1)
    async for message in event.message_stream:
        frames = [frame async for frame in message.audio_stream]
        assert frames
        assert all(frame.userdata.get(EPOCH) == 0 for frame in frames)


@pytest.mark.asyncio
async def test_requested_reply_failure_and_cancellation_propagate():
    model = guarded_model()
    session = model.session()
    pending = session.generate_reply(instructions="x")
    session.inner.pending.pop(0).set_exception(RuntimeError("timed out"))
    with pytest.raises(RuntimeError, match="timed out"):
        await pending
    pending = session.generate_reply(instructions="y")
    inner = session.inner.pending[-1]
    pending.cancel()
    await asyncio.sleep(0)
    assert inner.cancelled()


class RealtimeSource:
    """rtc.AudioSource + OutputPlayer stand-in: drains in real time and
    back-pressures past 1 s queued (queue_size_ms=1000)."""

    def __init__(self):
        self.until = time.monotonic()

    @property
    def queued_duration(self):
        return max(0.0, self.until - time.monotonic())

    async def capture_frame(self, frame):
        while self.queued_duration > 1.0:
            await asyncio.sleep(0.01)
        self.until = max(self.until, time.monotonic()) + frame.duration

    def clear_queue(self):
        self.until = time.monotonic()


class UnprotectedPersonal:
    def bind_audio_clear(self, callback):
        pass

    def playback_finished(self):
        pass

    async def allow_audio(self):
        return True

    def close(self, **kwargs):
        pass


class AllowAll:
    async def response_audio_allowed(self):
        return True

    def allow_response_audio(self):
        return True


class EarlyAnswerTurns:
    """VoiceProjectTurns for this sequence: the first answer came before
    project context, so it is held back and interrupted; once the held speech
    has played out (or 5 s pass) the context is delivered and a replacement is
    requested; from then on answers play."""

    def __init__(self):
        self.session = None
        self.delivered = False
        self.blocked = None
        self.replacement = None

    async def response_audio_allowed(self):
        await asyncio.sleep(0.35)  # _FAST_PATH_TEXT_WAIT_SECONDS
        return self.allow_response_audio()

    def allow_response_audio(self):
        if self.delivered:
            return True
        speech = self.session.current_speech
        if speech is self.blocked:
            return False
        self.blocked = speech
        speech.interrupt()
        asyncio.get_running_loop().create_task(self._repair(speech))
        return False

    async def _repair(self, held):
        try:
            await asyncio.wait_for(asyncio.shield(held.wait_for_playout()), 5)
        except TimeoutError:
            pass
        self.delivered = True
        self.replacement = self.session.generate_reply(instructions="answer again")


def production_chain(device, turns):
    """canonical_active_speaker_runtime._session_audio_output over
    runtime's GeminiEpochAudioOutput, over the shared speaker."""
    epoch = GeminiEpochAudioOutput(device, lambda: 0)
    personal = PersonalContextAudioOutput(epoch, UnprotectedPersonal())
    return ProjectAudioGate(personal, turns), (personal, epoch)


def serve(rt, gid, seconds, *, turn_complete_after):
    """Gemini: audio and generation_complete now; turn_complete later, once it
    judges the client has played the audio."""
    plugin = rt.inner
    plugin.serve(gid, seconds, text="(answer)", turn_complete=False)
    asyncio.get_running_loop().call_later(
        turn_complete_after,
        lambda: plugin._handle_server_content(
            SimpleNamespace(
                generation_complete=None, turn_complete=True, interrupted=None
            )
        ),
    )


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.asyncio
async def test_replacement_plays_and_later_replies_and_tool_results_flow(
    monkeypatch,
):
    monkeypatch.setattr(fakes, "RATE", 48000)  # the device rate: no resampling
    device = MediaDevicesAudioOutput(None, output_device=None)
    device._loop = asyncio.get_running_loop()
    device._source = RealtimeSource()
    started = []
    device.on("playback_started", lambda _ev: started.append(time.monotonic()))

    # The startup greeting uses the same speaker first; its chain stays
    # subscribed to the device after that session ends, as live.
    greeting_model = guarded_model(output_sample_rate=48000)
    greeting = AgentSession(llm=greeting_model)
    greeting.output.audio, _ = production_chain(device, AllowAll())
    await greeting.start(Agent(instructions="greeting"))
    serve(greeting_model.sessions[-1], "GR_greet", 0.5, turn_complete_after=0.7)
    await asyncio.sleep(1.5)
    await greeting.aclose()

    model = guarded_model(output_sample_rate=48000)
    turns = EarlyAnswerTurns()
    tool_outputs = []
    committed = []

    @function_tool
    async def remember_memory(fact: str = "") -> str:
        """Stand-in memory tool that fails like the live one did."""
        raise ValueError("the exact memory predicate must be named")

    session = AgentSession(llm=model)
    session.output.audio, layers = production_chain(device, turns)
    turns.session = session
    session.on("function_tools_executed", lambda ev: tool_outputs.append(ev))
    session.on(
        "conversation_item_added",
        lambda ev: (
            committed.append(ev.item.text_content)
            if getattr(ev.item, "role", None) == "assistant"
            else None
        ),
    )
    async with session:
        await session.start(Agent(instructions="wake", tools=[remember_memory]))
        rt = model.sessions[-1]

        # 1. "What time is it?" answered before project context: held back.
        rt.emit("input_speech_started", InputSpeechStartedEvent())
        serve(rt, "GR_early", 0.5, turn_complete_after=1.0)
        for _ in range(800):
            if rt.inner.pending:
                break
            await asyncio.sleep(0.01)
        assert rt.inner.pending, "the replacement was never requested"

        # 2. The replacement reaches the speaker, finishes and is committed.
        before = len(started)
        serve(rt, "GR_repl", 1.0, turn_complete_after=1.5)
        await asyncio.sleep(3.0)
        assert len(started) == before + 1, "the replacement never played"
        assert turns.replacement.done() and not turns.replacement.interrupted
        assert committed and committed[-1] == "(answer)"
        for layer in (session.output.audio, *layers):
            assert layer._pending_playback_count == 0, layer.label

        # 3. The next answer plays at once and finishes on its own.
        rt.emit("input_speech_started", InputSpeechStartedEvent())
        await asyncio.sleep(0.2)
        before = len(started)
        serve(rt, "GR_again", 1.0, turn_complete_after=1.5)
        await asyncio.sleep(0.8)
        assert len(started) == before + 1, "the next answer waited"
        await asyncio.sleep(2.0)
        assert len(committed) == 2

        # 4. A memory tool call runs at once and its result goes back.
        rt.emit("input_speech_started", InputSpeechStartedEvent())
        await asyncio.sleep(0.2)
        rt.inner.serve_tool_call("GR_tool", "remember_memory")
        await asyncio.sleep(1.0)
        assert tool_outputs, "the tool result was never handed back to Gemini"
