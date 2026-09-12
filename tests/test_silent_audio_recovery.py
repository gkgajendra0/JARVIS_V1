from __future__ import annotations

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
    assert needs_scripted_recovery(
        quality(2, rms_dbfs=-66.2, peak_abs=112)
    ) is True


def test_recovery_threshold_rejects_normal_spoken_reply() -> None:
    assert needs_scripted_recovery(
        quality(2, rms_dbfs=-23.7, peak_abs=14_426)
    ) is False


def test_recovery_threshold_rejects_interrupted_audio() -> None:
    assert needs_scripted_recovery(
        quality(2, rms_dbfs=-70.0, peak_abs=50, interrupted=True)
    ) is False


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

    await recovery._recover_turn(  # noqa: SLF001
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

    await recovery._recover_turn(  # noqa: SLF001
        ConversationTurn(role=ConversationRole.ASSISTANT, text="Normal reply.")
    )

    assert speech.spoken == []
    assert speech.closed is False
