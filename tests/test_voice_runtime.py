from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from livekit import rtc
from livekit.agents import (
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    RunContext,
    UserInputTranscribedEvent,
    llm,
)
from livekit.agents.llm import ChatMessage

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession, ConversationStatus
from jarvis.identity.speaker_turn import InMemorySpeakerTurnCapture
from jarvis.memory.live_context import LiveContext
from jarvis.voice.audio import LocalAudioOutput
from jarvis.voice.livekit_session import LiveKitConversationBridge
from jarvis.voice.runtime import VoiceRuntimeController, VoiceRuntimeState


class FakeSessionInput:
    def __init__(self) -> None:
        self.audio = None
        self.audio_enabled = True

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = enabled


class FakeSessionOutput:
    def __init__(self) -> None:
        self.audio = None
        self.audio_enabled = True

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = enabled


class FakeSession:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.handlers: dict[str, list] = defaultdict(list)
        self.input = FakeSessionInput()
        self.output = FakeSessionOutput()
        self.started = asyncio.Event()
        self.closed = False
        self.start_error = start_error
        self.interrupt_calls: list[bool] = []
        self.agent: Any | None = None
        self._global_run_state = None

    def on(self, event: str, callback):
        self.handlers[event].append(callback)
        return callback

    def emit(self, event: str, value: Any) -> None:
        for callback in tuple(self.handlers[event]):
            callback(value)

    async def start(self, *, agent: Any) -> None:
        self.agent = agent
        self.started.set()
        if self.start_error is not None:
            raise self.start_error

    def interrupt(self, *, force: bool = False) -> asyncio.Future[None]:
        self.interrupt_calls.append(force)
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def aclose(self) -> None:
        self.closed = True
        self.emit("close", CloseEvent(reason=CloseReason.USER_INITIATED))


class FakeAudio:
    def __init__(self) -> None:
        self.output = LocalAudioOutput(output_device=None)
        self.activated = False
        self.deactivated = False

    def activate_session(self, session_input) -> None:
        del session_input
        self.activated = True

    def deactivate_session(self) -> None:
        self.deactivated = True


class FakeScriptedSpeech:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.spoken: list[str] = []
        self.max_provider_retries: list[int | None] = []
        self.closed = False

    async def speak(
        self,
        output: LocalAudioOutput,
        text: str,
        *,
        max_provider_retries: int | None = None,
    ) -> None:
        del output
        self.spoken.append(text)
        self.max_provider_retries.append(max_provider_retries)
        self.started.set()
        await self.release.wait()

    async def aclose(self) -> None:
        self.closed = True


class FakeLocalStatusSpeech:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.spoken: list[str] = []
        self.started = asyncio.Event()

    async def speak(self, output: LocalAudioOutput, text: str) -> None:
        del output
        self.spoken.append(text)
        self.started.set()
        if self.error is not None:
            raise self.error


def _bridge(
    session: FakeSession,
    conversation: ConversationSession,
) -> LiveKitConversationBridge:
    return LiveKitConversationBridge(
        session,  # type: ignore[arg-type]
        conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )


def runtime_with_session(
    *,
    initial_timeout: float = 1,
    start_error: Exception | None = None,
) -> tuple[
    VoiceRuntimeController,
    FakeSession,
    ConversationSession,
    FakeAudio,
    FakeScriptedSpeech,
]:
    session = FakeSession(start_error=start_error)
    conversation = ConversationSession()
    bridge = _bridge(session, conversation)
    audio = FakeAudio()
    scripted_speech = FakeScriptedSpeech()
    config = JarvisConfig(initial_request_timeout_seconds=initial_timeout)
    runtime = VoiceRuntimeController(
        config,
        audio,  # type: ignore[arg-type]
        session_factory=lambda _: (session, bridge),  # type: ignore[arg-type,return-value]
        scripted_speech=scripted_speech,
    )
    return runtime, session, conversation, audio, scripted_speech


