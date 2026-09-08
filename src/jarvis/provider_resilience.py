"""Deterministic cloud-provider failure classification and health state.

Step 5 deliberately keeps this policy JARVIS-owned. Provider/LiveKit exceptions are
untrusted mechanics; they may describe a failure, but they never decide runtime
authority or mutate canonical conversation/memory state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProviderFailureKind(str, Enum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    MODEL_UNAVAILABLE = "model_unavailable"
    REQUEST_REJECTED = "request_rejected"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    CONNECTION_LOST = "connection_lost"
    UNKNOWN = "unknown"


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


def _provider_display_name(provider: str) -> str:
    normalized = provider.strip().casefold()
    if normalized == "gemini":
        return "Gemini"
    if normalized == "openai":
        return "OpenAI"
    return provider.strip() or "the cloud provider"


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    kind: ProviderFailureKind
    status_code: int | None = None
    retryable: bool | None = None

    @property
    def spoken_message(self) -> str:
        name = _provider_display_name(self.provider)
        messages = {
            ProviderFailureKind.QUOTA_EXHAUSTED: (
                f"Sir, {name}'s API quota is exhausted. Cloud conversation is "
                "temporarily unavailable. I am returning to wake mode."
            ),
            ProviderFailureKind.RATE_LIMITED: (
                f"Sir, {name} is rate-limiting requests at the moment. Please try "
                "again shortly. I am returning to wake mode."
            ),
            ProviderFailureKind.AUTHENTICATION_FAILED: (
                f"Sir, {name} is rejecting the configured credentials. Cloud "
                "conversation is unavailable until they are corrected."
            ),
            ProviderFailureKind.PERMISSION_DENIED: (
                f"Sir, the configured {name} credentials do not have permission for "
                "this request. I am returning to wake mode."
            ),
            ProviderFailureKind.MODEL_UNAVAILABLE: (
                f"Sir, the configured {name} realtime model is unavailable or could "
                "not be found. I am returning to wake mode."
            ),
            ProviderFailureKind.REQUEST_REJECTED: (
                f"Sir, {name} rejected the realtime request. I am returning to wake "
                "mode."
            ),
            ProviderFailureKind.PROVIDER_SERVER_ERROR: (
                f"Sir, {name} returned an internal server error. I am returning to "
                "wake mode."
            ),
            ProviderFailureKind.SERVICE_UNAVAILABLE: (
                f"Sir, {name}'s service is temporarily unavailable. I am returning "
                "to wake mode."
            ),
            ProviderFailureKind.TIMEOUT: (
                f"Sir, {name} did not respond within the expected time. I am "
                "returning to wake mode."
            ),
            ProviderFailureKind.CONNECTION_LOST: (
                f"Sir, I cannot currently reach {name}. The network or provider "
                "connection is unavailable. I am returning to wake mode."
            ),
            ProviderFailureKind.UNKNOWN: (
                f"Sir, {name} became unavailable because of an unclassified provider "
                "error. I am returning to wake mode."
            ),
        }
        return messages[self.kind]


@dataclass(slots=True)
class ProviderResilienceState:
    health: ProviderHealth = ProviderHealth.HEALTHY
    last_failure: ProviderFailure | None = None

    def mark_failure(self, failure: ProviderFailure) -> None:
        self.health = ProviderHealth.DEGRADED
        self.last_failure = failure

    def mark_recovered(self) -> bool:
        if self.health is ProviderHealth.HEALTHY:
            return False
        self.health = ProviderHealth.HEALTHY
        self.last_failure = None
        return True


def _error_chain(error: object) -> tuple[object, ...]:
    chain: list[object] = []
    seen: set[int] = set()
    current: object | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        nested = getattr(current, "error", None)
        if nested is not None and nested is not current:
            current = nested
            continue
        cause = getattr(current, "__cause__", None)
        if cause is not None and cause is not current:
            current = cause
            continue
        context = getattr(current, "__context__", None)
        if context is not None and context is not current:
            current = context
            continue
        break
    return tuple(chain)


def _status_code(chain: tuple[object, ...]) -> int | None:
    for item in chain:
        value = getattr(item, "status_code", None)
        if isinstance(value, int) and value >= 0:
            return value
        value = getattr(item, "status", None)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _retryable(chain: tuple[object, ...]) -> bool | None:
    for item in chain:
        value = getattr(item, "retryable", None)
        if isinstance(value, bool):
            return value
    return None


def _classification_text(chain: tuple[object, ...]) -> str:
    parts: list[str] = []
    for item in chain:
        parts.append(type(item).__name__)
        try:
            message = str(item)
        except Exception:  # noqa: BLE001 - diagnostic evidence is best effort only
            message = ""
        if message:
            parts.append(message)
        body: Any = getattr(item, "body", None)
        if body is not None:
            try:
                parts.append(str(body))
            except Exception:  # noqa: BLE001 - diagnostic evidence is best effort only
                parts.append(type(body).__name__)
    return " ".join(parts).casefold()


def classify_provider_failure(error: object, *, provider: str) -> ProviderFailure:
    """Classify provider failure without exposing raw provider payloads to users/logs."""

    chain = _error_chain(error)
    status = _status_code(chain)
    retryable = _retryable(chain)
    evidence = _classification_text(chain)

    if status == 429:
        quota_markers = (
            "quota_exceeded",
            "quota exceeded",
            "resource_exhausted",
            "resource exhausted",
            "insufficient_quota",
            "daily quota",
            "billing quota",
        )
        kind = (
            ProviderFailureKind.QUOTA_EXHAUSTED
            if any(marker in evidence for marker in quota_markers)
            else ProviderFailureKind.RATE_LIMITED
        )
    elif status == 401:
        kind = ProviderFailureKind.AUTHENTICATION_FAILED
    elif status == 403:
        kind = ProviderFailureKind.PERMISSION_DENIED
    elif status == 404:
        kind = (
            ProviderFailureKind.MODEL_UNAVAILABLE
            if "model" in evidence
            else ProviderFailureKind.REQUEST_REJECTED
        )
    elif status in {408, 504}:
        kind = ProviderFailureKind.TIMEOUT
    elif status == 500:
        kind = ProviderFailureKind.PROVIDER_SERVER_ERROR
    elif status in {502, 503}:
        kind = ProviderFailureKind.SERVICE_UNAVAILABLE
    elif status is not None and 400 <= status < 500:
        kind = ProviderFailureKind.REQUEST_REJECTED
    elif "timeout" in evidence or "timed out" in evidence or "deadline" in evidence:
        kind = ProviderFailureKind.TIMEOUT
    elif any(
        marker in evidence
        for marker in (
            "apiconnectionerror",
            "connectionerror",
            "connection error",
            "connection closed",
            "closed unexpectedly",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "name resolution",
            "dns",
        )
    ):
        kind = ProviderFailureKind.CONNECTION_LOST
    elif status is not None and status >= 500:
        kind = ProviderFailureKind.PROVIDER_SERVER_ERROR
    else:
        kind = ProviderFailureKind.UNKNOWN

    return ProviderFailure(
        provider=provider,
        kind=kind,
        status_code=status,
        retryable=retryable,
    )
