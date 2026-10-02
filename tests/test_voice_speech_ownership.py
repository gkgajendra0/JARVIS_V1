from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
    _owner_interaction_retry_seconds,
    _spoken_subject,
)
from jarvis.voice.runtime import VoiceRuntimeState
from jarvis.work.models import DeliveryPolicy, WorkDeliveryKind, WorkState


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


class FakeTimeoutRealtimeSpeech:
    async def speak(
        self,
        output,
        *,
        instructions: str,
        label: str,
    ) -> None:
        del output, instructions, label
        raise TimeoutError("playout completion timed out")


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
    def __init__(
        self,
        policy: DeliveryPolicy,
        *,
        work_state: WorkState = WorkState.WAITING_FOR_OWNER,
        kind: WorkDeliveryKind = WorkDeliveryKind.OWNER_INPUT,
        message: str = "Please confirm the TV pairing request.",
    ) -> None:
        self.work_state = work_state
        self.delivery = SimpleNamespace(
            delivery_id="delivery-tv-owner-input",
            work_id="work-tv-capability",
            kind=kind,
            policy=policy,
            message=message,
            failed_attempts=0,
        )
        self.delivered = False
        self.deferred = False
        self.retry: tuple[float, str] | None = None
        self.list_calls = 0

    def list_due_deliveries(self, *, limit: int = 5):
        assert limit == 5
        self.list_calls += 1
        return () if self.delivered or self.deferred else (self.delivery,)

    def require(self, work_id: str):
        assert work_id == self.delivery.work_id
        return SimpleNamespace(work_id=work_id, state=self.work_state)

    def mark_delivery_delivered(self, delivery_id: str) -> None:
        assert delivery_id == self.delivery.delivery_id
        self.delivered = True

    def schedule_delivery_retry(
        self,
        delivery_id: str,
        *,
        delay_seconds: float,
        reason: str,
    ):
        assert delivery_id == self.delivery.delivery_id
        self.deferred = True
        self.retry = (delay_seconds, reason)
        self.delivery.failed_attempts += 1
        return SimpleNamespace(failed_attempts=self.delivery.failed_attempts)


class FakeWorkRuntime:
    def __init__(
        self,
        policy: DeliveryPolicy,
        *,
        work_state: WorkState = WorkState.WAITING_FOR_OWNER,
        kind: WorkDeliveryKind = WorkDeliveryKind.OWNER_INPUT,
        message: str = "Please confirm the TV pairing request.",
    ) -> None:
        self.store = FakeStore(
            policy,
            work_state=work_state,
            kind=kind,
            message=message,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [DeliveryPolicy.WHEN_IDLE, DeliveryPolicy.INTERRUPT],
)
async def test_owner_input_waits_for_idle_then_opens_interactive_session(
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
    interaction_started = asyncio.Event()
    calls: list[tuple[str, str, bool]] = []

    async def interactive_owner_input(*, work_id: str, question: str) -> bool:
        calls.append((work_id, question, audio.detector.enabled))
        interaction_started.set()
        work.store.work_state = WorkState.RUNNING
        return True

    runtime._run_owner_input_interaction = interactive_owner_input  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.ACTIVE
    runtime._live_session = object()

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.35)

    assert calls == []
    assert work.store.delivered is False
    assert audio.detector.disable_calls == 0

    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await asyncio.wait_for(interaction_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert calls == [
        (
            "work-tv-capability",
            "Please confirm the TV pairing request.",
            False,
        )
    ]
    assert speech.instructions == []
    assert audio.detector.disable_calls == 1
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True
    assert work.store.delivered is True
    assert work.store.retry is None

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_owner_input_interaction_respects_shared_speech_lease() -> None:
    audio = FakeAudio()
    work = FakeWorkRuntime(DeliveryPolicy.WHEN_IDLE)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    interaction_started = asyncio.Event()

    async def interactive_owner_input(*, work_id: str, question: str) -> bool:
        del work_id, question
        interaction_started.set()
        work.store.work_state = WorkState.RUNNING
        return True

    runtime._run_owner_input_interaction = interactive_owner_input  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    await runtime._speech_ownership.acquire()
    delivery_task = asyncio.create_task(runtime._deliver_pending_work())
    await asyncio.sleep(0.1)

    assert not interaction_started.is_set()
    assert work.store.delivered is False

    runtime._speech_ownership.release()
    await asyncio.wait_for(interaction_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert work.store.delivered is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_unanswered_owner_input_stays_durable_and_retries() -> None:
    audio = FakeAudio()
    work = FakeWorkRuntime(DeliveryPolicy.WHEN_IDLE)
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )

    async def unanswered_owner_input(*, work_id: str, question: str) -> bool:
        del work_id, question
        return False

    runtime._run_owner_input_interaction = unanswered_owner_input  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())

    for _ in range(40):
        if work.store.retry is not None:
            break
        await asyncio.sleep(0.025)

    assert work.store.delivered is False
    assert work.store.retry is not None
    delay_seconds, reason = work.store.retry
    assert delay_seconds >= 30.0 * 60.0
    assert reason == "owner_input_unanswered"
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