@pytest.mark.asyncio
async def test_startup_greeting_waits_for_tracking_readiness() -> None:
    import threading

    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()
            self.started = asyncio.Event()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            self.started.set()

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    readiness = threading.Event()
    calls: list[float] = []

    def wait_for_ready(timeout_seconds: float) -> bool:
        calls.append(timeout_seconds)
        return readiness.wait(timeout_seconds)

    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        startup_readiness_waiter=wait_for_ready,
        startup_readiness_timeout_seconds=1.0,
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(audio.started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    assert scripted_speech.started.is_set() is False

    readiness.set()
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)
    assert calls == [1.0]

    scripted_speech.release.set()
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_dev_control_connects_before_audio_start_and_marks_ready_after_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.dev_control import DevControlClient

    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class FakeDevControl:
        def __init__(self) -> None:
            self.connected = asyncio.Event()
            self.ready = asyncio.Event()

        async def run(self, *, approval_handler, shutdown_handler) -> None:
            del approval_handler, shutdown_handler
            self.connected.set()
            await asyncio.Event().wait()

        def mark_ready(self) -> None:
            assert audio.started is True
            self.ready.set()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()
            self.started = False

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            await asyncio.wait_for(control.connected.wait(), timeout=1)
            self.started = True

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    control = FakeDevControl()
    audio = StartupAudio()
    monkeypatch.setattr(
        DevControlClient,
        "from_environment",
        classmethod(lambda cls: control),
    )
    runtime = VoiceRuntimeController(
        JarvisConfig(startup_greeting_enabled=False),
        audio,  # type: ignore[arg-type]
    )

    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(control.ready.wait(), timeout=1)
    assert control.connected.is_set() is True
    assert audio.started is True

    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_startup_readiness_timeout_skips_greeting() -> None:
    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            return None

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        startup_readiness_waiter=lambda _timeout: False,
        startup_readiness_timeout_seconds=0.01,
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.05)
    assert scripted_speech.started.is_set() is False
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_startup_greeting_prefers_primary_cloud_lifecycle_speech() -> None:
    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            return None

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    local_speech = FakeLocalStatusSpeech()
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        local_status_speech=local_speech,  # type: ignore[arg-type]
        startup_greeting_factory=lambda: "Good evening, sir.",
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)

    assert scripted_speech.spoken == ["Good evening, sir."]
    assert scripted_speech.max_provider_retries == [0]
    assert local_speech.spoken == []

    scripted_speech.release.set()
    await asyncio.sleep(0)
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_lifecycle_speech_falls_back_locally_after_one_cloud_attempt() -> None:
    class FailingScriptedSpeech(FakeScriptedSpeech):
        async def speak(
            self,
            output: LocalAudioOutput,
            text: str,
            *,
            max_provider_retries: int | None = None,
        ) -> None:
            del output
            self.spoken.append(text)
            self.max_provider_retries.append(max_provider_retries)
            self.started.set()
            raise RuntimeError("cloud failed")

    runtime, _, _, audio, _ = runtime_with_session()
    scripted_speech = FailingScriptedSpeech()
    local_speech = FakeLocalStatusSpeech()
    runtime._scripted_speech = scripted_speech  # type: ignore[attr-defined]
    runtime._local_status_speech = local_speech  # type: ignore[attr-defined]

    assert (
        await runtime._speak_lifecycle_message(
            audio.output,
            "Lifecycle message.",
            label="test lifecycle",
        )
        is True
    )

    assert scripted_speech.spoken == ["Lifecycle message."]
    assert scripted_speech.max_provider_retries == [0]
    assert local_speech.spoken == ["Lifecycle message."]


@pytest.mark.asyncio
async def test_standby_closes_when_local_and_cloud_speech_fail() -> None:
    class FailingScriptedSpeech(FakeScriptedSpeech):
        async def speak(
            self,
            output: LocalAudioOutput,
            text: str,
            *,
            max_provider_retries: int | None = None,
        ) -> None:
            del output
            self.spoken.append(text)
            self.max_provider_retries.append(max_provider_retries)
            self.started.set()
            raise RuntimeError("cloud failed")

    session = FakeSession()
    conversation = ConversationSession()
    bridge = _bridge(session, conversation)
    audio = FakeAudio()
    scripted_speech = FailingScriptedSpeech()
    local_speech = FakeLocalStatusSpeech(error=RuntimeError("local failed"))
    runtime = VoiceRuntimeController(
        JarvisConfig(initial_request_timeout_seconds=1),
        audio,  # type: ignore[arg-type]
        session_factory=lambda _: (session, bridge),  # type: ignore[arg-type,return-value]
        scripted_speech=scripted_speech,
        local_status_speech=local_speech,  # type: ignore[arg-type]
    )

    task = asyncio.create_task(runtime._run_one_session())
    await session.started.wait()
    assert session.agent is not None

    tool_ctx = llm.ToolContext(session.agent.tools)
    function_call = llm.FunctionCall(
        name="enter_standby",
        arguments="{}",
        call_id="standby-failure-test",
    )
    call_ctx = RunContext(
        session=session,  # type: ignore[arg-type]
        speech_handle=SimpleNamespace(num_steps=1),  # type: ignore[arg-type]
        function_call=function_call,
    )
    result = await llm.execute_function_call(
        llm.FunctionToolCall(
            name="enter_standby",
            arguments="{}",
            call_id="standby-failure-test",
        ),
        tool_ctx,
        call_ctx=call_ctx,
    )

    assert result.raw_exception is None
    await asyncio.wait_for(task, timeout=1)

    assert local_speech.spoken == ["Of course. I'll be standing by if you need me."]
    assert scripted_speech.spoken == ["Of course. I'll be standing by if you need me."]
    assert scripted_speech.max_provider_retries == [0]
    assert session.closed is True
    assert conversation.status is ConversationStatus.CLOSED


