"""RFC-8785 canonicalization helpers for EngineeringKnowledge facets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, TypeAlias

import rfc8785

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class EngineeringKnowledgeCanonicalizationError(ValueError):
    """A JSON payload cannot be represented by the canonical integrity contract."""


class EngineeringKnowledgeDuplicateKeyError(
    EngineeringKnowledgeCanonicalizationError
):
    """A JSON object contains duplicate property names."""


def _strict_object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EngineeringKnowledgeDuplicateKeyError(
                f"duplicate JSON property name: {key!r}"
            )
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise EngineeringKnowledgeCanonicalizationError(
        f"non-finite JSON number is not permitted: {token}"
    )


def parse_json_object(payload_json: str) -> dict[str, JSONValue]:
    """Parse one JSON object while rejecting duplicate keys and non-I-JSON numbers."""

    text = str(payload_json).strip()
    if not text:
        raise EngineeringKnowledgeCanonicalizationError(
            "payload_json must not be empty"
        )
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_constant,
        )
    except EngineeringKnowledgeCanonicalizationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EngineeringKnowledgeCanonicalizationError(
            "payload_json must contain valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise EngineeringKnowledgeCanonicalizationError(
            "payload_json must contain a JSON object"
        )
    return parsed


def canonicalize_json(value: JSONValue) -> bytes:
    """Return RFC-8785/JCS UTF-8 bytes or fail closed."""

    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise EngineeringKnowledgeCanonicalizationError(
            "payload cannot be canonicalized under RFC 8785"
        ) from exc


def canonical_sha256(value: JSONValue) -> str:
    """Return SHA-256 over RFC-8785 canonical bytes."""

    return hashlib.sha256(canonicalize_json(value)).hexdigest()


def canonicalize_json_object_text(
    payload_json: str,
) -> tuple[dict[str, JSONValue], bytes, str]:
    """Parse, canonicalize and digest one JSON object."""

    parsed = parse_json_object(payload_json)
    canonical = canonicalize_json(parsed)
    return parsed, canonical, hashlib.sha256(canonical).hexdigest()
