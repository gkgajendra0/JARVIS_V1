"""Bounded public LiveKit response streams; never execute a function here."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm
from livekit.agents.utils import aio


class LiveResponse:
    def __init__(self, *, current):
        self.current = current
        self.response_id = "live-response-" + uuid4().hex
        self.input_id = "live-input-" + uuid4().hex
        self.started_at = time.time()
        self.transcript = ""
        self.final_transcript = False
        self.closed = False
        self.text = aio.Chan(maxsize=128)
        self.audio = aio.Chan(maxsize=256)
        self.messages = aio.Chan(maxsize=1)
        self.functions = aio.Chan(maxsize=64)
        modalities = asyncio.get_running_loop().create_future()
        modalities.set_result(["text", "audio"])
        self.messages.send_nowait(
            llm.MessageGeneration(
                message_id=self.response_id,
                text_stream=self.stream(self.text),
                audio_stream=self.stream(self.audio),
                modalities=modalities,
            )
        )
        self.messages.close()
        self.event = llm.GenerationCreatedEvent(
            message_stream=self.stream(self.messages),
            function_stream=self.stream(self.functions),
            user_initiated=True,
            response_id=self.response_id,
        )

    async def stream(self, channel):
        async for value in channel:
            if not self.current():
                return
            yield value

    def content(self, content):
        # Output ASR is the spoken caption. Do not leak thought/unspoken model text.
        for part in (content.model_turn.parts or []) if content.model_turn else []:
            if part.thought:
                continue
            if part.inline_data is not None:
                blob = part.inline_data
                if (
                    blob.mime_type != "audio/pcm;rate=24000"
                    or not isinstance(blob.data, bytes)
                    or len(blob.data) % 2
                ):
                    raise llm.RealtimeError("Unsupported controlled Live audio")
                if blob.data:
                    self.audio.send_nowait(
                        rtc.AudioFrame(
                            data=blob.data,
                            sample_rate=24000,
                            num_channels=1,
                            samples_per_channel=len(blob.data) // 2,
                        )
                    )
            if part.text and content.output_transcription is None:
                self.text.send_nowait(part.text)
        if content.output_transcription and content.output_transcription.text:
            self.text.send_nowait(content.output_transcription.text)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.text.close()
        self.audio.close()
        self.functions.close()