@pytest.mark.asyncio
async def test_semantic_standby_speaks_ack_before_session_cleanup() -> None:
    runtime, session, conversation, audio, scripted_speech = runtime_with_session()
    task = asyncio.create_task(runtime._run_one_session())
    await session.started.wait()
    assert runtime.state is VoiceRuntimeState.ACTIVE
    assert session.agent is not None

    tool_ctx = llm.ToolContext(session.agent.tools)
    assert tool_ctx.get_function_tool("enter_standby") is not None
    function_call = llm.FunctionCall(
        name="enter_standby",
        arguments="{}",
        call_id="standby-test",
    )
    call_ctx = RunContext(
        session=session,  # type: ignore[arg-type]
        speech_handle=SimpleNamespace(num_steps=1),  # type: ignore[arg-type]
        function_call=function_call,
    )
    result = await llm.execute_function_call(
        llm.FunctionToolCall(
            name="enter_standby",
            arguments="{}",
            call_id="standby-test",
        ),
        tool_ctx,
        call_ctx=call_ctx,
    )
    assert result.raw_exception is None
    assert result.raw_output is None
    assert session.input.audio_enabled is False
    assert session.output.audio_enabled is False
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)

    assert scripted_speech.spoken == ["Of course. I'll be standing by if you need me."]
    assert session.interrupt_calls == [True]
    assert task.done() is False
    assert session.closed is False
    assert audio.deactivated is False

    scripted_speech.release.set()
    await asyncio.wait_for(task, timeout=1)

    assert audio.activated is True
    assert audio.deactivated is True
    assert session.closed is True
    assert conversation.status is ConversationStatus.CLOSED


@pytest.mark.asyncio
async def test_initial_timeout_ends_session_without_provider_activity() -> None:
    runtime, session, _, audio, _ = runtime_with_session(initial_timeout=0.01)

    await asyncio.wait_for(runtime._run_one_session(), timeout=1)

    assert session.closed is True
    assert audio.deactivated is True


