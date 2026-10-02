"""Bounded provider-pressure circuit breaker for non-authoritative background AI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from jarvis.work.provider_retry import ProviderRetryHint, provider_retry_hint

_RATE_LIMIT_BASE_SECONDS = 60.0
_RATE_LIMIT_MAX_SECONDS = 30.0 * 60.0
_SUBSCRIPTION_LIMIT_BASE_SECONDS = 30.0 * 60.0
_SUBSCRIPTION_LIMIT_MAX_SECONDS = 6.0 * 60.0 * 60.0
_TEMPORARY_UNAVAILABLE_BASE_SECONDS = 30.0
_TEMPORARY_UNAVAILABLE_MAX_SECONDS = 10.0 * 60.0


@dataclass(frozen=True, slots=True)
class ProviderCircuitTrip:
    reason: str
    status_code: int | None
    delay_seconds: float
    failed_attempts: int


class BackgroundProviderCircuit:
    """Pause best-effort AI work after retryable provider pressure.

    This circuit is intended for non-authoritative/background features where repeated
    cloud retries add cost/noise without improving correctness. Authoritative behavior
    must never depend on the circuit opening or closing.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._blocked_until = 0.0
        self._failed_attempts = 0

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._blocked_until - self._clock())

    def allow_request(self) -> bool:
        return self.remaining_seconds <= 0.0

    def record_success(self) -> None:
        self._failed_attempts = 0
        self._blocked_until = 0.0

    @staticmethod
    def _subscription_limit(exc: BaseException) -> bool:
        text = str(exc).casefold()
        return (
            "subscription_sharing_usage_limit_exceeded" in text
            or "subscription_sharing_usage_unavailable" in text
            or "subscription sharing usage limit" in text
        )

    def record_failure(self, exc: BaseException) -> ProviderCircuitTrip | None:
        hint = provider_retry_hint(exc)
        if hint is None:
            return None

        self._failed_attempts += 1
        if self._subscription_limit(exc):
            base = _SUBSCRIPTION_LIMIT_BASE_SECONDS
            maximum = _SUBSCRIPTION_LIMIT_MAX_SECONDS
            reason = "subscription_usage_limit"
        elif hint.status_code == 429:
            base = _RATE_LIMIT_BASE_SECONDS
            maximum = _RATE_LIMIT_MAX_SECONDS
            reason = "rate_limit"
        else:
            base = _TEMPORARY_UNAVAILABLE_BASE_SECONDS
            maximum = _TEMPORARY_UNAVAILABLE_MAX_SECONDS
            reason = hint.reason

        delay = (
            float(hint.retry_after_seconds)
            if hint.retry_after_seconds is not None
            else min(base * (2 ** (self._failed_attempts - 1)), maximum)
        )
        self._blocked_until = max(self._blocked_until, self._clock() + delay)
        return ProviderCircuitTrip(
            reason=reason,
            status_code=hint.status_code,
            delay_seconds=delay,
            failed_attempts=self._failed_attempts,
        )
