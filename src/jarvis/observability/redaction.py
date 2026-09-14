"""Deny-by-default sanitization for privileged operational evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"
_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "private_key",
    "access_key",
    "raw_audio",
    "raw_video",
    "audio_pcm",
    "face_crop",
    "gaze_vector",
    "iris_coordinate",
    "screenshot",
    "provider_payload",
    "prompt_content",
    "completion_content",
)
_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+\-/=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)


def _sensitive_key(key: str) -> bool:
    normalized = str(key).casefold()
    return any(part in normalized for part in _FORBIDDEN_KEY_PARTS)


def _sanitize_string(value: str) -> str:
    sanitized = value
    for pattern in _VALUE_PATTERNS:
        sanitized = pattern.sub(_REDACTED, sanitized)
    return sanitized


def redact_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            sanitized[key] = (
                _REDACTED if _sensitive_key(key) else redact_data(raw_value)
            )
        return sanitized
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, set):
        return sorted(redact_data(item) for item in value)
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return _sanitize_string(str(value))


def redact_event_dict(event_dict: dict[str, Any]) -> dict[str, Any]:
    return dict(redact_data(event_dict))
