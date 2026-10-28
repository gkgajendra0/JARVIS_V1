"""Actual installed LiveKit Gemini SDK; only Google's network client is replaced."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from google.genai import types
from google.genai.errors import APIError

from jarvis.config import JarvisConfig
from jarvis.voice.gemini_transport import GeminiTransportState
from jarvis.voice.livekit_session import _create_realtime_model


@pytest.mark.asyncio
async def test_installed_sdk_does_not_resume_failed_handle_on_fresh_transport(
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-test-key")
    connections = []
    physical_closed = []
    clients_closed = []

    class Wire:
        def __init__(self, index):
            self.index = index

        async def receive(self):
            if self.index == 0:
                yield types.LiveServerMessage(
                    session_resumption_update=types.LiveServerSessionResumptionUpdate(
                        resumable=True, new_handle="old-failed-handle"
                    )
                )
                raise APIError(1011, {"message": "Internal error encountered"})
            await asyncio.Event().wait()
            if False:
                yield None

        async def close(self):
            physical_closed.append(self.index)

    class Client:
        def __init__(self, **kwargs):
            self.aio = SimpleNamespace(
                live=SimpleNamespace(connect=self.connect), aclose=self.aclose
            )

        @asynccontextmanager
        async def connect(self, *, model, config):
            index = len(connections)
            connections.append(config)
            yield Wire(index)

        async def aclose(self):
            clients_closed.append(True)

    monkeypatch.setattr(
        "livekit.plugins.google.realtime.realtime_api.GenAIClient", Client
    )
    config = JarvisConfig(ai_provider="gemini")
    first = _create_realtime_model(
        config, transport_state=GeminiTransportState(epoch=0, current_epoch=lambda: 0)
    )
    session = first.session()
    failed = asyncio.Event()
    session.on("error", lambda _: failed.set())
    second_session = None
    try:
        await asyncio.wait_for(failed.wait(), 2)
        assert len(connections) == 1
        assert session.inner.session_resumption_handle == "old-failed-handle"
        await session.aclose()
        assert 0 in physical_closed
        assert clients_closed
        second = _create_realtime_model(
            config,
            transport_state=GeminiTransportState(epoch=1, current_epoch=lambda: 1),
        )
        second_session = second.session()

        async def connected():
            while len(connections) < 2:
                await asyncio.sleep(0)

        await asyncio.wait_for(connected(), 2)
        assert connections[1].session_resumption.handle is None
    finally:
        await session.aclose()
        if second_session is not None:
            await second_session.aclose()
