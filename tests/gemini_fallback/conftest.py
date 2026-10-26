"""Provider-free tests: no accidental network, keys or owner profile access."""

import socket
import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_inference(monkeypatch, tmp_path):
    for name in (
        "GOOGLE_API_KEY",
        "JARVIS_GEMINI_PAID_API_KEY",
        "OPENAI_API_KEY",
        "JARVIS_TTS_GOOGLE_API_KEY",
        "JARVIS_TTS_OPENAI_API_KEY",
        "JARVIS_GEMINI_PAID_FALLBACK_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "machine.json"))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)

    def blocked(*args, **kwargs):
        raise AssertionError(
            "External inference/network is forbidden in fallback tests"
        )

    original_connect = socket.socket.connect
    socketpair_code = socket.socketpair.__code__

    def guarded_connect(self, address):
        # Windows asyncio creates its wakeup pipe through stdlib socketpair.
        # Permit that direct internal caller only; provider/network calls stay blocked.
        if sys._getframe(1).f_code is socketpair_code:
            return original_connect(self, address)
        return blocked(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
