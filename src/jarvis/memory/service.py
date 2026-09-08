"""Sole public facade for explicit canonical semantic-memory operations."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from number_parser import parse as parse_number_words

from .assertions import SemanticAssertionDraft, SemanticAssertionRecord
from .lifecycle import MemoryLifecycleService
from .provenance import MemorySource
from .query import CanonicalMemoryReader
from .types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)

_PERSONAL_SCOPE = "personal"
_OWNER_SUBJECT = "owner"


class MemoryServiceError(RuntimeError):
    pass


class MemoryAlreadyExistsError(MemoryServiceError):
    pass


class MemoryNotFoundError(MemoryServiceError):
    pass


class MemoryAmbiguousError(MemoryServiceError):
    pass


def normalize_memory_surface(value: str) -> str:
    """Normalize user-facing memory text without introducing fuzzy semantics.

    Spoken number words are folded to digits before canonical key comparison so
    equivalent ASR/model forms such as ``phase four`` and ``phase 4`` resolve to
    the same deterministic key. English normalization always runs; Hindi number
    normalization is applied only when Devanagari is present.
    """

    if not isinstance(value, str):
        raise TypeError("memory surface must be a string")
    normalized = unicodedata.normalize("NFKC", value.strip())
    normalized = parse_number_words(normalized, language="en")
    if any("\u0900" <= character <= "\u097f" for character in normalized):
        normalized = parse_number_words(normalized, language="hi")
    return normalized.casefold()


def canonical_memory_predicate(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("predicate must be a string")
    normalized_input = normalize_memory_surface(value)
    characters: list[str] = []
    previous_was_separator = False
    for character in normalized_input:
        category_group = unicodedata.category(character)[0]
        if character == "_" or category_group in {"L", "M", "N"}:
            characters.append(character)
            previous_was_separator = False
            continue
        if characters and not previous_was_separator:
            characters.append("_")
            previous_was_separator = True
    normalized = "".join(characters).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    if not normalized:
        raise ValueError("predicate must contain letters or digits")
    if len(normalized) > 96:
        raise ValueError("predicate must not exceed 96 characters")
    return normalized


def _text_value(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("memory value must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("memory value must not be empty")
    return normalized


def _normalized_text(predicate: str, value: str) -> str:
    human_key = predicate.replace("_", " ")
    return f"{human_key}: {value}"


@dataclass(frozen=True, slots=True)
class ExplicitMemoryResult:
    predicate: str
    record: SemanticAssertionRecord


class MemoryService:
    """Own explicit high-level memory semantics above lifecycle/query primitives."""

    def __init__(
        self,
        lifecycle: MemoryLifecycleService,
        reader: CanonicalMemoryReader,
    ) -> None:
        self._lifecycle = lifecycle
        self._reader = reader

    async def remember_text(
        self,
        *,
        predicate: str,
        value: str,
        source: MemorySource,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
        freshness_class: FreshnessClass = FreshnessClass.CHANGEABLE,
    ) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        text = _text_value(value)
        self._validate_write_policy(source, sensitivity, freshness_class)
        existing = await self._reader.find_current_exact(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=key,
        )
        if existing:
            raise MemoryAlreadyExistsError(
                f"current memory already exists for predicate {key!r}; use correction"
            )
        record = await self._lifecycle.create(
            self._draft(
                predicate=key,
                value=text,
                sensitivity=sensitivity,
                freshness_class=freshness_class,
            ),
            source,
            reason_code="explicit_owner_remember",
        )
        return ExplicitMemoryResult(predicate=key, record=record)

    async def correct_text(
        self,
        *,
        predicate: str,
        value: str,
        source: MemorySource,
        sensitivity: Sensitivity | None = None,
        freshness_class: FreshnessClass | None = None,
    ) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        text = _text_value(value)
        current = await self._require_one_current(key)
        resolved_sensitivity = sensitivity or current.sensitivity
        resolved_freshness = freshness_class or current.freshness_class
        self._validate_write_policy(source, resolved_sensitivity, resolved_freshness)
        record = await self._lifecycle.correct(
            current.assertion_id,
            self._draft(
                predicate=key,
                value=text,
                sensitivity=resolved_sensitivity,
                freshness_class=resolved_freshness,
            ),
            source,
            reason_code="explicit_owner_correction",
        )
        return ExplicitMemoryResult(predicate=key, record=record)

    async def forget_exact(
        self,
        *,
        predicate: str,
        source: MemorySource,
    ) -> str:
        key = canonical_memory_predicate(predicate)
        current = await self._require_one_current(key)
        self._validate_owner_explicit_source(source, current.sensitivity)
        forgotten = await self._lifecycle.forget(
            current.assertion_id,
            source,
            reason_code="explicit_owner_request",
        )
        if not forgotten:
            raise MemoryNotFoundError(f"memory disappeared before forget for {key!r}")
        after = await self._reader.find_current_exact(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=key,
        )
        if after:
            raise MemoryServiceError(
                f"forget verification still found current memory for predicate {key!r}"
            )
        return key

    async def inspect_exact(self, *, predicate: str) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        record = await self._require_one_current(key)
        return ExplicitMemoryResult(predicate=key, record=record)

    async def _require_one_current(self, predicate: str) -> SemanticAssertionRecord:
        matches = await self._reader.find_current_exact(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=predicate,
        )
        if not matches:
            raise MemoryNotFoundError(f"no current memory for predicate {predicate!r}")
        if len(matches) != 1:
            raise MemoryAmbiguousError(
                f"multiple current memories exist for predicate {predicate!r}"
            )
        return matches[0]

    @staticmethod
    def _draft(
        *,
        predicate: str,
        value: str,
        sensitivity: Sensitivity,
        freshness_class: FreshnessClass,
    ) -> SemanticAssertionDraft:
        return SemanticAssertionDraft(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=predicate,
            value_type=ValueType.TEXT,
            value=value,
            normalized_text=_normalized_text(predicate, value),
            freshness_class=freshness_class,
            sensitivity=sensitivity,
        )

    @classmethod
    def _validate_write_policy(
        cls,
        source: MemorySource,
        sensitivity: Sensitivity,
        freshness_class: FreshnessClass,
    ) -> None:
        cls._validate_owner_explicit_source(source, sensitivity)
        if not isinstance(freshness_class, FreshnessClass):
            raise TypeError("freshness_class must be a FreshnessClass")

    @staticmethod
    def _validate_owner_explicit_source(
        source: MemorySource,
        sensitivity: Sensitivity,
    ) -> None:
        if not isinstance(source, MemorySource):
            raise TypeError("source must be a MemorySource")
        if source.source_class is not MemorySourceClass.OWNER_EXPLICIT:
            raise MemoryServiceError(
                "explicit memory mutation requires owner-explicit source provenance"
            )
        if source.authority_class is not AuthorityClass.OWNER_EXPLICIT:
            raise MemoryServiceError(
                "explicit memory mutation requires owner-explicit authority"
            )
        if not isinstance(sensitivity, Sensitivity):
            raise TypeError("sensitivity must be a Sensitivity")
        if sensitivity is Sensitivity.SECRET_PROHIBITED:
            raise ValueError("secret-prohibited content cannot be remembered")
        if source.sensitivity is not sensitivity:
            raise MemoryServiceError(
                "explicit memory source sensitivity must match the stored memory"
            )
