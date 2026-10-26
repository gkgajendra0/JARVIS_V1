"""One serialized sender and one public receiver; no implicit paid reconnect."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections import deque
from uuid import uuid4

from google.genai import types
from livekit import rtc
from livekit.agents import llm
from livekit.agents.types import NOT_GIVEN
from livekit.agents.utils import is_given

from jarvis.voice.gemini_live_events import LiveResponse, sanitized_live_error


class ControlledGeminiLiveSession(llm.RealtimeSession):
    def __init__(self, model):
        super().__init__(model)
        self.model = model
        self._ctx = llm.ChatContext.empty()
        self._tools = llm.ToolContext.empty()
        self._instructions = ""
        self._queue = asyncio.Queue(maxsize=32)
        self._resampler = None
        self._queued_samples = 0
        self._preroll = deque()
        self._preroll_samples = 0
        self._input_started = False
        self._pending = None
        self._response = None
        self._lease = None
        self._client = self._connection = self._wire = None
        self._receiver = self._timer = None
        self._connection_entered = False
        self._worker_started = False
        self._final_usage_identity = None
        self._activity = False
        self._commit = False
        self._failed = self._closed = False
        self._failure = None
        self._abort_requested = False
        self._pending_tools = {}
        self._seen_tools = {}
        self._cancelled_tools = set()
        self._connection_id = None
        self._sequence = 0
        self._usage_sequence = 0
        self._turn_done = asyncio.Event()
        self._round_usage_done = asyncio.Event()
        self._event_sequence = 0
        self._last_output_sequence = 0
        self._soft_stop_complete = False
        self._finalized = asyncio.Event()
        self._worker = asyncio.create_task(self._run(), name="jarvis-controlled-live")

    @property
    def connection_idle(self):
        return (
            not self._failed
            and not self._closed
            and self._failure is None
            and self._wire is None
            and self._lease is None
            and self._response is None
            and not self._pending_tools
        )

    async def wait_for_finalization(self):
        """Wait for this physical connection's terminal ledger/teardown boundary."""
        await self._finalized.wait()

    def take_pending_audio(self):
        """Transfer only the bounded current, not-yet-dispatched input to Free."""
        frames, retained = [], []
        while not self._queue.empty():
            kind, value = self._queue.get_nowait()
            if kind == "audio":
                frames.append(value)
                self._queued_samples -= value.samples_per_channel
            else:
                retained.append((kind, value))
        for command in retained:
            self._queue.put_nowait(command)
        return tuple(frames)

    @property
    def idle(self):
        return (
            not self._failed
            and not self._closed
            and self._wire is None
            and self._lease is None
            and self._pending is None
            and self._response is None
            and not self._input_started
            and not self._pending_tools
            and self._queue.empty()
        )

    @property
    def chat_ctx(self):
        return self._ctx.copy()

    @property
    def tools(self):
        return self._tools

    async def _check(self):
        if self._closed or self._failed or self._failure is not None:
            raise llm.RealtimeError("Controlled Live session unavailable")
        await self.model.state.require_context()
        await self.model.admission.require_authority()
        if self._closed or self._failed or self._failure is not None:
            raise llm.RealtimeError("Controlled Live session unavailable")

    async def update_instructions(self, instructions):
        await self._check()
        self._instructions = instructions

    async def update_chat_ctx(self, chat_ctx):
        await self._check()
        for item in chat_ctx.items:
            if item.type == "function_call_output":
                expected = self._pending_tools.get(item.call_id)
                if (
                    expected is None
                    or item.name != expected.name
                    or item.call_id in self._cancelled_tools
                ):
                    # Existing completed receipts can remain in the local projection,
                    # but they must never be sent again as a live tool response.
                    old = self._ctx.get_by_id(item.id)
                    if old is None or old != item:
                        raise llm.RealtimeError("Unowned controlled Live tool result")
        self._ctx = chat_ctx.copy()

    async def update_tools(self, tools):
        await self._check()
        context = llm.ToolContext(tools)
        if context.provider_tools:
            raise llm.RealtimeError("Unbounded provider tools are unavailable")
        self._tools = context

    def update_options(self, *, tool_choice=NOT_GIVEN):
        if is_given(tool_choice) and tool_choice not in (None, "auto"):
            raise llm.RealtimeError("Per-response tool choice is unsupported")

    def _enqueue(self, kind, value=None):
        if self._closed or self._failed:
            return False
        try:
            self._queue.put_nowait((kind, value))
            return True
        except asyncio.QueueFull:
            self._stop("Controlled Live input queue exceeded")
            return False

    def _stop(self, reason):
        if self._closed or self._failed:
            return
        if self._failure is None:
            self._failure = llm.RealtimeError(reason)
        if self._abort_requested:
            return
        self._abort_requested = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queued_samples = 0
        self._queue.put_nowait(("abort", None))
        if (
            self._worker_started
            and not self._worker.done()
            and self._worker is not asyncio.current_task()
        ):
            self._worker.cancel()

    def start_user_activity(self):
        if self._input_started or self._closed or self._failed:
            return
        self._input_started = True
        self._enqueue("activity")
        while self._preroll:
            self._push_pcm(self._preroll.popleft())
        self._preroll_samples = 0

    def push_audio(self, frame):
        if (
            frame.sample_rate not in (16000, 48000)
            or frame.num_channels != 1
            or frame.samples_per_channel <= 0
        ):
            self._stop("Controlled Live requires owner mono PCM16")
            return
        if frame.sample_rate == 48000:
            if self._resampler is None:
                self._resampler = rtc.AudioResampler(
                    input_rate=48000, output_rate=16000, num_channels=1
                )
            frames = self._resampler.push(frame)
        else:
            if self._resampler is not None:
                self._stop("Controlled Live input format changed during a turn")
                return
            frames = [frame]
        for item in frames:
            self._push_pcm(item)

    def _push_pcm(self, frame):
        if not self._input_started:
            self._preroll.append(frame)
            self._preroll_samples += frame.samples_per_channel
            while self._preroll_samples > 2560:
                self._preroll_samples -= self._preroll.popleft().samples_per_channel
            return
        if self._queued_samples + frame.samples_per_channel > 2560:
            self._stop("Controlled Live160ms input queue exceeded")
            return
        if self._enqueue("audio", frame):
            self._queued_samples += frame.samples_per_channel

    def push_video(self, frame):
        raise llm.RealtimeError("Paid Live video has no admitted exposure")

    def commit_audio(self):
        if self._resampler is not None:
            for frame in self._resampler.flush():
                self._push_pcm(frame)
            self._resampler = None
        self._input_started = False
        self._commit = True

    def generate_reply(
        self, *, instructions=NOT_GIVEN, tool_choice=NOT_GIVEN, tools=NOT_GIVEN
    ):
        future = asyncio.get_running_loop().create_future()
        if (
            self._closed
            or self._failed
            or self._failure
            or self._pending is not None
            or (self._response is not None and not self._response.closed)
        ):
            future.set_exception(
                llm.RealtimeError(
                    "Controlled Live response unavailable or already active"
                )
            )
            return future
        if (
            (self.model.operational and is_given(instructions))
            or (
                is_given(instructions)
                and (not isinstance(instructions, str) or len(instructions) > 65536)
            )
            or is_given(tools)
            or (is_given(tool_choice) and tool_choice not in (None, "auto"))
        ):
            future.set_exception(
                llm.RealtimeError("Unqualified per-response configuration")
            )
            return future
        self._pending = future

        def cancelled(result):
            if result.cancelled() and not self._closed and not self._failed:
                self._stop("Controlled Live generation cancelled")

        future.add_done_callback(cancelled)
        if not self._enqueue("generate", instructions):
            self._pending = None
            future.set_exception(
                llm.RealtimeError("Controlled Live response unavailable")
            )
        return future

    def clear_audio(self):
        # A manual stream has no provider-side removable PCM buffer. Closing the
        # bounded physical connection is the only proven cancellation boundary.
        self._stop("Controlled Live audio cleared")

    def interrupt(self):
        # AgentSession cancels the completed generation before requesting a
        # blocking-tool reply. There is no active output to cancel in that state.
        if self._pending_tools and (self._response is None or self._response.closed):
            return
        self._stop("Controlled Live response interrupted")

    def truncate(self, **kwargs):
        self.interrupt()

    def _config(self):
        declarations = self._tools.parse_function_tools(
            format="google", tool_behavior="BLOCKING"
        )
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            history_config=types.HistoryConfig(initial_history_in_client_content=True),
            generation_config=types.GenerationConfig(
                max_output_tokens=self.model.controls.output_token_limit
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=True
                )
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.model.voice
                    )
                )
            ),
            system_instruction=self._instructions or None,
            tools=[types.Tool(function_declarations=declarations)]
            if declarations
            else None,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def _admit(self):
        await self._check()
        self._sequence += 1
        self._turn_done.clear()
        self._final_usage_identity = None
        if self.model.operational:
            from jarvis.voice.gemini_live_budget_session import create_connection_budget

            self._round_usage_done.clear()
            first = self._lease is None
            if first:
                self._lease = create_connection_budget(
                    self.model.admission,
                    connection_id=self._connection_id,
                    target=self.model.target,
                )
            await self._lease.reserve_round(str(self._sequence))
            await self._lease.before_send(
                "setup" if first else "tool",
                str(self._sequence),
                tool_call_ids=() if first else tuple(self._pending_tools),
            )
            await self._check()
            return
        self._lease = await self.model.admission.reserve(
            self.model.target,
            connection_id=self._connection_id,
            trigger_id=str(self._sequence),
            exposure=self.model.admission.contract.exposure(
                self.model.admission.session_id
            ),
        )
        await self._check()
        await self._lease.mark_dispatched()
        await self._check()

    async def _open(self):
        if self.model.operational and self._wire is None:
            async with asyncio.timeout(self.model.controls.setup_timeout_seconds):
                await self._open_impl()
        else:
            await self._open_impl()

    async def _open_impl(self):
        if self._wire is not None:
            return
        if self.model.state.before_demand is not None:
            allowed = self.model.state.before_demand(self)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if allowed is not True:
                raise llm.RealtimeError("Original demand transferred to another target")
            await self._check()
        self._connection_id = "live-connection-" + uuid4().hex
        self._finalized.clear()
        lifetime = self.model.controls.max_physical_seconds
        # Reserve three bounded cleanup operations inside the physical envelope.
        # The watchdog starts before admission/setup, not after the first send.
        self._close_grace = min(1.0, lifetime / 10)
        self._timer = asyncio.get_running_loop().call_later(
            lifetime - 3 * self._close_grace,
            self._stop,
            "Controlled Live absolute physical lifetime exceeded",
        )
        await self._admit()
        self._client = self.model.client_factory()
        await self._check()
        self._connection = self._client.aio.live.connect(
            model=self.model.model, config=self._config()
        )
        self._wire = await self._connection.__aenter__()
        self._connection_entered = True
        await self._check()
        # Only text from accepted canonical projection; no historical raw tool
        # results, media or resumable handles are replayed into another project.
        projection = self._ctx
        if self.model.state.context_for_replay is not None:
            projection = self.model.state.context_for_replay()
            if inspect.isawaitable(projection):
                projection = await projection
            await self._check()
            if not isinstance(projection, llm.ChatContext):
                raise llm.RealtimeError("Original canonical projection required")
        history = projection.copy(
            exclude_function_call=True,
            exclude_handoff=True,
            exclude_instructions=True,
            exclude_empty_message=True,
            exclude_config_update=True,
        )
        for message in history.messages():
            if any(not isinstance(part, str) for part in message.content):
                raise llm.RealtimeError(
                    "Controlled Live history must be canonical text"
                )
        turns, _ = history.to_provider_format(
            format="google", inject_dummy_user_message=False
        )
        await self._check()
        if self.model.operational:
            await self._lease.before_send("history", "history")
        await self._wire.send_client_content(turns=turns, turn_complete=True)
        self._receiver = asyncio.create_task(
            self._receive(), name="jarvis-controlled-live-receive"
        )

    async def _generate(self, instructions):
        await self._open()
        if self._pending_tools:
            if self._lease is not None:
                previous = self._lease.invocation_id
                # A fast local tool may finish before the server's final usage.
                # Receive remains concurrent; the serialized sender waits boundedly.
                await asyncio.wait_for(
                    self._turn_done.wait(),
                    timeout=self.model.controls.fast_tool_wait_seconds,
                )
                await self._end((previous, True))
            results = [
                item
                for item in self._ctx.items
                if item.type == "function_call_output"
                and item.call_id in self._pending_tools
            ]
            if {item.call_id for item in results} != set(self._pending_tools) or len(
                results
            ) != len(self._pending_tools):
                raise llm.RealtimeError("All matching blocking tool results required")
            await self._admit()
            responses = [
                types.FunctionResponse(
                    id=item.call_id,
                    name=item.name,
                    response={"error" if item.is_error else "output": item.output},
                )
                for item in results
            ]
            await self._check()
            await self._wire.send_tool_response(function_responses=responses)
            self._pending_tools.clear()
        elif self._activity:
            await self._check()
            if self.model.operational:
                await self._lease.validate_send()
            if is_given(instructions):
                await self._wire.send_client_content(
                    turns=[
                        types.Content(
                            role="model", parts=[types.Part(text=instructions)]
                        )
                    ],
                    turn_complete=False,
                )
                await self._check()
            await self._wire.send_realtime_input(activity_end=types.ActivityEnd())
            self._activity = False
        else:
            await self._check()
            if self.model.operational:
                await self._lease.before_send("initial", "initial")
            turns = (
                [types.Content(role="model", parts=[types.Part(text=instructions)])]
                if is_given(instructions)
                else []
            )
            await self._wire.send_client_content(turns=turns, turn_complete=True)
        self._commit = False

    async def _run(self):
        self._worker_started = True
        try:
            while not self._closed:
                kind, value = await self._queue.get()
                if self._failure or kind == "abort":
                    raise self._failure or llm.RealtimeError("Controlled Live aborted")
                await self._check()
                if kind == "activity":
                    if self._response is not None or self._pending_tools:
                        raise llm.RealtimeError(
                            "New speech cannot replay an unfinished Paid response"
                        )
                    await self._open()
                    if not self._activity:
                        if self.model.operational:
                            await self._lease.before_send("initial", "initial")
                        await self._wire.send_realtime_input(
                            activity_start=types.ActivityStart()
                        )
                        self._activity = True
                elif kind == "audio":
                    self._queued_samples -= value.samples_per_channel
                    if (
                        not self._activity
                        or self._lease is None
                        or not self._lease.allow_frame(
                            samples=value.samples_per_channel,
                            sample_rate=value.sample_rate,
                        )
                    ):
                        raise llm.RealtimeError(
                            "Controlled Live audio has no current permit"
                        )
                    await self._wire.send_realtime_input(
                        audio=types.Blob(
                            data=bytes(value.data), mime_type="audio/pcm;rate=16000"
                        )
                    )
                elif kind == "generate":
                    await self._generate(value)
                elif kind == "end":
                    await self._end(value)
        except asyncio.CancelledError:
            if self._failure is not None and not self._closed:
                await self._fail(self._failure)
            else:
                raise
        except Exception as exc:  # noqa: BLE001 - terminal public transport boundary
            await self._fail(exc)
        finally:
            await self._disconnect()

    async def _can_release(self):
        try:
            await self._check()
        except Exception:  # noqa: BLE001 - source errors must deny queued disclosure
            self._stop("Controlled Live queued source is no longer current")
            return False
        return (
            self.model.state.current
            and self.model.state.ready
            and not self._failure
            and not self._failed
            and not self._closed
        )

    def _start_response(self):
        if self._response is not None:
            return self._response
        if self._pending is None or self._pending.done() or self._lease is None:
            raise llm.RealtimeError("Unadmitted provider generation")
        self._response = LiveResponse(current=self._can_release)
        self._pending.set_result(self._response.event)
        self._pending = None
        self.emit("generation_created", self._response.event)
        return self._response

    def _transcription(self, response, content=None, *, final=False):
        if content and content.input_transcription:
            item = content.input_transcription
            response.transcript += item.text or ""
            final = final or item.finished is True
        if response.transcript and not response.final_transcript:
            response.final_transcript = final
            if final and self._ctx.get_by_id(response.input_id) is None:
                self._ctx.add_message(
                    role="user",
                    content=response.transcript,
                    id=response.input_id,
                    created_at=response.started_at,
                )
            self.emit(
                "input_audio_transcription_completed",
                llm.InputTranscriptionCompleted(
                    item_id=response.input_id,
                    transcript=response.transcript,
                    is_final=final,
                    turn_started_at=response.started_at,
                ),
            )

    async def _receive(self):
        try:
            while self._wire is not None:
                async for event in self._wire.receive():
                    # Usage is accounted before any release filtering. Old transports
                    # cannot discard a charge merely because their epoch was retired.
                    self._event_sequence += 1
                    content = event.server_content
                    has_output = event.tool_call is not None or (
                        content is not None
                        and (
                            content.model_turn is not None
                            or content.input_transcription is not None
                            or content.output_transcription is not None
                        )
                    )
                    if has_output:
                        self._last_output_sequence = self._event_sequence
                    if event.usage_metadata is not None and self._lease is not None:
                        self._usage_sequence += 1
                        if self.model.operational:
                            post = (
                                self.model.admission.profile is not None
                                and self.model.admission.profile.terminal_mode
                                == "post_turn_complete"
                                and self._turn_done.is_set()
                            )
                            observation = await self._lease.observe(
                                str(self._usage_sequence),
                                event.usage_metadata,
                                sequence=self._event_sequence,
                                turn_complete=bool(
                                    (content and content.turn_complete) or post
                                ),
                                last_output_sequence=self._last_output_sequence,
                            )
                            if self._lease.round_complete:
                                self._round_usage_done.set()
                            if self._lease.stopped:
                                self._soft_stop_complete = bool(
                                    self._lease.round_complete
                                    and observation is not None
                                    and observation.unknown_reason is None
                                    and not self._pending_tools
                                    and event.tool_call is None
                                )
                                self._stop("Controlled Live operational budget stop")
                                return
                        else:
                            self._lease.observe(
                                str(self._usage_sequence), event.usage_metadata
                            )
                    await self._check()
                    if event.go_away is not None:
                        raise llm.RealtimeError(
                            "Controlled Live GoAway requires a new admitted operation"
                        )
                    if event.tool_call_cancellation is not None:
                        self._cancelled_tools.update(
                            event.tool_call_cancellation.ids or []
                        )
                        raise llm.RealtimeError("Controlled Live tool call cancelled")
                    if event.server_content is None and event.tool_call is None:
                        continue
                    response = self._start_response()
                    if event.server_content is not None:
                        response.content(event.server_content)
                        self._transcription(response, event.server_content)
                    if event.tool_call is not None:
                        for call in event.tool_call.function_calls or []:
                            if (
                                not call.id
                                or not call.name
                                or call.name not in self._tools.function_tools
                            ):
                                raise llm.RealtimeError(
                                    "Unowned controlled Live tool call"
                                )
                            function = llm.FunctionCall(
                                call_id=call.id,
                                name=call.name,
                                arguments=json.dumps(call.args or {}, sort_keys=True),
                            )
                            prior = self._seen_tools.get(call.id)
                            if prior is not None:
                                if (
                                    prior != (function.name, function.arguments)
                                    or call.id not in self._pending_tools
                                ):
                                    raise llm.RealtimeError(
                                        "Conflicting or completed controlled Live tool call"
                                    )
                                continue
                            if len(self._seen_tools) >= 256:
                                raise llm.RealtimeError(
                                    "Controlled Live tool identity bound exceeded"
                                )
                            self._seen_tools[call.id] = (
                                function.name,
                                function.arguments,
                            )
                            self._pending_tools[call.id] = function
                            response.functions.send_nowait(function)
                        # Let the public AgentSession execute its original guarded tools.
                        # Only a separately admitted matching result can resume the model.
                        response.close()
                    content = event.server_content
                    if content and content.interrupted:
                        raise llm.RealtimeError("Controlled Live provider interrupted")
                    if content and content.turn_complete:
                        self._transcription(response, final=True)
                        response.close()
                        self._turn_done.set()
                        self._final_usage_identity = (
                            self._lease.invocation_id
                            if event.usage_metadata is not None
                            else None
                        )
                        self._enqueue(
                            "end",
                            (
                                self._lease.invocation_id,
                                event.usage_metadata is not None,
                            ),
                        )
                if not self._pending_tools and not self.model.operational:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed without provider retries
            if self._failure is None:
                self._failure = exc
            self._stop("Controlled Live receive failed")

    async def _end(self, outcome):
        identity, complete = outcome
        if self._lease is None or self._lease.invocation_id != identity:
            return
        if self.model.operational:
            # Keep receive alive during a profile-supported terminal metadata window.
            await asyncio.wait_for(
                self._round_usage_done.wait(),
                timeout=self.model.controls.final_usage_wait_seconds,
            )
            complete = self._lease.round_complete
        else:
            complete = complete and self._final_usage_identity == identity
        if (
            self._response is not None
            and self._response.output_text
            and self._ctx.get_by_id(self._response.response_id) is None
        ):
            self._ctx.add_message(
                role="assistant",
                content=self._response.output_text,
                id=self._response.response_id,
            )
        self._response = None
        if self._pending_tools:
            if self.model.operational:
                await self._lease.finish_round(self._lease.round_id, complete=complete)
            else:
                await self._lease.finish(complete=complete)
                self._lease = None
        else:
            # Final usage cannot release exposure before bounded socket teardown.
            await self._disconnect(complete=complete)

    async def _disconnect(self, *, complete=False):
        receiver, self._receiver = self._receiver, None
        if receiver is not None and receiver is not asyncio.current_task():
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        connection, self._connection = self._connection, None
        entered, self._connection_entered = self._connection_entered, False
        wire, self._wire = self._wire, None
        client, self._client = self._client, None
        grace = getattr(self, "_close_grace", 1.0)
        closed = False
        try:
            if wire is not None:
                await asyncio.wait_for(wire.close(), timeout=grace)
            if entered and connection is not None:
                await asyncio.wait_for(
                    connection.__aexit__(None, None, None), timeout=grace
                )
            if client is not None:
                await asyncio.wait_for(client.aio.aclose(), timeout=grace)
            closed = True
        finally:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._lease is not None:
                lease, self._lease = self._lease, None
                if self.model.operational:
                    await lease.close(
                        teardown_confirmed=closed,
                        complete=bool(
                            (complete and not self._failure) or self._soft_stop_complete
                        ),
                    )
                elif lease.reservation.state == "reserved":
                    await lease.cancel_unsent()
                else:
                    await lease.finish(
                        complete=bool(complete and closed and not self._failure)
                    )
        self._activity = self._commit = self._input_started = False
        self._finalized.set()
        self._preroll.clear()
        self._preroll_samples = 0
        if (
            self.idle
            and self.model.state.current
            and self.model.state.on_idle is not None
        ):
            self.model.state.on_idle()

    async def _fail(self, error):
        self._failed = True
        pending, self._pending = self._pending, None
        if self._response is not None:
            self._response.close()
        try:
            await self._disconnect()
        finally:
            if pending is not None and not pending.done():
                pending.set_exception(
                    llm.RealtimeError("Controlled Live response unavailable")
                )
        if self.model.state.current:
            self.emit(
                "error",
                llm.RealtimeModelError(
                    timestamp=time.time(),
                    label=self.model.label,
                    error=sanitized_live_error(error),
                    recoverable=False,
                ),
            )

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(llm.RealtimeError("Controlled Live closed"))
        self._pending = None
        if self._response is not None:
            self._response.close()
        await self._disconnect()
