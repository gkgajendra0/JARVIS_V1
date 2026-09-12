from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.voice import production_runtime


class _ManagedHttpContext:
    def __init__(self, events: list[str], state: dict[str, bool]) -> None:
        self._events = events
        self._state = state

    async def __aenter__(self) -> None:
        assert not self._state["active"]
        self._state["active"] = True
        self._events.append("http_enter")

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        assert self._state["active"]
        self._events.append("http_exit")
        self._state["active"] = False


def _wire_runtime_lifecycle(monkeypatch, *, run_error: Exception | None = None):
    events: list[str] = []
    state = {"active": False}
    config = SimpleNamespace(log_level="INFO")

    class FakeRuntime:
        async def run(self) -> None:
            assert state["active"]
            events.append("run")
            if run_error is not None:
                raise run_error

    def configure_logging(log_level: str) -> None:
        assert log_level == "INFO"
        events.append("logging")

    def require_startup_preflight(runtime_config) -> None:
        assert runtime_config is config
        assert not state["active"]
        events.append("preflight")

    def build_runtime(runtime_config):
        assert runtime_config is config
        assert state["active"]
        events.append("build")
        return FakeRuntime()

    monkeypatch.setattr(
        production_runtime.JarvisConfig,
        "from_environment",
        classmethod(lambda cls: config),
    )
    monkeypatch.setattr(production_runtime, "configure_logging", configure_logging)
    monkeypatch.setattr(
        production_runtime,
        "require_startup_preflight",
        require_startup_preflight,
    )
    monkeypatch.setattr(
        production_runtime,
        "build_production_voice_runtime",
        build_runtime,
    )
    monkeypatch.setattr(
        production_runtime.http_context,
        "open",
        lambda: _ManagedHttpContext(events, state),
    )
    return events, state


@pytest.mark.asyncio
async def test_production_runtime_owns_livekit_http_context(monkeypatch) -> None:
    events, state = _wire_runtime_lifecycle(monkeypatch)

    await production_runtime._run_from_configuration()

    assert events == [
        "logging",
        "preflight",
        "http_enter",
        "build",
        "run",
        "http_exit",
    ]
    assert state["active"] is False


@pytest.mark.asyncio
async def test_production_runtime_closes_livekit_http_context_on_failure(monkeypatch) -> None:
    events, state = _wire_runtime_lifecycle(
        monkeypatch,
        run_error=RuntimeError("runtime failed"),
    )

    with pytest.raises(RuntimeError, match="runtime failed"):
        await production_runtime._run_from_configuration()

    assert events == [
        "logging",
        "preflight",
        "http_enter",
        "build",
        "run",
        "http_exit",
    ]
    assert state["active"] is False
