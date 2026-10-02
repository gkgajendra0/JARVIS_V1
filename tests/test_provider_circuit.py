from __future__ import annotations

from jarvis.chatgpt_plan import ChatGPTPlanUsageUnavailable
from jarvis.provider_circuit import BackgroundProviderCircuit


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
