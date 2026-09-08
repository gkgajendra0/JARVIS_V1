from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)


def _utc(value: datetime | None, *, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime when provided")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _validated_value(value_type: ValueType, value: Any) -> Any:
    if value_type is ValueType.TEXT:
        if not isinstance(value, str):
            raise TypeError("text memory value must be a string")
        return value
    if value_type is ValueType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("number memory value must be an int or float")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("number memory value must be finite")
        return value
    if value_type is ValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise TypeError("boolean memory value must be a bool")
        return value
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError("json memory value must be JSON-serializable") from exc
    return value


def canonical_value_json(value_type: ValueType, value: Any) -> str:
    validated = _validated_value(value_type, value)
    return json.dumps(
        validated,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class SemanticAssertionDraft:
    subject_scope: str
    subject: str
    predicate: str
    value_type: ValueType
    value: Any
    normalized_text: str
    freshness_class: FreshnessClass
    sensitivity: Sensitivity
    verification_state: VerificationState = VerificationState.UNVERIFIED
    confidence: float | None = None
    valid_from: datetime | None = None
    last_verified_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("subject_scope", "subject", "predicate", "normalized_text"):
            object.__setattr__(self, name, _text(getattr(self, name), name=name))
        if not isinstance(self.value_type, ValueType):
            raise TypeError("value_type must be a ValueType")
        if not isinstance(self.freshness_class, FreshnessClass):
            raise TypeError("freshness_class must be a FreshnessClass")
        if not isinstance(self.sensitivity, Sensitivity):
            raise TypeError("sensitivity must be a Sensitivity")
        if self.sensitivity is Sensitivity.SECRET_PROHIBITED:
            raise ValueError("secret-prohibited content cannot become semantic memory")
        if not isinstance(self.verification_state, VerificationState):
            raise TypeError("verification_state must be a VerificationState")

        _validated_value(self.value_type, self.value)
        if self.confidence is not None:
            if not isinstance(self.confidence, int | float) or isinstance(
                self.confidence, bool
            ):
                raise TypeError("confidence must be numeric when provided")
            confidence = float(self.confidence)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", confidence)

        object.__setattr__(
            self,
            "valid_from",
            _utc(self.valid_from, name="valid_from"),
        )
        object.__setattr__(
            self,
            "last_verified_at",
            _utc(self.last_verified_at, name="last_verified_at"),
        )
        if (
            self.verification_state is VerificationState.VERIFIED
            and self.last_verified_at is None
        ):
            raise ValueError("verified assertion requires last_verified_at")
        if (
            self.verification_state is VerificationState.UNVERIFIED
            and self.last_verified_at is not None
        ):
            raise ValueError("unverified assertion cannot have last_verified_at")

    @property
    def value_json(self) -> str:
        return canonical_value_json(self.value_type, self.value)


@dataclass(frozen=True, slots=True)
class SemanticAssertionRecord:
    assertion_id: str
    subject_scope: str
    subject: str
    predicate: str
    value_type: ValueType
    value: Any
    normalized_text: str
    source_id: str
    valid_from: datetime | None
    valid_to: datetime | None
    system_from: datetime
    system_to: datetime | None
    last_verified_at: datetime | None
    state: AssertionState
    supersedes_id: str | None
    verification_state: VerificationState
    confidence: float | None
    freshness_class: FreshnessClass
    sensitivity: Sensitivity
    created_at: datetime
    updated_at: datetime
