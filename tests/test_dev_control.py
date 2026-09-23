from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.dev_control import (
    DevControlClient,
    DevControlClientConfig,
    parse_explicit_update_decision,
)


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "YES",
        "yeah",
        "yep",
        "Jarvis yes",
        "yes please",
        "Yes, sir. I will do it.",
        "Jarvis, yes sir, go ahead.",
        "haan",
        "हाँ",
        "हाँ जी, कर दीजिए।",
    ],
)
def test_spoken_update_decision_accepts_explicit_yes(text: str) -> None:
    assert parse_explicit_update_decision(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "no",
        "NO",
        "nope",
        "nah",
        "Jarvis no",
        "no please",
        "No, sir. Leave it.",
        "nahi",
        "नहीं",
    ],
)
def test_spoken_update_decision_accepts_explicit_no(text: str) -> None:
    assert parse_explicit_update_decision(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "maybe",
        "maybe yes",
        "do it",
        "sure",
        "okay",
        "I guess so",
        "restart later",
        "yes, but no",
        "yes, do not update",
        "yes, don't update",
        "no, actually yes",
    ],
)
def test_spoken_update_decision_rejects_ambiguous_or_conflicting_speech(
    text: str,
) -> None:
    assert parse_explicit_update_decision(text) is None


@pytest.mark.asyncio
async def test_dev_control_client_answers_authenticated_liveness_probe() -> None:
    observed: dict[str, object] = {}

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        observed["hello"] = json.loads(await reader.readline())
        writer.write(b'{"type":"liveness_probe","request_id":"probe-1"}\n')
        await writer.drain()
        observed["liveness"] = json.loads(await reader.readline())
        writer.write(b'{"type":"shutdown_request","request_id":"shutdown-1"}\n')
        await writer.drain()
        observed["shutdown"] = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    client = DevControlClient(
        DevControlClientConfig(
            host=str(host),
            port=int(port),
            token="test-token",
        )
    )

    async with server:
        await asyncio.wait_for(
            client.run(
                approval_handler=lambda *_: asyncio.sleep(0, result=False),
                shutdown_handler=lambda: None,
            ),
            timeout=2,
        )

    assert observed["hello"] == {
        "type": "hello",
        "token": "test-token",
    }
    assert observed["liveness"] == {
        "type": "liveness_response",
        "request_id": "probe-1",
        "alive": True,
    }
    assert observed["shutdown"] == {
        "type": "shutdown_ack",
        "request_id": "shutdown-1",
    }
