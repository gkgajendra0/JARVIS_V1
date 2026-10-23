"""Real LiveKit public interfaces; the only fake is the provider transport."""

import asyncio
from collections import defaultdict
from types import SimpleNamespace

from livekit.agents import llm


async def empty_stream():
    if False:
        yield None


class ProviderSession(llm.RealtimeSession):
    def __init__(self, model):
        super().__init__(model)
        self._ctx = llm.ChatContext.empty()
        self._tools = llm.ToolContext([])
        self.closed = False
        self.replies = 0
        self.reply_started = asyncio.Event()
        self.audio = []
        self.instructions = ""

    @property
    def chat_ctx(self):
        return self._ctx

    @property
    def tools(self):
        return self._tools

    async def update_chat_ctx(self, chat_ctx):
        self._ctx = chat_ctx.copy()

    async def update_tools(self, tools):
        self._tools = llm.ToolContext(tools)

    async def update_instructions(self, instructions):
        self.instructions = instructions

    def update_options(self, **kwargs):
        pass

    def push_audio(self, frame):
        self.audio.append(frame)

    def push_video(self, frame):
        pass

    def commit_audio(self):
        pass

    def clear_audio(self):
        self.audio.clear()

    def interrupt(self):
        pass

    def truncate(self, **kwargs):
        pass

    async def aclose(self):
        self.closed = True

    def generate_reply(self, **kwargs):
        self.replies += 1
        self.reply_started.set()
        event = llm.GenerationCreatedEvent(
            message_stream=empty_stream(),
            function_stream=empty_stream(),
            user_initiated=True,
        )
        future = asyncio.get_running_loop().create_future()
        future.set_result(event)
        self.emit("generation_created", event)
        return future


class ProviderModel(llm.RealtimeModel):
    def __init__(self, slot="free"):
        super().__init__(
            capabilities=llm.RealtimeCapabilities(
                message_truncation=False,
                turn_detection=True,
                user_transcription=True,
                auto_tool_reply_generation=True,
                audio_output=True,
                manual_function_calls=False,
                mutable_chat_context=True,
                mutable_instructions=True,
                mutable_tools=False,
            )
        )
        self.slot = slot
        self.sessions = []

    @property
    def model(self):
        return "gemini-test-live"

    @property
    def provider(self):
        return "gemini"

    def session(self, **kwargs):
        session = ProviderSession(self)
        self.sessions.append(session)
        return session

    async def aclose(self):
        for session in self.sessions:
            await session.aclose()


class SessionEvents:
    def __init__(self):
        self.handlers = defaultdict(list)
        self.closed = False
        self.input = SimpleNamespace(set_audio_enabled=lambda _: None)
        self.output = SimpleNamespace(audio=None)
        self.current_agent = None

    def on(self, event, callback):
        self.handlers[event].append(callback)

    def emit(self, event, value):
        for callback in tuple(self.handlers[event]):
            callback(value)

    async def aclose(self):
        self.closed = True
