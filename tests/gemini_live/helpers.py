"""Synthetic public GenAI endpoint; actual governor and SDK schemas stay real."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from google.genai import types
from livekit import rtc
from livekit.agents import llm
from tests.gemini_live.test_budget import live_env

from jarvis.voice.gemini_transport import GeminiTransportState


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


class Wire:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def send_client_content(self, **kwargs):
        self.sent.append(("content", types.LiveClientContent(**kwargs)))

    async def send_realtime_input(self, **kwargs):
        self.sent.append(("input", types.LiveClientRealtimeInput(**kwargs)))

    async def send_tool_response(self, **kwargs):
        self.sent.append(("tool", types.LiveClientToolResponse(**kwargs)))

    async def receive(self):
        while True:
            event = await self.events.get()
            if isinstance(event, Exception):
                raise event
            yield event
            if event.server_content and event.server_content.turn_complete:
                return

    def feed(self, **kwargs):
        self.events.put_nowait(types.LiveServerMessage(**kwargs))


class Endpoint:
    def __init__(self, runtime):
        self.runtime = runtime
        self.wires = []
        self.configs = []
        self.clients = 0
        self.setup_error = None

    def client(self):
        assert self.runtime.paid_budget.status().reserved_inr_minor >= 3993
        self.clients += 1
        return SimpleNamespace(
            aio=SimpleNamespace(
                live=SimpleNamespace(connect=self.connect), aclose=self.aclose
            )
        )

    async def aclose(self):
        pass

    @asynccontextmanager
    async def connect(self, *, model, config):
        assert self.runtime.paid_budget.status().reserved_inr_minor >= 3993
        self.configs.append(types.LiveConnectConfig.model_validate(config))
        if self.setup_error:
            raise self.setup_error
        wire = Wire(self)
        self.wires.append(wire)
        try:
            yield wire
        finally:
            wire.closed = True


def frame(samples=320):
    return rtc.AudioFrame(
        data=bytes(samples * 2),
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=samples,
    )


def environment(tmp_path, *, authorize=lambda: True):
    from jarvis.voice.gemini_live_model import ControlledGeminiLiveModel

    admission, runtime, target, _ = live_env(tmp_path, authorize=authorize)
    endpoint = Endpoint(runtime)
    epoch = [1]
    state = GeminiTransportState(
        epoch=1, current_epoch=lambda: epoch[0], authorize=authorize
    )
    model = ControlledGeminiLiveModel(
        target=target,
        voice="Puck",
        state=state,
        admission=admission,
        client_factory=endpoint.client,
    )
    session = model.session(turn_detection_disabled=True)
    return SimpleNamespace(
        model=model,
        session=session,
        endpoint=endpoint,
        runtime=runtime,
        epoch=epoch,
        state=state,
    )


async def context(session):
    ctx = llm.ChatContext.empty()
    ctx.add_message(
        role="user", content="Meri vegetarian preference ke hisaab se suggest karo"
    )
    await session.update_chat_ctx(ctx)
    return ctx


from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities


class SyntheticPlayback(AudioOutput):
    def __init__(self):
        super().__init__(
            label="synthetic playback",
            sample_rate=24000,
            capabilities=AudioOutputCapabilities(pause=False),
        )
        self.pending = False
        self.duration = 0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.pending = True
        self.duration += frame.duration

    def flush(self):
        super().flush()
        if self.pending:
            self.pending = False
            self.on_playback_finished(
                playback_position=self.duration, interrupted=False
            )
            self.duration = 0

    def clear_buffer(self):
        if self.pending:
            self.pending = False
            self.on_playback_finished(playback_position=0, interrupted=True)
            self.duration = 0
