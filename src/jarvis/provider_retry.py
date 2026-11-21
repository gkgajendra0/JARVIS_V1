"""Bounded retry policy for temporary provider failures (owner-approved 2026-11-21).

One initial attempt plus at most two retries, and only for a failure that the
provider itself reports as temporary: HTTP 503/502 (service unavailable), 500
(server error) or a lost connection. Everything else is final on the first
attempt, including:

- 429 rate limits and quota exhaustion (the existing cooldown applies);
- authentication, permission and invalid-request failures;
- timeouts and stalls (the deadline is already spent; they stay unresolved);
- invalid output or a wrong answer (that is a result, not a transport failure).

The waits grow (about 2 s, then about 5 s, with +/-25 % randomness) and must fit
inside the caller's *existing* deadline with time left for a useful attempt;
otherwise no retry is made. This module only decides. The caller owns the
single retry loop, rechecks its permissions before every attempt and records
each attempt. Nothing here extends a deadline, a lease or a permission.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .provider_resilience import ProviderFailureKind

MAX_ATTEMPTS = 3
RETRY_DELAYS = (2.0, 5.0)
RETRY_JITTER = 0.25
MIN_ATTEMPT_SECONDS = 6.0

TRANSIENT_KINDS = frozenset(
    {
        ProviderFailureKind.SERVICE_UNAVAILABLE,
        ProviderFailureKind.PROVIDER_SERVER_ERROR,
        ProviderFailureKind.CONNECTION_LOST,
    }
)

RETRY = "transient_retry"
NOT_TRANSIENT = "not_transient"
ATTEMPTS_EXHAUSTED = "attempts_exhausted"
DEADLINE_INSUFFICIENT = "deadline_insufficient"


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    reason: str
    delay: float = 0.0


def is_transient(failure) -> bool:
    return getattr(failure, "kind", None) in TRANSIENT_KINDS


def decide_retry(failure, *, attempt: int, remaining: float, rng=random.random):
    """Decide whether attempt ``attempt`` (1-based) that failed with
    ``failure`` may be followed by another, given ``remaining`` seconds of the
    caller's deadline."""
    if not is_transient(failure):
        return RetryDecision(False, NOT_TRANSIENT)
    if attempt >= MAX_ATTEMPTS:
        return RetryDecision(False, ATTEMPTS_EXHAUSTED)
    base = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)) - 1]
    delay = round(base * (1 + RETRY_JITTER * (2 * rng() - 1)), 3)
    if remaining - delay < MIN_ATTEMPT_SECONDS:
        return RetryDecision(False, DEADLINE_INSUFFICIENT)
    return RetryDecision(True, RETRY, delay)


def policy_summary() -> dict:
    return {
        "max_attempts": MAX_ATTEMPTS,
        "retry_delays_seconds": list(RETRY_DELAYS),
        "jitter": RETRY_JITTER,
        "min_attempt_seconds": MIN_ATTEMPT_SECONDS,
        "transient_kinds": sorted(k.value for k in TRANSIENT_KINDS),
    }
