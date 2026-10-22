"""Provider-free tests: no accidental network, keys or owner profile access."""

import socket

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

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
