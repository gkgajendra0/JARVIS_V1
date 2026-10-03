"""Bounded provider-pressure circuit breaker for non-authoritative background AI."""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.work.provider_retry import provider_retry_hint
from jarvis.work.store import default_work_state_dir

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

    The default clock is wall time rather than monotonic time because production
    circuits can be restored after a process restart. Tests may still inject a
    deterministic clock.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        failed_attempts: int = 0,
        blocked_until: float = 0.0,
        on_change: Callable[["BackgroundProviderCircuit"], None] | None = None,
    ) -> None:
        if isinstance(failed_attempts, bool) or int(failed_attempts) < 0:
            raise ValueError("failed_attempts must be a non-negative integer")
        if float(blocked_until) < 0:
            raise ValueError("blocked_until must not be negative")
        self._clock = clock
        self._blocked_until = float(blocked_until)
        self._failed_attempts = int(failed_attempts)
        self._on_change = on_change

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._blocked_until - self._clock())

    def allow_request(self) -> bool:
        return self.remaining_seconds <= 0.0

    @property
    def blocked_until(self) -> float:
        return self._blocked_until

    def _notify_change(self) -> None:
        callback = self._on_change
        if callback is not None:
            callback(self)

    def record_success(self) -> None:
        self._failed_attempts = 0
        self._blocked_until = 0.0
        self._notify_change()

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
        self._notify_change()
        return ProviderCircuitTrip(
            reason=reason,
            status_code=hint.status_code,
            delay_seconds=delay,
            failed_attempts=self._failed_attempts,
        )



def provider_circuit_key(*, provider: str, model: str | None = None) -> str:
    """Return the durable capacity key for one provider allowance domain."""

    normalized_provider = str(provider).strip().casefold()
    if not normalized_provider:
        raise ValueError("provider must not be empty")
    if normalized_provider == "chatgpt_plan":
        # Subscription Sharing usage is app/account scoped, not model scoped.
        return "chatgpt_plan:subscription"
    normalized_model = str(model or "").strip().casefold()
    return (
        normalized_provider
        if not normalized_model
        else f"{normalized_provider}:{normalized_model}"
    )


class BackgroundProviderCircuitRegistry:
    """Own process-wide provider circuits and persist cooldown state across restarts."""

    def __init__(
        self,
        *,
        path: str | pathlib.Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = pathlib.Path(
            path or (default_work_state_dir() / "provider_circuits.json")
        ).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._circuits: dict[str, BackgroundProviderCircuit] = {}
        self._state = self._load()

    def _load(self) -> dict[str, dict[str, float | int]]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, dict[str, float | int]] = {}
        for key, raw in payload.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            try:
                attempts = int(raw.get("failed_attempts", 0))
                blocked_until = float(raw.get("blocked_until", 0.0))
            except (TypeError, ValueError):
                continue
            if attempts < 0 or blocked_until < 0:
                continue
            result[key] = {
                "failed_attempts": attempts,
                "blocked_until": blocked_until,
            }
        return result

    def _persist(self) -> None:
        payload = {key: dict(value) for key, value in self._state.items()}
        for key, circuit in self._circuits.items():
            if circuit.failed_attempts > 0 or circuit.blocked_until > 0:
                payload[key] = {
                    "failed_attempts": circuit.failed_attempts,
                    "blocked_until": circuit.blocked_until,
                }
            else:
                payload.pop(key, None)
        self._state = payload
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)

    def _changed(self, key: str, circuit: BackgroundProviderCircuit) -> None:
        with self._lock:
            self._circuits[key] = circuit
            self._persist()

    def circuit(self, key: str) -> BackgroundProviderCircuit:
        normalized = str(key).strip().casefold()
        if not normalized:
            raise ValueError("provider circuit key must not be empty")
        with self._lock:
            existing = self._circuits.get(normalized)
            if existing is not None:
                return existing
            restored = self._state.get(normalized, {})
            circuit = BackgroundProviderCircuit(
                clock=self._clock,
                failed_attempts=int(restored.get("failed_attempts", 0)),
                blocked_until=float(restored.get("blocked_until", 0.0)),
                on_change=lambda value, key=normalized: self._changed(key, value),
            )
            self._circuits[normalized] = circuit
            return circuit
