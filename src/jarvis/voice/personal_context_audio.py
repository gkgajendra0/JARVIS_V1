"""Lease-checking wrapper around the normal, shared physical audio output."""

from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities


class PersonalContextAudioOutput(AudioOutput):
    def __init__(self, output, personal):
        super().__init__(
            label="owner-context",
            sample_rate=output.sample_rate,
            capabilities=AudioOutputCapabilities(pause=output.can_pause),
            next_in_chain=output,
        )
        self._personal = personal
        personal.bind_audio_clear(self.clear_buffer)
        self._finished = lambda event: personal.playback_finished()
        self.on("playback_finished", self._finished)

    async def capture_frame(self, frame):
        if await self._personal.allow_audio():
            await super().capture_frame(frame)
            await self._next_in_chain.capture_frame(frame)
        else:
            self.clear_buffer()

    def flush(self):
        super().flush()
        self._next_in_chain.flush()

    def clear_buffer(self):
        self._next_in_chain.clear_buffer()

    def detach(self):
        # Remove listeners only. The controller owns and reuses the real device.
        self.off("playback_finished", self._finished)
        chain = self._next_in_chain
        chain.off("playback_finished", self._forward_next_playback_finished)
        chain.off("playback_started", self._forward_next_playback_started)
        chain.off("playback_progressed", self._forward_next_playback_progressed)
