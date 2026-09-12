from __future__ import annotations

import asyncio

import pytest

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.voice.media_devices_audio import PlaybackQualitySnapshot
from jarvis.voice.silent_audio_recovery import (
    SilentRealtimeAudioRecovery,
    needs_scripted_recovery,
)


class FakeOutput:
    def __init__(self, quality: PlaybackQualitySnapshot | None = None) -> None:
        self.last_completed_quality = quality


class FakeSpeech:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.closed = False

    async def speak(self, output, text: str) -> None:
        del output
        self.spoken.append(text)

    async def aclose(self) -> None:
        self.closed = True


class BlockingSpeech(FakeSpeech):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def speak(self, output, text: str) -> None:
        del output
        self.spoken.append(text)
        self.started.set()
        await asyncio.Future()


def quality(
    sequence: int,
    *,
    rms_dbfs: float,
    peak_abs: int,
    interrupted: bool = False,
) -> PlaybackQualitySnapshot:
    return PlaybackQualitySnapshot(
        sequence=sequence,
        duration_seconds=1.0,
        peak_abs=peak_abs,
        rms_dbfs=rms_dbfs,
        interrupted=interrupted,
    )


def test_recovery_threshold_accepts_observed_silent_yes() -> None:
    assert needs_scripted_recovery(quality(2, rms_dbfs=-66.2, peak_abs=112)) is True


def test_recovery_threshold_rejects_normal_spoken_reply() -> None:
    assert needs_scripted_recovery(quality(2, rms_dbfs=-23.7, peak_abs=14_426)) is False


def test_recovery_threshold_rejects_interrupted_audio() -> None:
    assert (
        needs_scripted_recovery(
            quality(2, rms_dbfs=-70.0, peak_abs=50, interrupted=True)
        )
        is False
    )


@pytest.mark.asyncio
async def test_silent_assistant_turn_replays_exact_text_once() -> None:
    output = FakeOutput(quality(1, rms_dbfs=-20.0, peak_abs=10_000))
    speech = FakeSpeech()
    recovery = SilentRealtimeAudioRecovery(
        JarvisConfig(),
        output_getter=lambda: output,  # type: ignore[arg-type]
        speech_factory=lambda _: speech,
    )
    output.last_completed_quality = quality(2, rms_dbfs=-66.2, peak_abs=112)

    await recovery._recover_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Yes.")
    )

    assert speech.spoken == ["Yes."]
    assert speech.closed is True


@pytest.mark.asyncio
async def test_normal_assistant_turn_does_not_invoke_scripted_tts() -> None:
    output = FakeOutput(quality(1, rms_dbfs=-20.0, peak_abs=10_000))
    speech = FakeSpeech()
    recovery = SilentRealtimeAudioRecovery(
        JarvisConfig(),
        output_getter=lambda: output,  # type: ignore[arg-type]
        speech_factory=lambda _: speech,
    )
    output.last_completed_quality = quality(2, rms_dbfs=-23.7, peak_abs=14_426)

    await recovery._recover_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Normal reply.")
    )

    assert speech.spoken == []
    assert speech.closed is False


@pytest.mark.asyncio
async def test_interrupted_assistant_turn_never_replays_even_with_silent_quality() -> None:
    output = FakeOutput(quality(1, rms_dbfs=-20.0, peak_abs=10_000))
    speech = FakeSpeech()
    recovery = SilentRealtimeAudioRecovery(
        JarvisConfig(),
        output_getter=lambda: output,  # type: ignore[arg-type]
        speech_factory=lambda _: speech,
    )
    output.last_completed_quality = quality(2, rms_dbfs=-66.2, peak_abs=112)

    await recovery._recover_turn(
        ConversationTurn(
            role=ConversationRole.ASSISTANT,
            text="Interrupted reply.",
            interrupted=True,
        )
    )

    assert speech.spoken == []
    assert speech.closed is False


@pytest.mark.asyncio
async def test_scripted_replay_quality_is_consumed_before_the_next_assistant_turn() -> None:
    output = FakeOutput(quality(1, rms_dbfs=-20.0, peak_abs=10_000))

    class UpdatingSpeech(FakeSpeech):
        async def speak(self, playback_output, text: str) -> None:
            await super().speak(playback_output, text)
            output.last_completed_quality = quality(
                3,
                rms_dbfs=-22.0,
                peak_abs=12_000,
            )

    speech = UpdatingSpeech()
    recovery = SilentRealtimeAudioRecovery(
        JarvisConfig(),
        output_getter=lambda: output,  # type: ignore[arg-type]
        speech_factory=lambda _: speech,
    )
    output.last_completed_quality = quality(2, rms_dbfs=-66.2, peak_abs=112)

    await recovery._recover_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Yes.")
    )
    assert recovery._last_consumed_sequence == 3

    output.last_completed_quality = quality(4, rms_dbfs=-23.7, peak_abs=14_426)
    await recovery._recover_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Normal reply.")
    )

    assert speech.spoken == ["Yes."]


@pytest.mark.asyncio
async def test_close_cancels_inflight_recovery_and_closes_scripted_speech() -> None:
    output = FakeOutput(quality(1, rms_dbfs=-20.0, peak_abs=10_000))
    speech = BlockingSpeech()
    recovery = SilentRealtimeAudioRecovery(
        JarvisConfig(),
        output_getter=lambda: output,  # type: ignore[arg-type]
        speech_factory=lambda _: speech,
    )
    output.last_completed_quality = quality(2, rms_dbfs=-66.2, peak_abs=112)

    recovery.observe_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Yes.")
    )
    await asyncio.wait_for(speech.started.wait(), timeout=1.0)
    tasks = tuple(recovery._tasks)
    assert tasks

    recovery.close()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert speech.closed is True
    assert recovery._tasks == set()
