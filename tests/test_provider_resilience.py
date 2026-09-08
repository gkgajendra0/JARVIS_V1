from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.provider_resilience import (
    ProviderFailureKind,
    ProviderHealth,
    ProviderResilienceState,
    classify_provider_failure,
)
from jarvis.voice.provider_resilience import ProviderResilienceSessionObserver


class FakeStatusError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: object | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.retryable = retryable


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


class FakeStatusSpeech:
    def __init__(self) -> None:
        self.spoken: list[tuple[object, str]] = []

    async def speak(self, output: object, text: str) -> None:
        self.spoken.append((output, text))


def test_429_quota_is_distinguished_from_rate_limit() -> None:
    quota = classify_provider_failure(
        FakeStatusError(
            "RESOURCE_EXHAUSTED",
            status_code=429,
            body={"error": {"code": "quota_exceeded"}},
        ),
        provider="gemini",
    )
    rate = classify_provider_failure(
        FakeStatusError(
            "Too many requests",
            status_code=429,
            body={"error": {"code": "rate_limit_exceeded"}},
        ),
        provider="gemini",
    )

    assert quota.kind is ProviderFailureKind.QUOTA_EXHAUSTED
    assert quota.status_code == 429
    assert "quota is exhausted" in quota.spoken_message
    assert rate.kind is ProviderFailureKind.RATE_LIMITED
    assert "rate-limiting" in rate.spoken_message


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, None, ProviderFailureKind.AUTHENTICATION_FAILED),
        (403, None, ProviderFailureKind.PERMISSION_DENIED),
        (404, {"error": "model_not_found"}, ProviderFailureKind.MODEL_UNAVAILABLE),
        (408, None, ProviderFailureKind.TIMEOUT),
        (500, None, ProviderFailureKind.PROVIDER_SERVER_ERROR),
        (503, None, ProviderFailureKind.SERVICE_UNAVAILABLE),
    ],
)
def test_http_failures_map_to_bounded_diagnostics(
    status: int,
    body: object | None,
    expected: ProviderFailureKind,
) -> None:
    failure = classify_provider_failure(
        FakeStatusError("controlled", status_code=status, body=body),
        provider="openai",
    )
    assert failure.kind is expected
    assert failure.status_code == status


def test_http_status_is_read_from_nested_response_object() -> None:
    class FakeResponse:
        status_code = 429
        reason = "Too Many Requests"

    class RequestsStyleHTTPError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("429 Client Error")
            self.response = FakeResponse()

    failure = classify_provider_failure(
        RequestsStyleHTTPError(),
        provider="exa",
    )

    assert failure.status_code == 429
    assert failure.kind is ProviderFailureKind.RATE_LIMITED


def test_connection_failure_does_not_claim_exact_internet_root_cause() -> None:
    class APIConnectionError(RuntimeError):
        pass

    failure = classify_provider_failure(
        APIConnectionError("connection closed unexpectedly"),
        provider="gemini",
    )

    assert failure.kind is ProviderFailureKind.CONNECTION_LOST
    assert "network or provider connection" in failure.spoken_message


def test_raw_provider_payload_is_not_spoken() -> None:
    failure = classify_provider_failure(
        FakeStatusError(
            "secret diagnostic payload",
            status_code=500,
            body={"internal": "sensitive-provider-detail"},
        ),
        provider="gemini",
    )

    assert "secret diagnostic payload" not in failure.spoken_message
    assert "sensitive-provider-detail" not in failure.spoken_message


@pytest.mark.asyncio
async def test_terminal_realtime_failure_is_announced_locally_then_closed() -> None:
    session = FakeSession()
    state = ProviderResilienceState()
    speech = FakeStatusSpeech()
    output = object()
    observer = ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=state,
        status_speech=speech,
        output_getter=lambda: output,  # type: ignore[arg-type]
    )
    wrapped = FakeRealtimeError(
        FakeStatusError(
            "RESOURCE_EXHAUSTED",
            status_code=429,
            body={"error": {"code": "quota_exceeded"}},
        ),
        recoverable=False,
    )

    session.emit("error", SimpleNamespace(error=wrapped, source=object()))
    await asyncio.wait_for(session.closed.wait(), timeout=1)

    assert wrapped.recoverable is True
    assert state.health is ProviderHealth.DEGRADED
    assert state.last_failure is not None
    assert state.last_failure.kind is ProviderFailureKind.QUOTA_EXHAUSTED
    assert speech.spoken == [(output, state.last_failure.spoken_message)]
    assert observer.terminal_task is not None
    await observer.terminal_task


def test_recoverable_realtime_error_is_not_announced_or_marked_degraded() -> None:
    session = FakeSession()
    state = ProviderResilienceState()
    speech = FakeStatusSpeech()
    observer = ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=state,
        status_speech=speech,
        output_getter=lambda: object(),  # type: ignore[arg-type]
    )
    wrapped = FakeRealtimeError(
        FakeStatusError("temporary", status_code=503, retryable=True),
        recoverable=True,
    )

    session.emit("error", SimpleNamespace(error=wrapped, source=object()))

    assert observer.terminal_task is None
    assert state.health is ProviderHealth.HEALTHY
    assert speech.spoken == []


def test_next_live_agent_state_marks_provider_recovered() -> None:
    state = ProviderResilienceState()
    state.mark_failure(
        classify_provider_failure(
            FakeStatusError("down", status_code=503),
            provider="gemini",
        )
    )
    session = FakeSession()
    ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=state,
        status_speech=None,
        output_getter=lambda: None,
    )

    session.emit("agent_state_changed", SimpleNamespace(new_state="listening"))

    assert state.health is ProviderHealth.HEALTHY
    assert state.last_failure is None
