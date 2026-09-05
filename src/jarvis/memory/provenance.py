from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .types import AuthorityClass, MemorySourceClass, Sensitivity


def _normalize_utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MemorySource:
    source_id: str
    source_class: MemorySourceClass
    canonical_ref: str
    observed_at: datetime
    authority_class: AuthorityClass
    sensitivity: Sensitivity
    created_at: datetime
    source_created_at: datetime | None = None
    evidence_text: str | None = None
    evidence_hash: str | None = None
    external_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_id", "canonical_ref"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, normalized)

        if not isinstance(self.source_class, MemorySourceClass):
            raise TypeError("source_class must be a MemorySourceClass")
        if not isinstance(self.authority_class, AuthorityClass):
            raise TypeError("authority_class must be an AuthorityClass")
        if not isinstance(self.sensitivity, Sensitivity):
            raise TypeError("sensitivity must be a Sensitivity")

        object.__setattr__(
            self,
            "observed_at",
            _normalize_utc(self.observed_at, name="observed_at"),
        )
        object.__setattr__(
            self,
            "created_at",
            _normalize_utc(self.created_at, name="created_at"),
        )
        if self.source_created_at is not None:
            object.__setattr__(
                self,
                "source_created_at",
                _normalize_utc(self.source_created_at, name="source_created_at"),
            )

        for name in ("evidence_text", "evidence_hash", "external_ref"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string when provided")
            normalized = value.strip()
            object.__setattr__(self, name, normalized or None)

        if self.evidence_hash is not None:
            normalized_hash = self.evidence_hash.casefold()
            if len(normalized_hash) != 64 or any(
                char not in "0123456789abcdef" for char in normalized_hash
            ):
                raise ValueError("evidence_hash must be a SHA-256 hex digest")
            object.__setattr__(self, "evidence_hash", normalized_hash)
