"""Question-bound personal evidence contracts; canonical storage retains truth."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.personal_learning_scope import (
    LEGACY_FACETS,
    POLICY_VERSION,
    SUPPRESSION_KEYS,
)

from .assertions import SemanticAssertionRecord
from .types import AssertionState, FreshnessClass, Sensitivity, ValueType

ScopeKey = Literal[
    "owned_item.vehicle",
    "owned_item.device",
    "owned_item.other",
    "food_preference",
    "response_preference",
    "routine",
    "goal",
]


class PersonalContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope_key: ScopeKey
    target_quote: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_target(cls, value):
        if isinstance(value, dict) and "target_quote" in value:
            quote = value["target_quote"]
            if (
                type(quote) is not str
                or not quote.strip()
                or len(quote.encode("utf-8")) > 256
                or value.get("scope_key") in ("food_preference", "response_preference")
            ):
                raise ValueError("invalid context target")
        return value


def parse_context_requests(
    requests: object, *, question: str
) -> tuple[PersonalContextRequest, ...]:
    if type(requests) is not list or not 1 <= len(requests) <= 4:
        raise ValueError("invalid context requests")
    if not isinstance(question, str):
        raise ValueError("invalid current question")  # noqa: TRY004 - closed parser contract
    if frozenset(get_args(ScopeKey)) != SUPPRESSION_KEYS:
        raise ValueError("context scope registry mismatch")
    parsed = []
    seen = set()
    for item in requests:
        if isinstance(item, PersonalContextRequest):
            item = item.model_dump(exclude_unset=True)
        request = PersonalContextRequest.model_validate(item, strict=True)
        quote = request.target_quote
        if quote is not None and quote not in question:
            raise ValueError("context target is not current question text")
        key = (request.scope_key, quote)
        if key in seen:
            raise ValueError("duplicate context request")
        seen.add(key)
        parsed.append(request)
    return tuple(parsed)


@dataclass(frozen=True)
class ScopedContextSnapshot:
    entries: tuple[tuple[SemanticAssertionRecord, str], ...]
    suppression: tuple[tuple[str, int, bool], ...]


@dataclass(frozen=True)
class ContextProjection:
    status: str
    reason: str | None
    facts: tuple[dict[str, object], ...]
    selected: tuple[SemanticAssertionRecord, ...]
    scope_keys: tuple[str, ...]
    signature: str


def _json_default(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    raise ValueError("unsupported context metadata")


def context_scope_signature(
    snapshot: ScopedContextSnapshot, scope_keys: tuple[str, ...]
) -> str:
    rows = sorted(
        (
            (scope, asdict(record))
            for record, scope in snapshot.entries
            if scope in scope_keys
        ),
        key=lambda pair: (pair[0], pair[1]["predicate"], pair[1]["assertion_id"]),
    )
    epochs = {k: (epoch, suppressed) for k, epoch, suppressed in snapshot.suppression}
    payload = [rows, [(k, *epochs.get(k, (0, False))) for k in sorted(scope_keys)]]
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        ).encode()
    ).hexdigest()


def _current_label(record, scope):
    value = record.value
    if (
        record.value_type is not ValueType.JSON
        or not isinstance(value, dict)
        or value.get("schema") != POLICY_VERSION
        or value.get("category") != scope.split(".")[0]
        or (
            scope.startswith("owned_item.") and value.get("kind") != scope.split(".")[1]
        )
    ):
        return None
    label = value.get("label")
    return (
        label
        if isinstance(label, str) and label.strip() and len(label) <= 240
        else None
    )


def _normalize_label(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def project_personal_context(
    snapshot: ScopedContextSnapshot, requests: tuple[PersonalContextRequest, ...]
) -> ContextProjection:
    scopes = tuple(sorted({r.scope_key for r in requests}))

    def result(status, reason=None, facts=(), selected=(), signature=""):
        return ContextProjection(
            status, reason, tuple(facts), tuple(selected), scopes, signature
        )

    try:
        if len(snapshot.entries) > 32:
            return result("unavailable", "storage_unavailable")
        chosen = {}
        clarification = None
        missing = False
        for request in requests:
            candidates = [
                r for r, scope in snapshot.entries if scope == request.scope_key
            ]
            if request.target_quote is not None:
                labels = [(r, _current_label(r, request.scope_key)) for r in candidates]
                candidates = [
                    r
                    for r, label in labels
                    if label is not None
                    and _normalize_label(label)
                    == _normalize_label(request.target_quote)
                ]
                if len(candidates) > 1:
                    clarification = "ambiguous_target"
                elif not candidates and any(label is None for _, label in labels):
                    clarification = "unresolved_target"
            if not candidates:
                missing = True
            for r in candidates:
                chosen[r.assertion_id] = (r, request.scope_key)
        if clarification:
            return result("clarification_required", clarification)
        if missing:
            return result("no_match")
        if len(chosen) > 4:
            return result("clarification_required", "narrow_request")
        facts = []
        selected = []
        for ordinal, (r, scope) in enumerate(
            sorted(
                chosen.values(),
                key=lambda pair: (pair[1], pair[0].predicate, pair[0].assertion_id),
            ),
            start=1,
        ):
            if (
                r.subject_scope != "personal"
                or r.subject != "owner"
                or r.state is not AssertionState.ACTIVE
                or r.valid_to is not None
                or r.sensitivity is not Sensitivity.STANDARD
                or r.freshness_class is FreshnessClass.TIME_SENSITIVE
                or not isinstance(r.normalized_text, str)
                or not r.normalized_text
            ):
                return result("unavailable", "storage_unavailable")
            text = r.normalized_text
            if r.value_type is ValueType.TEXT and r.predicate not in LEGACY_FACETS:
                if not isinstance(r.value, str) or not r.value:
                    return result("unavailable", "storage_unavailable")
                # Registered corrections retain scope, not the opaque display prefix.
                text = f"{scope}: {r.value}"
            fact = {
                "evidence_ref": ordinal,
                "scope_key": scope,
                "text": text,
                "recorded_at": _json_default(r.system_from),
                "freshness": "last_known",
            }
            if isinstance(r.value, dict) and r.value.get("schema") == POLICY_VERSION:
                state = r.value.get("state")
                if state not in {"owned", "not_owned", "active", "completed"}:
                    return result("unavailable", "storage_unavailable")
                fact["state"] = state
            facts.append(fact)
            selected.append(r)
        encoded = json.dumps(
            facts, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(encoded) > 1800:
            return result("clarification_required", "narrow_request")
        return result(
            "selected",
            facts=facts,
            selected=selected,
            signature=context_scope_signature(snapshot, scopes),
        )
    except (TypeError, ValueError, AttributeError):
        return result("unavailable", "storage_unavailable")
