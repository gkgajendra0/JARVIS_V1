"""Canonical JSON/digest helpers for Phase-5 engineering-substrate contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from jarvis.engineering_knowledge.canonical import (
    JSONValue,
    canonical_sha256,
    canonicalize_json,
)


class SubstrateCanonicalizationError(ValueError):
    """A contract cannot be represented by the canonical JSON integrity contract."""


def _to_json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _to_json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SubstrateCanonicalizationError(
                    "canonical mappings require string keys"
                )
            result[key] = _to_json_value(item)
        return result
    raise SubstrateCanonicalizationError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def canonical_payload(value: Any) -> JSONValue:
    """Convert one immutable substrate contract into canonical JSON-compatible data."""

    return _to_json_value(value)


def canonical_bytes(value: Any) -> bytes:
    """Return RFC-8785/JCS bytes using the accepted EngineeringKnowledge helper."""

    return canonicalize_json(canonical_payload(value))


def canonical_digest(value: Any) -> str:
    """Return SHA-256 over canonical RFC-8785/JCS JSON."""

    return canonical_sha256(canonical_payload(value))
