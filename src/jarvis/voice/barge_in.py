"""Local barge-in gate for full-duplex realtime conversation.

Gemini Live 3.1 must retain its native activity/turn completion path with the
currently pinned LiveKit Google adapter. During JARVIS playback, however, even
small residual loudspeaker echo can make provider-side activity detection look
like user speech. This gate therefore sits on the already AEC-cleaned canonical
microphone stream and withholds audio only while JARVIS is speaking. A local
Silero VAD must confirm sustained speech before the buffered prefix and live
frames are released to the realtime provider.

The gate does not decide end-of-turn and never calls provider-specific commit or
generate APIs. Provider-native turn completion remains authoritative after a
real barge-in has been admitted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from livekit import rtc
from livekit.agents import inference, vad

from jarvis.voice.audio import DEVICE_SAMPLE_RATE, SessionAudioInput

LOGGER = logging.getLogger(__name__)

_BARGE_VAD_ACTIVATION_THRESHOLD = 0.60
_BARGE_VAD_MIN_SPEECH_SECONDS = 0.22
_BARGE_VAD_MIN_SILENCE_SECONDS = 0.20
_BARGE_VAD_PREFIX_PADDING_SECONDS = 0.20
_BARGE_BUFFER_SECONDS = 0.50


class _VADStream(Protocol):
    def push_frame(self, frame: rtc.AudioFrame) -> None: ...
    def flush(self) -> None: ...
    def __aiter__(self): ...
    async def aclose(self) -> None: ...


class _VADModel(Protocol):
    def stream(self) -> _VADStream: ...


class BargeInGatedSessionAudioInput(SessionAudioInput):
    """Suppress residual assistant echo while preserving real human barge-in."""

    def __init__(
        self,
        observer: Callable[[rtc.AudioFrame, float], None] | None = None,
        *,
        capacity_frames: int = 1_000,
        vad_model: _VADModel | None = None,
        buffer_seconds: float = _BARGE_BUFFER_SECONDS,
    ) -> None:
        super().__init__(capacity_frames=capacity_frames)
        if buffer_seconds <= 0:
            raise ValueError("barge-in buffer duration must be positive")
        self._observer = observer
        self._buffer_limit_samples = round(buffer_seconds * DEVICE_SAMPLE_RATE)
        self._buffer: deque[tuple[rtc.AudioFrame, float]] = deque()
        self._buffer_samples = 0
        self._agent_speaking = False
        self._gate_open = False
        self._closed_gate = False
        self._vad_model = vad_model or inference.VAD(
            model="silero",
            min_speech_duration=_BARGE_VAD_MIN_SPEECH_SECONDS,
            min_silence_duration=_BARGE_VAD_MIN_SILENCE_SECONDS,
            prefix_padding_duration=_BARGE_VAD_PREFIX_PADDING_SECONDS,
            max_buffered_speech=10.0,
            activation_threshold=_BARGE_VAD_ACTIVATION_THRESHOLD,
        )
        self._vad_stream = self._vad_model.stream()
        self._vad_task = asyncio.create_task(
            self._consume_vad(),
            name="jarvis-aec-clean-barge-in-vad",
        )

    @property
    def agent_speaking(self) -> bool:
        return self._agent_speaking

    @property
    def gate_open(self) -> bool:
        return self._gate_open

    @property
    def buffered_frames(self) -> int:
        return len(self._buffer)

    def set_agent_speaking(self, speaking: bool) -> None:
        """Update assistant playout state used to arm/disarm echo gating."""
        speaking = bool(speaking)
        if speaking == self._agent_speaking:
            return
        self._agent_speaking = speaking
        if speaking:
            if not self._gate_open:
                self._reset_closed_gate()
            return
        if not self._gate_open:
            self._reset_closed_gate()

    def push_frame(
        self,
        frame: rtc.AudioFrame,
        *,
        observed_at_monotonic: float | None = None,
    ) -> bool:
        if self._closed_gate:
            return False
        observed_at = (
            time.monotonic()
            if observed_at_monotonic is None
            else observed_at_monotonic
        )
        if observed_at < 0:
            raise ValueError("barge-in audio timestamp must be non-negative")

        # Once real speech has opened the gate, preserve the complete utterance
        # even if assistant playout stops before Silero publishes END_OF_SPEECH.
        if self._gate_open:
            self._vad_stream.push_frame(frame)
            return self._forward(frame, observed_at)

        # Outside assistant speech, provider-native activity detection receives
        # the canonical AEC-clean microphone without delay.
        if not self._agent_speaking:
            return self._forward(frame, observed_at)

        # During assistant speech, retain a bounded prefix and let Silero decide
        # whether this is real near-end speech or residual far-end echo.
        self._buffer.append((frame, observed_at))
        self._buffer_samples += frame.samples_per_channel
        while (
            self._buffer
            and self._buffer_samples - self._buffer[0][0].samples_per_channel
            >= self._buffer_limit_samples
        ):
            old_frame, _ = self._buffer.popleft()
            self._buffer_samples -= old_frame.samples_per_channel
        self._vad_stream.push_frame(frame)
        # Withheld echo is intentionally treated as accepted by the router; it
        # is not a session queue overflow.
        return True

    def close(self) -> None:
        if self._closed_gate:
            return
        self._closed_gate = True
        self._buffer.clear()
        self._buffer_samples = 0
        self._vad_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and not loop.is_closed():
            loop.create_task(self._vad_stream.aclose())
        super().close()

    async def _consume_vad(self) -> None:
        try:
            async for event in self._vad_stream:
                if event.type is vad.VADEventType.START_OF_SPEECH:
                    if self._agent_speaking and not self._gate_open:
                        self._gate_open = True
                        LOGGER.info(
                            "AEC-clean local Silero admitted real barge-in after %.2fs speech",
                            event.speech_duration,
                        )
                        self._release_buffer()
                    continue
                if event.type is vad.VADEventType.END_OF_SPEECH:
                    if self._gate_open:
                        self._gate_open = False
                        self._buffer.clear()
                        self._buffer_samples = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            # Fail open for microphone safety: a VAD failure must not make the
            # user permanently inaudible. It may reduce echo protection, but
            # conversation remains usable and the failure is visible in logs.
            LOGGER.exception(
                "AEC-clean local Silero barge-in gate failed; failing open"
            )
            self._gate_open = True
            self._release_buffer()

    def _release_buffer(self) -> None:
        buffered = tuple(self._buffer)
        self._buffer.clear()
        self._buffer_samples = 0
        for frame, observed_at in buffered:
            if not self._forward(frame, observed_at):
                LOGGER.error(
                    "Voice session microphone queue overflowed while releasing barge-in prefix"
                )
                break

    def _forward(self, frame: rtc.AudioFrame, observed_at: float) -> bool:
        accepted = super().push_frame(
            frame,
            observed_at_monotonic=observed_at,
        )
        if not accepted or self._observer is None:
            return accepted
        try:
            self._observer(frame, observed_at)
        except Exception:
            LOGGER.exception(
                "Passive session-audio observer failed; conversation audio continues"
            )
        return True

    def _reset_closed_gate(self) -> None:
        self._buffer.clear()
        self._buffer_samples = 0
        try:
            self._vad_stream.flush()
        except Exception:
            LOGGER.exception("Failed to reset local barge-in VAD stream")
