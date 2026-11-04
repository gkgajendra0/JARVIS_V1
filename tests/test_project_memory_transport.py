"""Network-free tests of production dispatch, plus pinned adapter characterization."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from jarvis.memory.project_conversations import PreparedProjectReply, ProjectSelection
from jarvis.voice.project_memory_transport import (
    ProjectReplyDispatcher,
    StaleProjectReply,
)


def packet(request_id="request-1"):
    return PreparedProjectReply(
        request_id=request_id,
        selection=ProjectSelection("nepal", "nepal-thread", 1),
        source_ids=("accepted-turn",),
        context="USER: Nepal trip; vehicle is Jimny; permit pending.",
        revision="archive:1/personal:0",
        estimated_tokens=18,
    )


class ProviderBoundary:
    def __init__(self):
        self.packets = []
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.closed = False

    async def generate(self, prepared):
        self.packets.append(prepared)
        self.started.set()
        try:
            await self.finish.wait()
            yield b"answer-audio"
        finally:
            self.closed = True


def test_archive_and_context_finish_before_any_provider_generation():
    async def scenario():
        provider = ProviderBoundary()
        committed = asyncio.Event()
        preparing = asyncio.Event()
        released = []
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=released.append
        )

        async def prepare():
            preparing.set()
            await committed.wait()
            return packet()

        pending = asyncio.create_task(dispatcher.reply("request-1", prepare))
        await preparing.wait()
        assert provider.packets == []  # not even an uninformed generation
        committed.set()
        await provider.started.wait()
        assert provider.packets == [packet()]  # actual boundary payload
        assert released == []
        provider.finish.set()
        result = await pending
        assert result.request_id == "request-1"
        assert result.revision == packet().revision
        assert released == [b"answer-audio"]
        assert provider.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reason", ["interruption", "project_switch", "transport_recreated"]
)
def test_invalidation_while_generating_discards_audio(reason):
    async def scenario():
        provider = ProviderBoundary()
        released = []
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=released.append
        )

        async def prepare():
            return packet()

        pending = asyncio.create_task(dispatcher.reply("request-1", prepare))
        await provider.started.wait()
        dispatcher.invalidate(reason)
        provider.finish.set()
        with pytest.raises(StaleProjectReply):
            await pending
        assert released == []
        assert provider.closed

    asyncio.run(scenario())


def test_invalidation_during_archive_write_prevents_generation():
    async def scenario():
        provider = ProviderBoundary()
        preparing, proceed = asyncio.Event(), asyncio.Event()
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=lambda _: None
        )

        async def prepare():
            preparing.set()
            await proceed.wait()
            return packet()

        pending = asyncio.create_task(dispatcher.reply("request-1", prepare))
        await preparing.wait()
        dispatcher.invalidate("project_switch")
        proceed.set()
        with pytest.raises(StaleProjectReply):
            await pending
        assert provider.packets == []

    asyncio.run(scenario())


def test_failed_archive_commit_never_generates():
    async def scenario():
        provider = ProviderBoundary()
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=lambda _: None
        )

        async def prepare():
            raise OSError("database unavailable")

        with pytest.raises(OSError, match="database unavailable"):
            await dispatcher.reply("request-1", prepare)
        assert provider.packets == []

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["revoked", "wrong_request"])
def test_denied_or_mismatched_packet_never_generates(mutation):
    async def scenario():
        provider = ProviderBoundary()
        dispatcher = ProjectReplyDispatcher(
            provider,
            validate_current=lambda _: mutation != "revoked",
            release_audio=lambda _: None,
        )

        async def prepare():
            return (
                replace(packet(), request_id="other")
                if mutation == "wrong_request"
                else packet()
            )

        with pytest.raises(StaleProjectReply):
            await dispatcher.reply("request-1", prepare)
        assert provider.packets == []

    asyncio.run(scenario())


def test_pinned_google_adapter_can_emit_generation_before_final_transcript():
    """Exercise installed adapter handlers, without opening a socket or an API client."""
    from google.genai import types
    from livekit.plugins.google.realtime.realtime_api import RealtimeSession

    async def scenario():
        session = object.__new__(RealtimeSession)
        session._current_generation = None
        session._pending_generation_fut = asyncio.get_running_loop().create_future()
        session._realtime_model = SimpleNamespace(
            capabilities=SimpleNamespace(audio_output=True)
        )
        session._opts = SimpleNamespace(output_audio_transcription=object())
        observed = []
        session.emit = lambda name, value: observed.append((name, value))
        session._start_new_generation()
        session._handle_server_content(
            types.LiveServerContent(
                input_transcription=types.Transcription(text="I want to go to Nepal")
            )
        )
        assert observed[0][0] == "generation_created"
        assert observed[1][0] == "input_audio_transcription_completed"
        assert observed[1][1].is_final is False

    asyncio.run(scenario())


def test_revocation_after_generation_blocks_audio():
    async def scenario():
        provider = ProviderBoundary()
        current = True
        released = []
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: current, release_audio=released.append
        )

        async def prepare():
            return packet()

        pending = asyncio.create_task(dispatcher.reply("request-1", prepare))
        await provider.started.wait()
        current = False
        provider.finish.set()
        with pytest.raises(StaleProjectReply):
            await pending
        assert released == []

    asyncio.run(scenario())


def test_cancelling_reply_closes_provider_stream():
    async def scenario():
        provider = ProviderBoundary()
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=lambda _: None
        )

        async def prepare():
            return packet()

        pending = asyncio.create_task(dispatcher.reply("request-1", prepare))
        await provider.started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert provider.closed

    asyncio.run(scenario())


def test_request_can_retry_after_preparation_failed_before_dispatch():
    async def scenario():
        provider = ProviderBoundary()
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=lambda _: None
        )

        async def failed():
            raise OSError("temporary archive failure")

        async def recovered():
            return packet()

        with pytest.raises(OSError):
            await dispatcher.reply("request-1", failed)
        provider.finish.set()
        result = await dispatcher.reply("request-1", recovered)
        assert result.request_id == "request-1"
        assert provider.packets == [packet()]
        with pytest.raises(StaleProjectReply):
            await dispatcher.reply("request-1", recovered)

    asyncio.run(scenario())
