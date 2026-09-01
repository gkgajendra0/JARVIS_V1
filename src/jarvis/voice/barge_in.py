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
from collections import deque
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


class BargeInGate:
    """Filter AEC-cleaned PCM before it enters the active realtime session."""

    def __init__(
        self,
        *,
        vad_model: _VADModel | None = None,
        buffer_seconds: float = _BARGE_BUFFER_SECONDS,
    ) -> None:
        if buffer_seconds <= 0:
            raise ValueError("barge-in buffer duration must be positive")
        self._buffer_limit_samples = round(buffer_seconds * DEVICE_SAMPLE_RATE)
        self._buffer: deque[tuple[rtc.AudioFrame, float]] = deque()
        self._buffer_samples = 0
        self._target: SessionAudioInput | None = None
        self._agent_speaking = False
        self._gate_open = False
        self._closed = False
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

    def set_target(self, target: SessionAudioInput | None) -> None:
        self._target = target
        if target is None:
            self._gate_open = False
            self._reset_closed_gate()

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
        # If genuine near-end speech already opened the gate, keep forwarding
        # until Silero publishes END_OF_SPEECH so the user's full utterance is
        # not clipped merely because assistant playout stopped.
        if not self._gate_open:
            self._reset_closed_gate()

    def push_frame(
        self,
        frame: rtc.AudioFrame,
        *,
        observed_at_monotonic: float,
    ) -> bool:
        if self._closed:
            return False
        target = self._target
        if target is None:
            return False
        if observed_at_monotonic < 0:
            raise ValueError("barge-in audio timestamp must be non-negative")

        if self._gate_open:
            self._vad_stream.push_frame(frame)
            return target.push_frame(
                frame,
                observed_at_monotonic=observed_at_monotonic,
            )

        # Outside assistant speech, provider-native activity detection receives
        # canonical AEC-clean audio with zero additional latency.
        if not self._agent_speaking:
            return target.push_frame(
                frame,
                observed_at_monotonic=observed_at_monotonic,
            )

        # During assistant speech, retain a bounded prefix and let Silero decide
        # whether this is real near-end speech or residual far-end echo.
        self._buffer.append((frame, observed_at_monotonic))
        self._buffer_samples += frame.samples_per_channel
        while (
            self._buffer
            and self._buffer_samples - self._buffer[0][0].samples_per_channel
            >= self._buffer_limit_samples
        ):
            old_frame, _ = self._buffer.popleft()
            self._buffer_samples -= old_frame.samples_per_channel
        self._vad_stream.push_frame(frame)
        # Withheld echo is intentionally accepted by the router; it is not a
        # downstream microphone queue overflow.
        return True

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._target = None
        self._buffer.clear()
        self._buffer_samples = 0
        self._vad_task.cancel()
        await asyncio.gather(self._vad_task, return_exceptions=True)
        await self._vad_stream.aclose()

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
                if event.type is vad.VADEventType.END_OF_SPEECH and self._gate_open:
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
        target = self._target
        if target is None:
            self._buffer.clear()
            self._buffer_samples = 0
            return
        buffered = tuple(self._buffer)
        self._buffer.clear()
        self._buffer_samples = 0
        for frame, observed_at in buffered:
            if not target.push_frame(
                frame,
                observed_at_monotonic=observed_at,
            ):
                LOGGER.error(
                    "Voice session microphone queue overflowed while releasing barge-in prefix"
                )
                break

    def _reset_closed_gate(self) -> None:
        self._buffer.clear()
        self._buffer_samples = 0
        try:
            self._vad_stream.flush()
        except Exception:
            LOGGER.exception("Failed to reset local barge-in VAD stream")
