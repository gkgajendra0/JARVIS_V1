"""Public realtime adapters that fence obsolete Gemini transports and streams."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace

from livekit import rtc
from livekit.agents import llm
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities


@dataclass(slots=True)
class GeminiTransportState:
    epoch: int
    current_epoch: Callable[[], int]
    authorize: Callable | None = None
    budget: object | None = None
    ready: bool = True
    active: bool = True
    output_sample_rate: int | None = None
    restored_ids: frozenset[str] = frozenset()

    @property
    def current(self):
        return self.active and self.epoch == self.current_epoch()

    async def require_context(self):
        if not self.current:
            raise llm.RealtimeError("Obsolete Gemini transport")
        if self.authorize is not None:
            valid = self.authorize()
            if inspect.isawaitable(valid):
                valid = await valid
            if valid is not True or not self.current:
                raise llm.RealtimeError(
                    "Gemini context authorization no longer current"
                )


class GuardedGeminiRealtimeModel(llm.RealtimeModel):
    def __init__(self, inner, state: GeminiTransportState):
        super().__init__(capabilities=inner.capabilities)
        self.inner = inner
        self.state = state
        self.sessions = []
        self._close_task = None

    @property
    def model(self):
        return self.inner.model

    @property
    def provider(self):
        return self.inner.provider

    def session(self, *, turn_detection_disabled=False):
        if not self.state.current:
            raise llm.RealtimeError("Retired Gemini model cannot reconnect")
        if self.state.budget is not None:
            self.state.budget.before_connect()
        session = GuardedGeminiRealtimeSession(
            self, self.inner.session(turn_detection_disabled=turn_detection_disabled)
        )
        self.sessions.append(session)
        return session

    def retire(self):
        self.state.active = False
        if self._close_task is None:
            self._close_task = asyncio.create_task(self.aclose())

    async def aclose(self):
        self.state.active = False
        await self.inner.aclose()
        if self.state.budget is not None:
            self.state.budget.close()


class GuardedGeminiRealtimeSession(llm.RealtimeSession):
    def __init__(self, model, inner):
        super().__init__(model)
        self.inner = inner
        self.state = model.state
        self._handlers = {}
        for name in (
            "input_speech_started",
            "input_speech_stopped",
            "input_audio_transcription_completed",
            "generation_created",
            "session_reconnected",
            "metrics_collected",
            "remote_item_added",
            "error",
        ):

            def forward(value, event_name=name):
                self._forward(event_name, value)

            self._handlers[name] = forward
            inner.on(name, forward)

    @property
    def chat_ctx(self):
        return self.inner.chat_ctx

    @property
    def tools(self):
        return self.inner.tools

    def _forward(self, name, value):
        if name == "metrics_collected" and self.state.budget is not None:
            self.state.budget.observe_usage(value)
        if not self.state.current:
            return
        if name == "remote_item_added" and value.item.id in self.state.restored_ids:
            return
        if name == "generation_created":
            value = replace(
                value,
                message_stream=self._messages(value.message_stream),
                function_stream=self._stream(value.function_stream),
            )
        self.emit(name, value)

    async def _stream(self, source):
        async for item in source:
            if not self.state.current or not self.state.ready:
                return
            yield item

    async def _audio(self, source):
        resampler = None
        async for frame in source:
            if not self.state.current or not self.state.ready:
                return
            rate = self.state.output_sample_rate
            if rate is not None and frame.sample_rate != rate and resampler is None:
                resampler = rtc.AudioResampler(
                    input_rate=frame.sample_rate,
                    output_rate=rate,
                    num_channels=frame.num_channels,
                )
            frames = resampler.push(frame) if resampler is not None else [frame]
            for output in frames:
                if not self.state.current or not self.state.ready:
                    return
                output.userdata["jarvis_transport_epoch"] = self.state.epoch
                yield output
        if resampler is not None:
            for output in resampler.flush():
                if not self.state.current or not self.state.ready:
                    return
                output.userdata["jarvis_transport_epoch"] = self.state.epoch
                yield output

    async def _messages(self, source):
        async for message in self._stream(source):
            yield replace(
                message,
                text_stream=self._stream(message.text_stream),
                audio_stream=self._audio(message.audio_stream),
            )

    async def update_instructions(self, instructions):
        await self.state.require_context()
        if self.state.budget is not None:
            self.state.budget.admit_instructions(instructions)
        await self.inner.update_instructions(instructions)

    async def update_chat_ctx(self, chat_ctx):
        await self.state.require_context()
        if self.state.budget is not None:
            self.state.budget.admit_context(chat_ctx)
        await self.inner.update_chat_ctx(chat_ctx)

    async def update_tools(self, tools):
        await self.state.require_context()
        if self.state.budget is not None:
            self.state.budget.admit_tools(tools)
        await self.inner.update_tools(tools)

    def update_options(self, **kwargs):
        if self.state.current:
            self.inner.update_options(**kwargs)

    def push_audio(self, frame):
        if (
            self.state.current
            and self.state.ready
            and (self.state.budget is None or self.state.budget.allow_input(frame))
        ):
            self.inner.push_audio(frame)

    def push_video(self, frame):
        # Paid modality exposure must be separately admitted, never inferred from audio.
        if self.state.current and self.state.ready and self.state.budget is None:
            self.inner.push_video(frame)

    def generate_reply(self, **kwargs):
        if not self.state.current or not self.state.ready:
            future = asyncio.get_running_loop().create_future()
            future.set_exception(
                llm.RealtimeError("Gemini generation transport unavailable")
            )
            return future
        if self.state.budget is not None:
            self.state.budget.admit_generation(kwargs)
        return self.inner.generate_reply(**kwargs)

    def commit_audio(self):
        if self.state.current and self.state.ready:
            self.inner.commit_audio()

    def clear_audio(self):
        self.inner.clear_audio()

    def interrupt(self):
        self.inner.interrupt()

    def truncate(self, **kwargs):
        if self.state.current:
            self.inner.truncate(**kwargs)

    def start_user_activity(self):
        if self.state.current and self.state.ready:
            self.inner.start_user_activity()

    async def aclose(self):
        for name, callback in self._handlers.items():
            self.inner.off(name, callback)
        await self.inner.aclose()


class GeminiEpochAudioOutput(AudioOutput):
    """Reject stale provider audio immediately above the shared physical device."""

    def __init__(self, output, current_epoch):
        super().__init__(
            label="gemini-transport",
            sample_rate=output.sample_rate,
            capabilities=AudioOutputCapabilities(pause=output.can_pause),
            next_in_chain=output,
        )
        self._output = output
        self._current_epoch = current_epoch
        self._detached = False

    async def capture_frame(self, frame):
        if (
            not self._detached
            and frame.userdata.get("jarvis_transport_epoch") == self._current_epoch()
        ):
            await super().capture_frame(frame)
            await self._next_in_chain.capture_frame(frame)

    def flush(self):
        super().flush()
        self._next_in_chain.flush()

    def clear_buffer(self):
        self._next_in_chain.clear_buffer()

    def detach(self):
        if self._detached:
            return
        self._detached = True
        chain = self._next_in_chain
        for name in ("playback_finished", "playback_started", "playback_progressed"):
            chain.off(name, getattr(self, f"_forward_next_{name}"))
            if chain is not self._output:
                self._output.off(name, getattr(chain, f"_forward_next_{name}"))
