"""Provider-neutral retry classification for transient cloud failures."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RETRYABLE_STATUS_CODES = {429, 503}
_MAX_PROVIDER_RETRY_SECONDS = 24 * 60 * 60
_DELIVERY_BACKOFF_BASE_SECONDS = 5.0
_DELIVERY_BACKOFF_MAX_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class ProviderRetryHint:
    """Normalized retry guidance derived from one provider exception chain."""

    status_code: int | None
    retry_after_seconds: float | None
    reason: str


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    items: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        items.append(current)
        seen.add(id(current))
        cause = current.__cause__
        if cause is None or cause is current:
            cause = current.__context__
        current = cause
    return tuple(items)


def _coerce_status_code(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _status_code_from_exception(exc: BaseException) -> int | None:
    for item in _exception_chain(exc):
        candidates = [
            getattr(item, "status_code", None),
            getattr(item, "code", None),
        ]
        response = getattr(item, "response", None)
        if response is not None:
            candidates.extend(
                [
                    getattr(response, "status_code", None),
                    getattr(response, "status", None),
                    getattr(response, "code", None),
                ]
            )
        for candidate in candidates:
            code = _coerce_status_code(candidate)
            if code is not None:
                return code

    match = re.search(r"(?<!\d)(429|503)(?!\d)", str(exc))
    return int(match.group(1)) if match else None


def _duration_seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        text = value.strip().lower()
        match = re.fullmatch(
            r"([0-9]+(?:\.[0-9]+)?)\s*(ms|milliseconds?|s|sec|secs|seconds?)?",
            text,
        )
        if match is None:
            return None
        seconds = float(match.group(1))
        unit = match.group(2) or "s"
        if unit.startswith("ms"):
            seconds /= 1000.0
    else:
        return None

    if seconds <= 0:
        return None
    return min(seconds, float(_MAX_PROVIDER_RETRY_SECONDS))


def _structured_retry_delay(value: object) -> float | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).replace("-", "").replace("_", "").casefold()
            if normalized_key in {
                "retrydelay",
                "retryafter",
                "retryafterseconds",
            }:
                parsed = _duration_seconds(nested)
                if parsed is not None:
                    return parsed
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple)):
                parsed = _structured_retry_delay(nested)
                if parsed is not None:
                    return parsed
        return None

    if isinstance(value, (list, tuple)):
        for nested in value:
            parsed = _structured_retry_delay(nested)
            if parsed is not None:
                return parsed
    return None


def _retry_delay_from_value(value: object) -> float | None:
    structured = _structured_retry_delay(value)
    if structured is not None:
        return structured

    if isinstance(value, dict):
        for nested in value.values():
            parsed = _retry_delay_from_value(nested)
            if parsed is not None:
                return parsed
        return None

    if isinstance(value, (list, tuple)):
        for nested in value:
            parsed = _retry_delay_from_value(nested)
            if parsed is not None:
                return parsed
        return None

    if isinstance(value, str):
        patterns = (
            (
                r"retry(?:ing)?\s+(?:in|after)\s+([0-9]+(?:\.[0-9]+)?)\s*"
                r"(ms|milliseconds?|s|sec|secs|seconds?)"
            ),
            (
                r"retry(?:_|-)?delay[\"']?\s*[:=]\s*[\"']?"
                r"([0-9]+(?:\.[0-9]+)?)\s*"
                r"(ms|milliseconds?|s|sec|secs|seconds?)"
            ),
        )
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match is not None:
                return _duration_seconds(f"{match.group(1)}{match.group(2)}")
    return None


def _retry_after_from_exception(exc: BaseException) -> float | None:
    for item in _exception_chain(exc):
        for name in (
            "retry_after_seconds",
            "retry_after",
            "retry_delay",
            "retry_delay_seconds",
        ):
            parsed = _duration_seconds(getattr(item, name, None))
            if parsed is not None:
                return parsed

        for name in ("details", "body"):
            parsed = _retry_delay_from_value(getattr(item, name, None))
            if parsed is not None:
                return parsed

        parsed = _retry_delay_from_value(str(item))
        if parsed is not None:
            return parsed

    return None


def provider_retry_hint(exc: BaseException) -> ProviderRetryHint | None:
    """Return retry guidance for provider pressure without binding to one SDK."""

    status_code = _status_code_from_exception(exc)
    text = " ".join(str(item) for item in _exception_chain(exc)).casefold()
    retryable = status_code in _RETRYABLE_STATUS_CODES
    if not retryable and (
        "resource_exhausted" in text
        or "too many requests" in text
        or "temporarily unavailable" in text
    ):
        retryable = True

    if not retryable:
        return None

    if status_code == 429 or "resource_exhausted" in text:
        reason = "rate_limit"
    elif status_code == 503 or "temporarily unavailable" in text:
        reason = "temporarily_unavailable"
    else:
        reason = "provider_pressure"

    return ProviderRetryHint(
        status_code=status_code,
        retry_after_seconds=_retry_after_from_exception(exc),
        reason=reason,
    )


def delivery_retry_delay_seconds(
    *,
    failed_attempts: int,
    provider_hint: ProviderRetryHint | None,
) -> float:
    """Choose provider guidance first, otherwise bounded exponential backoff."""

    if failed_attempts < 0:
        raise ValueError("failed_attempts must not be negative")
    if provider_hint is not None and provider_hint.retry_after_seconds is not None:
        return provider_hint.retry_after_seconds

    return min(
        _DELIVERY_BACKOFF_BASE_SECONDS * (2**failed_attempts),
        _DELIVERY_BACKOFF_MAX_SECONDS,
    )
