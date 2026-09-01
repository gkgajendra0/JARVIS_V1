"""Thread-safe wake bridge for audio owned by the paired GStreamer source."""

from __future__ import annotations

import asyncio

from livekit import rtc

from jarvis.voice.wakeword import LiveKitWakeDetector, WakeDetection


class PairedWakeDetectorBridge:
    """Expose one wake detector while accepting audio only from paired capture.

    ``LocalAudioRuntime`` still owns the temporary conversation microphone. Its
    ordinary ``feed`` calls are intentionally ignored so idle wake detection does
    not silently drift back to that unrelated device. GStreamer's native callback
    uses ``feed_external_pcm``; frames are handed onto the asyncio loop before the
    underlying detector is touched.
    """

    def __init__(self, detector: LiveKitWakeDetector) -> None:
        self._detector = detector
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def enabled(self) -> bool:
        return self._detector.enabled

    def enable(self, *, clear_buffer: bool = True) -> None:
        self._loop = asyncio.get_running_loop()
        self._detector.enable(clear_buffer=clear_buffer)

    def disable(self, *, clear_buffer: bool = True) -> None:
        self._detector.disable(clear_buffer=clear_buffer)

    def clear_buffer(self) -> None:
        self._detector.clear_buffer()

    def feed(self, frame: rtc.AudioFrame) -> None:
        """Ignore the temporary conversation microphone as a wake source."""
        del frame

    def feed_external_pcm(
        self,
        data: bytes | bytearray | memoryview,
        *,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        """Post one native-thread paired-audio buffer onto the asyncio loop."""
        if sample_rate <= 0:
            raise ValueError("paired wake sample rate must be positive")
        if num_channels != 1:
            raise ValueError("paired wake audio must be mono")
        if samples_per_channel <= 0:
            raise ValueError("paired wake frame size must be positive")
        payload = bytes(data)
        expected_bytes = samples_per_channel * 2
        if len(payload) != expected_bytes:
            raise ValueError("paired wake PCM byte length does not match int16 mono audio")

        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(
            self._feed_external_frame,
            payload,
            sample_rate,
            samples_per_channel,
        )

    def _feed_external_frame(
        self,
        payload: bytes,
        sample_rate: int,
        samples_per_channel: int,
    ) -> None:
        frame = rtc.AudioFrame(
            data=payload,
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=samples_per_channel,
        )
        self._detector.feed(frame)

    async def wait_for_detection(self) -> WakeDetection:
        return await self._detector.wait_for_detection()

    async def aclose(self) -> None:
        self._loop = None
        await self._detector.aclose()
