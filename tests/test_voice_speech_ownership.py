from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.runtime import VoiceRuntimeState
from jarvis.work.models import DeliveryPolicy, WorkDeliveryKind


class FakeDetector:
    def __init__(self) -> None:
        self.enabled = True
        self.disable_calls = 0
        self.enable_calls = 0

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.disable_calls += 1
        self.enabled = False

    def enable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer
        self.enable_calls += 1
        self.enabled = True


class FakeAudio:
    def __init__(self) -> None:
        self.detector = FakeDetector()
        self.output = object()
        self.resume_calls = 0

    async def resume_wake(self, *, cooldown_seconds: float) -> None:
        assert cooldown_seconds == pytest.approx(0.01)
        self.resume_calls += 1
        self.detector.enable()


class FakeRealtimeSpeech:
    def __init__(self, audio: FakeAudio) -> None:
        self._audio = audio
        self.instructions: list[str] = []
        self.labels: list[str] = []
        self.started = asyncio.Event()
        self.detector_was_disabled = False

    async def speak(
        self,
        output,
        *,
        instructions: str,
        label: str,
    ) -> None:
        assert output is self._audio.output
        self.detector_was_disabled = not self._audio.detector.enabled
        self.instructions.append(instructions)
        self.labels.append(label)
        self.started.set()


class FakeFailingRealtimeSpeech:
    async def speak(
        self,
        output,
        *,
        instructions: str,
        label: str,
    ) -> None:
        del output, instructions, label
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


class FakeLocalStatusSpeech:
    def __init__(self, audio: FakeAudio) -> None:
        self._audio = audio
        self.messages: list[str] = []
        self.spoken = asyncio.Event()

    async def speak(self, output, text: str) -> None:
        assert output is self._audio.output
        self.messages.append(text)
        self.spoken.set()


class FakeStore:
    def __init__(self, policy: DeliveryPolicy) -> None:
        self.delivery = SimpleNamespace(
            delivery_id="delivery-tv-owner-input",
            work_id="work-tv-capability",
            kind=WorkDeliveryKind.OWNER_INPUT,
            policy=policy,
            message="Please confirm the TV pairing request.",
            failed_attempts=0,
        )
        self.delivered = False
        self.list_calls = 0

    def list_due_deliveries(self, *, limit: int = 5):
        assert limit == 5
        self.list_calls += 1
        return () if self.delivered else (self.delivery,)

    def mark_delivery_delivered(self, delivery_id: str) -> None:
        assert delivery_id == self.delivery.delivery_id
        self.delivered = True

    def schedule_delivery_retry(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("successful realtime speech must not schedule a retry")


class FakeWorkRuntime:
    def __init__(self, policy: DeliveryPolicy) -> None:
        self.store = FakeStore(policy)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [DeliveryPolicy.WHEN_IDLE, DeliveryPolicy.INTERRUPT],
)
async def test_background_work_speech_waits_until_voice_session_is_idle(
    policy: DeliveryPolicy,
) -> None:
    audio = FakeAudio()
    speech = FakeRealtimeSpeech(audio)
    work = FakeWorkRuntime(policy)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    runtime._speak_ephemeral_realtime_message = speech.speak  # type: ignore[method-assign]

    runtime._state = VoiceRuntimeState.ACTIVE
    runtime._live_session = object()

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.35)

    assert speech.instructions == []
    assert work.store.delivered is False
    assert audio.detector.disable_calls == 0

    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await asyncio.wait_for(speech.started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert len(speech.instructions) == 1
    assert "Please confirm the TV pairing request." in speech.instructions[0]
    assert "one or two brief, natural sentences" in speech.instructions[0]
    assert speech.labels == ["background work notification"]
    assert speech.detector_was_disabled is True
    assert audio.detector.disable_calls == 1
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True
    assert work.store.delivered is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_background_work_speech_respects_shared_speech_lease() -> None:
    audio = FakeAudio()
    speech = FakeRealtimeSpeech(audio)
    work = FakeWorkRuntime(DeliveryPolicy.WHEN_IDLE)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    runtime._speak_ephemeral_realtime_message = speech.speak  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await runtime._speech_ownership.acquire()
    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.1)

    assert speech.instructions == []
    assert work.store.delivered is False

    runtime._speech_ownership.release()
    await asyncio.wait_for(speech.started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert work.store.delivered is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_critical_background_notification_falls_back_to_local_speech() -> None:
    audio = FakeAudio()
    work = FakeWorkRuntime(DeliveryPolicy.WHEN_IDLE)
    local = FakeLocalStatusSpeech(audio)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
        local_status_speech=local,  # type: ignore[arg-type]
    )
    failing = FakeFailingRealtimeSpeech()
    runtime._speak_ephemeral_realtime_message = failing.speak  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())

    await asyncio.wait_for(local.spoken.wait(), timeout=1)
    await asyncio.sleep(0)

    assert local.messages == [
        (
            "Sir, I need your input on a background task. "
            "Please confirm the TV pairing request."
        )
    ]
    assert work.store.delivered is True
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)
