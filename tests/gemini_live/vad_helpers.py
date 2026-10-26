"""Synthetic VAD boundary, real AgentSession/local audio pipeline."""

import time

from livekit.agents import vad


class ActivityVAD(vad.VAD):
    def __init__(self):
        super().__init__(capabilities=vad.VADCapabilities(update_interval=0.02))
        self.frames = 0

    def stream(self):
        return ActivityStream(self)


class ActivityStream(vad.VADStream):
    async def _main_task(self):
        speaking = False
        frames = []
        index = 0
        async for frame in self._input_ch:
            if isinstance(frame, self._FlushSentinel):
                speaking = False
                frames = []
                continue
            self._vad.frames += 1
            index += frame.samples_per_channel
            active = any(bytes(frame.data))
            frames.append(frame)
            kind = None
            if active and not speaking:
                kind = vad.VADEventType.START_OF_SPEECH
                speaking = True
            elif not active and speaking:
                kind = vad.VADEventType.END_OF_SPEECH
                speaking = False
            if kind is not None:
                self._event_ch.send_nowait(
                    vad.VADEvent(
                        type=kind,
                        samples_index=index,
                        timestamp=time.perf_counter(),
                        speech_duration=0.7,
                        silence_duration=0 if active else 0.1,
                        frames=list(frames),
                        probability=1 if active else 0,
                        speaking=speaking,
                    )
                )
            self._event_ch.send_nowait(
                vad.VADEvent(
                    type=vad.VADEventType.INFERENCE_DONE,
                    samples_index=index,
                    timestamp=time.perf_counter(),
                    speech_duration=0.7 if active else 0,
                    silence_duration=0 if active else 0.1,
                    probability=1 if active else 0,
                    frames=[frame],
                    speaking=speaking,
                )
            )
