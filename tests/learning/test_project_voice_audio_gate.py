"""ProjectAudioGate against LiveKit's real AudioOutput chain.

Uses the pinned SDK's AudioOutput, including the _AudioSinkProxy that real
LiveKit inserts above a bare leaf sink. Skipped only where the SDK is absent.
"""

import asyncio
import inspect

import pytest


def _real_livekit():
    from livekit.agents import function_tool

    return inspect.isfunction(function_tool)


async def exercise_gate(audio_output, capabilities, gate_class, make_frame):
    """Shared by the test and by offline runs against the real io module."""

    class Sink(audio_output):
        def __init__(self):
            super().__init__(
                label="sink",
                capabilities=capabilities(pause=False),
                sample_rate=24000,
            )
            self.frames = 0
            self.flushes = 0
            self.clears = 0

        async def capture_frame(self, frame):
            await super().capture_frame(frame)
            self.frames += 1

        def flush(self):
            super().flush()
            self.flushes += 1

        def clear_buffer(self):
            self.clears += 1

    decisions = iter([False, True])
    asked = []

    class Turns:
        def allow_response_audio(self):
            asked.append(1)
            return next(decisions)

    sink = Sink()
    gate = gate_class(sink, Turns())
    # Real LiveKit wraps a bare leaf in its swap proxy.
    assert gate.next_in_chain is not sink
    assert gate.next_in_chain.next_in_chain is sink

    # Withheld response: decided once, nothing reaches the device, nothing
    # counted as played, and playout waits do not hang.
    for _ in range(3):
        await gate.capture_frame(make_frame())
    gate.flush()
    assert len(asked) == 1
    assert sink.frames == 0 and sink.flushes == 0
    assert gate.captured_playout_segments == 0
    await asyncio.wait_for(gate.wait_for_playout(), 0.5)

    # Allowed response: every frame forwarded and flushed as one segment.
    for _ in range(2):
        await gate.capture_frame(make_frame())
    gate.flush()
    assert len(asked) == 2
    assert sink.frames == 2 and sink.flushes == 1
    assert gate.captured_playout_segments == 1
    sink.on_playback_finished(playback_position=0.02, interrupted=False)
    finished = await asyncio.wait_for(gate.wait_for_playout(), 0.5)
    assert finished.interrupted is False

    # Barge-in clears the device and resets the per-segment decision.
    gate.clear_buffer()
    assert sink.clears == 1 and gate._allowed is None

    # Detach leaves no listener on the long-lived device.
    gate.detach()
    for name in ("playback_finished", "playback_started", "playback_progressed"):
        assert not sink._events.get(name)


@pytest.mark.skipif(not _real_livekit(), reason="needs the real LiveKit SDK")
@pytest.mark.asyncio
async def test_real_audio_gate_forwards_only_allowed_segments():
    from livekit import rtc
    from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

    from jarvis.voice.project_voice_audio import ProjectAudioGate

    def frame():
        return rtc.AudioFrame(b"\0\0" * 240, 24000, 1, 240)

    await exercise_gate(AudioOutput, AudioOutputCapabilities, ProjectAudioGate, frame)


async def exercise_async_gate(audio_output, capabilities, gate_class, make_frame):
    """The fast path's async decision: frames wait for it, none are lost; a
    segment cleared (barge-in) while deciding forwards nothing."""

    class Sink(audio_output):
        def __init__(self):
            super().__init__(
                label="sink", capabilities=capabilities(pause=False), sample_rate=24000
            )
            self.frames = 0

        async def capture_frame(self, frame):
            await super().capture_frame(frame)
            self.frames += 1

        def flush(self):
            super().flush()

        def clear_buffer(self):
            pass

    release = asyncio.Event()
    asked = []

    class Turns:
        async def response_audio_allowed(self):
            asked.append(1)
            await release.wait()
            return True

        def allow_response_audio(self):  # never used when the async one exists
            raise AssertionError("sync decision used")

    sink = Sink()
    gate = gate_class(sink, Turns())
    first = asyncio.ensure_future(gate.capture_frame(make_frame()))
    await asyncio.sleep(0)
    assert sink.frames == 0 and not first.done()  # waiting for the decision
    release.set()
    await first
    await gate.capture_frame(make_frame())
    assert sink.frames == 2 and len(asked) == 1  # delayed, not dropped
    gate.flush()

    release.clear()
    pending = asyncio.ensure_future(gate.capture_frame(make_frame()))
    await asyncio.sleep(0)
    gate.clear_buffer()  # barge-in while deciding
    release.set()
    await pending
    assert sink.frames == 2  # the cleared segment forwarded nothing


@pytest.mark.skipif(not _real_livekit(), reason="needs the real LiveKit SDK")
@pytest.mark.asyncio
async def test_real_audio_gate_waits_for_an_async_decision():
    from livekit import rtc
    from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

    from jarvis.voice.project_voice_audio import ProjectAudioGate

    def frame():
        return rtc.AudioFrame(b"\0\0" * 240, 24000, 1, 240)

    await exercise_async_gate(
        AudioOutput, AudioOutputCapabilities, ProjectAudioGate, frame
    )
