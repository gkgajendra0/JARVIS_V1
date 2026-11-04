"""Per-response audio gate for project voice memory (isolated lab only).

Decides once at the start of each response segment whether Gemini's answer was
produced with this utterance's project context. Allowed segments pass through
unchanged; a blocked segment is never forwarded (nothing is heard, and LiveKit
records it as unplayed), and VoiceProjectTurns re-requests a prepared answer.
Barge-in mid-segment is LiveKit's own interruption and is not re-decided here.

When the turns object offers an async decision (``response_audio_allowed``),
the first frame waits for it: the fast path may let streaming recognition
catch up for a moment instead of withholding an ordinary answer. Frames are
delayed, never dropped, while it decides; a segment cleared meanwhile is
discarded.
"""

from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities


class ProjectAudioGate(AudioOutput):
    def __init__(self, output, turns, *, inner_detach=None):
        super().__init__(
            label="project-memory",
            sample_rate=output.sample_rate,
            capabilities=AudioOutputCapabilities(pause=output.can_pause),
            next_in_chain=output,
        )
        self._turns = turns
        self._output = output
        self._allowed = None
        self._segment = 0
        self._detached = False
        self._inner_detach = inner_detach

    async def capture_frame(self, frame):
        if self._allowed is None:
            segment = self._segment
            decide = getattr(type(self._turns), "response_audio_allowed", None)
            if decide is not None:
                allowed = await self._turns.response_audio_allowed()
            else:
                allowed = self._turns.allow_response_audio()
            if segment != self._segment:
                return  # flushed or interrupted while deciding
            self._allowed = allowed
        if self._allowed:
            await super().capture_frame(frame)
            await self._next_in_chain.capture_frame(frame)

    def flush(self):
        allowed, self._allowed = self._allowed, None
        self._segment += 1
        super().flush()
        if allowed:
            self._next_in_chain.flush()

    def clear_buffer(self):
        self._allowed = None
        self._segment += 1
        self._next_in_chain.clear_buffer()

    def detach(self):
        # Remove listeners only. The controller owns and reuses the real device.
        if self._detached:
            return
        self._detached = True
        chain = self._next_in_chain
        chain.off("playback_finished", self._forward_next_playback_finished)
        chain.off("playback_started", self._forward_next_playback_started)
        chain.off("playback_progressed", self._forward_next_playback_progressed)
        if chain is not self._output:
            self._output.off("playback_finished", chain._forward_next_playback_finished)
            self._output.off("playback_started", chain._forward_next_playback_started)
            self._output.off(
                "playback_progressed", chain._forward_next_playback_progressed
            )
        if self._inner_detach is not None:
            self._inner_detach()  # a session wrapper this gate was stacked on
