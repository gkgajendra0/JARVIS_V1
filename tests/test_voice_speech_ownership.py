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
        assert cooldown_seconds == 0
        self.resume_calls += 1
        self.detector.enable()


class FakeScriptedSpeech:
    def __init__(self, audio: FakeAudio) -> None:
        self._audio = audio
        self.spoken: list[str] = []
        self.started = asyncio.Event()
        self.detector_was_disabled = False

    async def speak(
        self,
        output,
        text: str,
        *,
        max_provider_retries: int | None = None,
    ) -> None:
        assert output is self._audio.output
        assert max_provider_retries == 0
        self.detector_was_disabled = not self._audio.detector.enabled
        self.spoken.append(text)
        self.started.set()

    async def aclose(self) -> None:
        return None


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
        raise AssertionError("successful scripted speech must not schedule a retry")


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
    speech = FakeScriptedSpeech(audio)
    work = FakeWorkRuntime(policy)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0),
        audio,  # type: ignore[arg-type]
        scripted_speech=speech,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )

    runtime._state = VoiceRuntimeState.ACTIVE
    runtime._live_session = object()

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.35)

    assert speech.spoken == []
    assert work.store.delivered is False
    assert audio.detector.disable_calls == 0

    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await asyncio.wait_for(speech.started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert speech.spoken == [
        (
            "Sir, I need your input on a background task. "
            "Please confirm the TV pairing request."
        )
    ]
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
    speech = FakeScriptedSpeech(audio)
    work = FakeWorkRuntime(DeliveryPolicy.WHEN_IDLE)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0),
        audio,  # type: ignore[arg-type]
        scripted_speech=speech,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await runtime._speech_ownership.acquire()
    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.1)

    assert speech.spoken == []
    assert work.store.delivered is False

    runtime._speech_ownership.release()
    await asyncio.wait_for(speech.started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert work.store.delivered is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)