def test_owner_interaction_retry_uses_long_exponential_backoff() -> None:
    assert _owner_interaction_retry_seconds(0) == pytest.approx(30.0 * 60.0)
    assert _owner_interaction_retry_seconds(1) == pytest.approx(60.0 * 60.0)
    assert _owner_interaction_retry_seconds(2) == pytest.approx(2.0 * 60.0 * 60.0)
    assert _owner_interaction_retry_seconds(3) == pytest.approx(4.0 * 60.0 * 60.0)
    assert _owner_interaction_retry_seconds(4) == pytest.approx(6.0 * 60.0 * 60.0)
    assert _owner_interaction_retry_seconds(99) == pytest.approx(6.0 * 60.0 * 60.0)


def test_spoken_subject_hides_internal_identifier_formatting() -> None:
    assert _spoken_subject("media_catalog.search") == "media catalog search"
    assert _spoken_subject("change_deadbeef") is None
    assert _spoken_subject("gate_deadbeef") is None


@pytest.mark.asyncio
async def test_noninteractive_critical_notification_falls_back_to_local_speech() -> (
    None
):
    audio = FakeAudio()
    work = FakeWorkRuntime(
        DeliveryPolicy.WHEN_IDLE,
        work_state=WorkState.FAILED,
        kind=WorkDeliveryKind.FAILURE,
        message="The capability build failed.",
    )
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
        "Sir, a background task failed. The capability build failed."
    ]
    assert work.store.delivered is True
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_obsolete_owner_input_notification_is_discarded_without_speaking() -> (
    None
):
    audio = FakeAudio()
    speech = FakeRealtimeSpeech(audio)
    work = FakeWorkRuntime(
        DeliveryPolicy.WHEN_IDLE,
        work_state=WorkState.FAILED,
    )
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    runtime._speak_ephemeral_realtime_message = speech.speak  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())

    for _ in range(20):
        if work.store.delivered:
            break
        await asyncio.sleep(0.025)

    assert work.store.delivered is True
    assert speech.instructions == []
    assert audio.detector.disable_calls == 0

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)


@pytest.mark.asyncio
async def test_timed_out_noncritical_notification_is_consumed_without_replay() -> None:
    audio = FakeAudio()
    work = FakeWorkRuntime(
        DeliveryPolicy.WHEN_IDLE,
        work_state=WorkState.COMPLETED,
        kind=WorkDeliveryKind.COMPLETION,
        message="Research-stage planning is complete.",
    )
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(wake_cooldown_seconds=0.01),
        audio,  # type: ignore[arg-type]
        work_runtime=work,  # type: ignore[arg-type]
    )
    timeout_speech = FakeTimeoutRealtimeSpeech()
    runtime._speak_ephemeral_realtime_message = timeout_speech.speak  # type: ignore[method-assign]
    runtime._state = VoiceRuntimeState.IDLE
    runtime._live_session = None

    delivery_task = asyncio.create_task(runtime._deliver_pending_work())

    for _ in range(40):
        if work.store.delivered:
            break
        await asyncio.sleep(0.025)

    assert work.store.delivered is True
    assert work.store.retry is None
    assert audio.resume_calls == 1
    assert audio.detector.enabled is True

    runtime.request_shutdown()
    await asyncio.wait_for(delivery_task, timeout=1)
