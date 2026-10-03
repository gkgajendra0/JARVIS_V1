from __future__ import annotations

from pathlib import Path

from jarvis.chatgpt_plan import ChatGPTPlanUsageUnavailable
from jarvis.provider_circuit import (
    BackgroundProviderCircuit,
    BackgroundProviderCircuitRegistry,
    provider_circuit_key,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class _RateLimitError(RuntimeError):
    status_code = 429


def test_background_provider_circuit_uses_exponential_rate_limit_backoff() -> None:
    clock = _Clock()
    circuit = BackgroundProviderCircuit(clock=clock)

    first = circuit.record_failure(_RateLimitError("429 Too Many Requests"))
    assert first is not None
    assert first.reason == "rate_limit"
    assert first.delay_seconds == 60.0
    assert circuit.allow_request() is False

    clock.value += 60.0
    assert circuit.allow_request() is True

    second = circuit.record_failure(_RateLimitError("429 Too Many Requests"))
    assert second is not None
    assert second.delay_seconds == 120.0


def test_subscription_usage_limit_opens_long_shadow_cooldown() -> None:
    clock = _Clock()
    circuit = BackgroundProviderCircuit(clock=clock)

    trip = circuit.record_failure(
        ChatGPTPlanUsageUnavailable(
            "The ChatGPT user has reached their Subscription Sharing usage limit.",
            status_code=429,
            code="subscription_sharing_usage_limit_exceeded",
            retryable=True,
        )
    )

    assert trip is not None
    assert trip.reason == "subscription_usage_limit"
    assert trip.delay_seconds == 30.0 * 60.0
    assert circuit.allow_request() is False


def test_success_resets_provider_circuit() -> None:
    clock = _Clock()
    circuit = BackgroundProviderCircuit(clock=clock)
    assert circuit.record_failure(_RateLimitError("429 Too Many Requests")) is not None

    circuit.record_success()

    assert circuit.allow_request() is True
    assert circuit.failed_attempts == 0
    assert circuit.remaining_seconds == 0.0


def test_chatgpt_plan_circuit_key_is_shared_across_models() -> None:
    assert provider_circuit_key(
        provider="chatgpt_plan",
        model="gpt-6-astra",
    ) == provider_circuit_key(
        provider="chatgpt_plan",
        model="another-model",
    )


def test_registry_reuses_one_circuit_across_sessions(tmp_path: Path) -> None:
    registry = BackgroundProviderCircuitRegistry(path=tmp_path / "circuits.json")
    first = registry.circuit("chatgpt_plan:subscription")
    second = registry.circuit("chatgpt_plan:subscription")

    assert first is second


def test_subscription_cooldown_survives_restart_and_probes_after_expiry(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    path = tmp_path / "circuits.json"
    error = ChatGPTPlanUsageUnavailable(
        "The ChatGPT user has reached their Subscription Sharing usage limit.",
        status_code=429,
        code="subscription_sharing_usage_limit_exceeded",
        retryable=True,
    )

    first_registry = BackgroundProviderCircuitRegistry(path=path, clock=clock)
    first = first_registry.circuit("chatgpt_plan:subscription")
    first_trip = first.record_failure(error)

    assert first_trip is not None
    assert first_trip.failed_attempts == 1
    assert first.allow_request() is False

    second_registry = BackgroundProviderCircuitRegistry(path=path, clock=clock)
    restored = second_registry.circuit("chatgpt_plan:subscription")
    assert restored.failed_attempts == 1
    assert restored.allow_request() is False

    clock.value += 30.0 * 60.0
    assert restored.allow_request() is True

    second_trip = restored.record_failure(error)
    assert second_trip is not None
    assert second_trip.failed_attempts == 2
    assert second_trip.delay_seconds == 60.0 * 60.0
    assert restored.allow_request() is False
