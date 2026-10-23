import asyncio

from livekit import rtc
from livekit.agents import llm
from tests.gemini_fallback.live_helpers import ProviderModel, empty_stream


def test_retired_transport_drops_late_tool_transcript_and_audio():
    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )

    async def run():
        epoch = [0]
        state = GeminiTransportState(epoch=0, current_epoch=lambda: epoch[0])
        inner = ProviderModel()
        wrapped = GuardedGeminiRealtimeModel(inner, state)
        session = wrapped.session()
        events = []
        session.on("input_audio_transcription_completed", events.append)
        inner.sessions[0].emit(
            "input_audio_transcription_completed",
            llm.InputTranscriptionCompleted("old", "accepted before retirement", True),
        )
        assert len(events) == 1
        epoch[0] = 1
        inner.sessions[0].emit(
            "input_audio_transcription_completed",
            llm.InputTranscriptionCompleted("late", "late text", True),
        )
        assert len(events) == 1
        frame = rtc.AudioFrame(b"\0" * 320, 16000, 1, 160)
        session.push_audio(frame)
        assert inner.sessions[0].audio == []
        await session.aclose()

    asyncio.run(run())


def test_generation_stream_cannot_release_tool_or_audio_after_epoch_changes():
    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )

    async def run():
        epoch = [0]
        state = GeminiTransportState(epoch=0, current_epoch=lambda: epoch[0])
        inner = ProviderModel()
        wrapped = GuardedGeminiRealtimeModel(inner, state)
        session = wrapped.session()
        generations = []
        session.on("generation_created", generations.append)

        async def functions():
            epoch[0] = 1
            yield llm.FunctionCall(
                id="late-call", call_id="call-1", name="send", arguments="{}"
            )

        event = llm.GenerationCreatedEvent(
            message_stream=empty_stream(),
            function_stream=functions(),
            user_initiated=False,
        )
        inner.sessions[0].emit("generation_created", event)
        assert [item async for item in generations[0].function_stream] == []
        await session.aclose()

    asyncio.run(run())


def test_microphone_transition_discards_buffered_and_new_unaccepted_pcm():
    from jarvis.voice.audio import SessionAudioInput

    async def run():
        stream = SessionAudioInput()
        old = rtc.AudioFrame(b"\0" * 320, 16000, 1, 160)
        new = rtc.AudioFrame(b"\0" * 320, 16000, 1, 160)
        assert stream.push_frame(old)
        stream.set_transport_enabled(False)
        assert not stream.push_frame(old)
        stream.set_transport_enabled(True)
        assert stream.push_frame(new)
        assert await stream.__anext__() is new
        stream.close()

    asyncio.run(run())


def test_final_audio_sink_rejects_old_or_unattributed_epoch():
    from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

    from jarvis.voice.gemini_transport import GeminiEpochAudioOutput

    async def run():
        class Sink(AudioOutput):
            def __init__(self):
                super().__init__(
                    label="fake physical",
                    sample_rate=48000,
                    capabilities=AudioOutputCapabilities(pause=False),
                )
                self.frames = []

            async def capture_frame(self, frame):
                self.frames.append(frame)

            def flush(self):
                pass

            def clear_buffer(self):
                pass

        sink = Sink()
        output = GeminiEpochAudioOutput(sink, lambda: 1)
        for epoch in [None, 0, 1]:
            frame = rtc.AudioFrame(b"\0" * 320, 16000, 1, 160)
            if epoch is not None:
                frame.userdata["jarvis_transport_epoch"] = epoch
            await output.capture_frame(frame)
        assert len(sink.frames) == 1
        assert sink.frames[0].userdata["jarvis_transport_epoch"] == 1
        output.detach()

    asyncio.run(run())


def test_audio_epoch_survives_resampling_before_sdk_output_forwarding():
    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )

    async def run():
        state = GeminiTransportState(
            epoch=4, current_epoch=lambda: 4, output_sample_rate=48000
        )
        raw = ProviderModel()
        wrapped = GuardedGeminiRealtimeModel(raw, state)
        session = wrapped.session()
        generations = []
        session.on("generation_created", generations.append)

        async def frames():
            yield rtc.AudioFrame(b"\0" * 960, 24000, 1, 480)

        async def messages():
            modalities = asyncio.get_running_loop().create_future()
            modalities.set_result(["audio"])
            yield llm.MessageGeneration(
                message_id="reply",
                text_stream=empty_stream(),
                audio_stream=frames(),
                modalities=modalities,
            )

        raw.sessions[0].emit(
            "generation_created",
            llm.GenerationCreatedEvent(
                message_stream=messages(),
                function_stream=empty_stream(),
                user_initiated=False,
            ),
        )
        output = []
        async for message in generations[0].message_stream:
            output.extend([frame async for frame in message.audio_stream])
        assert output
        assert all(
            frame.sample_rate == 48000 and frame.userdata["jarvis_transport_epoch"] == 4
            for frame in output
        )
        await session.aclose()

    asyncio.run(run())
