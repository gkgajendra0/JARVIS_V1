from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.health_adapters import ProviderResilienceHealthObserver
from jarvis.provider_resilience import ProviderResilienceState, classify_provider_failure
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState
from jarvis.voice.provider_resilience import ProviderResilienceSessionObserver


class FakeStatusError(Exception):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = None
        self.retryable = False


class FakeRealtimeError:
    type = "realtime_model_error"
    label = "fake-realtime"

    def __init__(self, error: Exception, *, recoverable: bool) -> None:
        self.error = error
        self.recoverable = recoverable


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = defaultdict(list)
        self.closed = asyncio.Event()

    def on(self, event: str, callback):
        self.handlers[event].append(callback)
        return callback

    def emit(self, event: str, value: Any) -> None:
        for callback in tuple(self.handlers[event]):
            callback(value)

    async def aclose(self) -> None:
        self.closed.set()


def test_provider_health_adapter_maps_degraded_then_recovered(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    state = ProviderResilienceState()
    observer = ProviderResilienceHealthObserver(awareness)

    state.mark_failure(
        classify_provider_failure(
            FakeStatusError("service unavailable", status_code=503),
            provider="gemini",
        )
    )
    observer(state)
    degraded = awareness.component_snapshot("runtime.provider")
    assert degraded.health.state is HealthState.DEGRADED
    assert "provider_service_unavailable" in degraded.health.reason_codes

    state.mark_recovered()
    observer(state)
    healthy = awareness.component_snapshot("runtime.provider")
    assert healthy.health.state is HealthState.HEALTHY
    assert "provider_healthy" in healthy.health.reason_codes
    awareness.close()


@pytest.mark.asyncio
async def test_session_observer_notifies_health_on_terminal_failure_and_recovery() -> None:
    session = FakeSession()
    state = ProviderResilienceState()
    observed: list[tuple[str, str | None]] = []

    def observe(current: ProviderResilienceState) -> None:
        observed.append(
            (
                current.health.value,
                current.last_failure.kind.value if current.last_failure else None,
            )
        )

    provider_observer = ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=state,
        status_speech=None,
        output_getter=lambda: None,
        health_observer=observe,
    )
    wrapped = FakeRealtimeError(
        FakeStatusError("service unavailable", status_code=503),
        recoverable=False,
    )

    session.emit("error", SimpleNamespace(error=wrapped, source=object()))
    await asyncio.wait_for(session.closed.wait(), timeout=1)
    assert observed[0] == ("degraded", "service_unavailable")
    assert provider_observer.terminal_task is not None
    await provider_observer.terminal_task

    session.emit("agent_state_changed", SimpleNamespace(new_state="listening"))
    assert observed[-1] == ("healthy", None)
