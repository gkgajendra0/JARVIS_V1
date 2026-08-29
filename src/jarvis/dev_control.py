"""Local-only control protocol between jarvis-dev and the voice runtime."""

from __future__ import annotations

import asyncio
import json
import os
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

DEV_CONTROL_HOST_ENV = "JARVIS_DEV_CONTROL_HOST"
DEV_CONTROL_PORT_ENV = "JARVIS_DEV_CONTROL_PORT"
DEV_CONTROL_TOKEN_ENV = "JARVIS_DEV_CONTROL_TOKEN"

ApprovalHandler = Callable[[str, str], Awaitable[bool]]
ShutdownHandler = Callable[[], None]


@dataclass(frozen=True, slots=True)
class DevControlClientConfig:
    host: str
    port: int
    token: str

    @classmethod
    def from_environment(cls) -> DevControlClientConfig | None:
        host = os.environ.get(DEV_CONTROL_HOST_ENV, "").strip()
        port_text = os.environ.get(DEV_CONTROL_PORT_ENV, "").strip()
        token = os.environ.get(DEV_CONTROL_TOKEN_ENV, "").strip()
        if not host and not port_text and not token:
            return None
        if not host or not port_text or not token:
            raise RuntimeError("incomplete JARVIS development control configuration")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise RuntimeError("invalid JARVIS development control port") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError("JARVIS development control port is out of range")
        return cls(host=host, port=port, token=token)


def _normalized_confirmation(text: str) -> str:
    normalized = "".join(
        character
        if character.isspace() or unicodedata.category(character)[0] in {"L", "M", "N"}
        else " "
        for character in text.casefold()
    )
    candidate = " ".join(normalized.split())
    for prefix in ("jarvis ", "जार्विस "):
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix).strip()
    for suffix in (" please", " कृपया"):
        if candidate.endswith(suffix):
            candidate = candidate.removesuffix(suffix).strip()
    return candidate


def parse_explicit_update_decision(text: str) -> bool | None:
    """Return an explicit Yes/No decision; ambiguous speech stays undecided."""
    candidate = _normalized_confirmation(text)
    if candidate in {"yes", "yeah", "yep", "haan", "han", "हाँ", "हां"}:
        return True
    if candidate in {"no", "nope", "nah", "nahi", "nahin", "नहीं", "नही"}:
        return False
    return None


async def _write_message(
    writer: asyncio.StreamWriter,
    payload: dict[str, object],
) -> None:
    writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
    await writer.drain()


class DevControlClient:
    """Voice-runtime side of the loopback supervisor protocol."""

    def __init__(self, config: DevControlClientConfig) -> None:
        self.config = config

    @classmethod
    def from_environment(cls) -> DevControlClient | None:
        config = DevControlClientConfig.from_environment()
        return cls(config) if config is not None else None

    async def run(
        self,
        *,
        approval_handler: ApprovalHandler,
        shutdown_handler: ShutdownHandler,
    ) -> None:
        reader, writer = await asyncio.open_connection(
            self.config.host,
            self.config.port,
        )
        try:
            await _write_message(
                writer,
                {"type": "hello", "token": self.config.token},
            )
            while True:
                line = await reader.readline()
                if not line:
                    return
                message = json.loads(line)
                message_type = message.get("type")
                request_id = str(message.get("request_id", ""))
                if message_type == "update_approval_request":
                    approved = await approval_handler(
                        str(message.get("local_sha", "")),
                        str(message.get("remote_sha", "")),
                    )
                    await _write_message(
                        writer,
                        {
                            "type": "update_approval_response",
                            "request_id": request_id,
                            "approved": approved,
                        },
                    )
                elif message_type == "shutdown_request":
                    await _write_message(
                        writer,
                        {"type": "shutdown_ack", "request_id": request_id},
                    )
                    shutdown_handler()
                    return
        finally:
            writer.close()
            await writer.wait_closed()