@pytest.mark.asyncio
async def test_provider_start_failure_marks_conversation_failed_and_cleans_up() -> None:
    runtime, session, conversation, audio, _ = runtime_with_session(
        start_error=RuntimeError("provider unavailable")
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await runtime._run_one_session()

    assert session.closed is True
    assert audio.deactivated is True
    assert conversation.status is ConversationStatus.FAILED


@pytest.mark.asyncio
async def test_speaker_shadow_submits_only_after_committed_user_item() -> None:
    session = FakeSession()
    conversation = ConversationSession()
    bridge = _bridge(session, conversation)
    audio = FakeAudio()
    config = JarvisConfig(
        speaker_shadow_enabled=True,
        initial_request_timeout_seconds=1,
    )
    runtime = VoiceRuntimeController(
        config,
        audio,  # type: ignore[arg-type]
        session_factory=lambda _: (session, bridge),  # type: ignore[arg-type,return-value]
    )
    submitted = asyncio.Event()
    observed_turns = []

    async def inspect_shadow_turn(turn, *, audio_turn_id: str) -> None:
        del audio_turn_id
        observed_turns.append(turn)
        submitted.set()

    runtime._inspect_shadow_turn = inspect_shadow_turn  # type: ignore[method-assign]
    task = asyncio.create_task(runtime._run_one_session())
    await session.started.wait()

    frame_samples = 1_000
    samples = np.full(frame_samples, 100, dtype=np.int16)
    assert session.input.audio.push_frame(
        rtc.AudioFrame(
            data=samples.tobytes(),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=frame_samples,
        )
    )

    session.emit("user_state_changed", SimpleNamespace(new_state="speaking"))
    session.emit("user_state_changed", SimpleNamespace(new_state="listening"))
    await asyncio.sleep(0)
    assert observed_turns == []

    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(id="user-1", role="user", content=["Can you hear me?"])
        ),
    )
    await asyncio.wait_for(submitted.wait(), timeout=1)

    assert len(observed_turns) == 1
    assert observed_turns[0].duration_seconds == pytest.approx(1.0)
    np.testing.assert_array_equal(observed_turns[0].samples, samples)

    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_active_speaker_shadow_uses_separate_paired_audio_window() -> None:
    session = FakeSession()
    conversation = ConversationSession()
    bridge = _bridge(session, conversation)
    audio = FakeAudio()
    config = JarvisConfig(
        speaker_shadow_enabled=True,
        initial_request_timeout_seconds=1,
    )
    paired_capture = InMemorySpeakerTurnCapture(max_turn_seconds=2.0)
    runtime = VoiceRuntimeController(
        config,
        audio,  # type: ignore[arg-type]
        session_factory=lambda _: (session, bridge),  # type: ignore[arg-type,return-value]
        active_speaker_audio_capture=paired_capture,
    )
    submitted = asyncio.Event()
    observed: list[tuple[object, object]] = []

    async def inspect_shadow_turn(
        turn,
        *,
        audio_turn_id: str,
        active_speaker_turn=None,
    ) -> None:
        del audio_turn_id
        observed.append((turn, active_speaker_turn))
        submitted.set()

    runtime._inspect_shadow_turn = inspect_shadow_turn  # type: ignore[method-assign]
    task = asyncio.create_task(runtime._run_one_session())
    await session.started.wait()

    canonical = np.full(1_000, 111, dtype=np.int16)
    paired = np.full(1_000, 222, dtype=np.int16)
    assert session.input.audio.push_frame(
        rtc.AudioFrame(
            data=canonical.tobytes(),
            sample_rate=1_000,
            num_channels=1,
            samples_per_channel=1_000,
        )
    )
    paired_capture.push_frame(
        paired.tobytes(),
        sample_rate=1_000,
        num_channels=1,
        samples_per_channel=1_000,
        observed_at_monotonic=50.0,
    )

    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(
                id="user-paired", role="user", content=["Testing paired audio"]
            )
        ),
    )
    await asyncio.wait_for(submitted.wait(), timeout=1)

    assert len(observed) == 1
    canonical_turn, paired_turn = observed[0]
    np.testing.assert_array_equal(canonical_turn.samples, canonical)
    assert paired_turn is not None
    np.testing.assert_array_equal(paired_turn.samples, paired)
    assert paired_turn.start_monotonic == pytest.approx(50.0)
    assert paired_turn.end_monotonic == pytest.approx(51.0)

    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_update_approval_uses_scripted_speech_then_real_spoken_yes() -> None:
    runtime, session, _, audio, scripted_speech = runtime_with_session()
    task = asyncio.create_task(runtime._run_update_approval_session("a" * 40, "b" * 40))
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)

    assert scripted_speech.spoken == [
        (
            "A JARVIS software update is available. Shall I install it and restart now? "
            "Please answer yes or no."
        )
    ]
    assert session.output.audio is None

    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(transcript="yes", is_final=True),
    )
    await asyncio.sleep(0)
    assert task.done() is False

    scripted_speech.release.set()
    await asyncio.sleep(0)
    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(transcript="yes", is_final=True),
    )

    assert await asyncio.wait_for(task, timeout=1) is True
    assert audio.activated is True
    assert audio.deactivated is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_startup_greeting_timeout_does_not_block_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            return None

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        startup_readiness_waiter=lambda _timeout: True,
    )
    monkeypatch.setattr(
        "jarvis.voice.runtime._LIFECYCLE_CLOUD_PRIMARY_TIMEOUT_SECONDS",
        0.01,
    )

    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)
    await asyncio.sleep(0.05)

    assert runtime.state is VoiceRuntimeState.IDLE

    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)
