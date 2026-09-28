"""Typed immutable contracts for Phase-10 closed-loop engineering outcomes."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_knowledge.canonical import JSONValue, canonical_sha256

ENGINEERING_OUTCOME_SCHEMA_VERSION = "1"


class EngineeringOutcomeSourceKind(StrEnum):
    PROMOTION = "promotion"
    REPAIR = "repair"
    CAPABILITY_COMPATIBILITY = "capability_compatibility"
    CAPABILITY_ACQUISITION = "capability_acquisition"


class EngineeringOutcomeResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    ROLLED_BACK = "rolled_back"
    INCONCLUSIVE = "inconclusive"


class EngineeringOutcomeAttribution(StrEnum):
    CANDIDATE = "candidate"
    EXTERNAL_PROVIDER = "external_provider"
    EXTERNAL_HARDWARE = "external_hardware"
    ENVIRONMENT = "environment"
    COMPATIBILITY = "compatibility"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


def _text(value: object, field: str, *, max_length: int = 512) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _token(value: object, field: str, *, max_length: int = 160) -> str:
    return _text(value, field, max_length=max_length).casefold()


def _sha256(value: object, field: str) -> str:
    normalized = _text(value, field, max_length=64).casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _git_sha(value: object, field: str) -> str:
    normalized = _text(value, field, max_length=64).casefold()
    if len(normalized) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a hexadecimal Git/release SHA")
    return normalized


def _optional_text(
    value: object | None,
    field: str,
    *,
    max_length: int = 512,
) -> str | None:
    if value is None:
        return None
    return _text(value, field, max_length=max_length)


def _optional_sha256(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field)


def _optional_git_sha(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    return _git_sha(value, field)


def _unique_tokens(
    values: tuple[str, ...],
    field: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not values:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _token(value, f"{field}[{index}]", max_length=200)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _unique_texts(
    values: tuple[str, ...],
    field: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not values:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _text(value, f"{field}[{index}]", max_length=512)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class OutcomeApplicability:
    target_namespace: str
    target_identity: str
    matcher_type: str
    constraint: dict[str, JSONValue]
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=256),
        )
        object.__setattr__(
            self,
            "matcher_type",
            _token(self.matcher_type, "matcher_type"),
        )
        if not isinstance(self.constraint, dict):
            raise TypeError("constraint must be a JSON object")
        canonical_sha256(self.constraint)
        object.__setattr__(self, "constraint", deepcopy(self.constraint))
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")

    def payload(self) -> dict[str, JSONValue]:
        return {
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
            "matcher_type": self.matcher_type,
            "constraint": deepcopy(self.constraint),
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class EngineeringOutcomeV1:
    outcome_id: str
    source_kind: EngineeringOutcomeSourceKind
    source_identity: str
    subject_type: str
    subject_id: str
    subject_digest: str
    result: EngineeringOutcomeResult
    attribution: EngineeringOutcomeAttribution
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    applicability: tuple[OutcomeApplicability, ...]
    observed_at_epoch: float
    producer: str
    change_id: str | None = None
    candidate_id: str | None = None
    candidate_digest: str | None = None
    release_sha: str | None = None
    package_id: str | None = None
    package_version: str | None = None
    package_digest: str | None = None
    schema_version: str = ENGINEERING_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, EngineeringOutcomeSourceKind):
            raise TypeError("source_kind must be an EngineeringOutcomeSourceKind")
        if not isinstance(self.result, EngineeringOutcomeResult):
            raise TypeError("result must be an EngineeringOutcomeResult")
        if not isinstance(self.attribution, EngineeringOutcomeAttribution):
            raise TypeError("attribution must be an EngineeringOutcomeAttribution")
        if self.schema_version != ENGINEERING_OUTCOME_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {ENGINEERING_OUTCOME_SCHEMA_VERSION!r}"
            )

        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity"),
        )
        object.__setattr__(
            self,
            "subject_type",
            _token(self.subject_type, "subject_type"),
        )
        object.__setattr__(
            self,
            "subject_id",
            _text(self.subject_id, "subject_id"),
        )
        object.__setattr__(
            self,
            "subject_digest",
            _sha256(self.subject_digest, "subject_digest"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes", max_items=32),
        )
        object.__setattr__(
            self,
            "evidence_references",
            _unique_texts(
                self.evidence_references,
                "evidence_references",
                max_items=64,
            ),
        )
        if not self.applicability:
            raise ValueError("applicability must not be empty")
        if len(self.applicability) > 32:
            raise ValueError("applicability exceeds 32 items")
        if not all(
            isinstance(item, OutcomeApplicability) for item in self.applicability
        ):
            raise TypeError("applicability must contain OutcomeApplicability values")

        observed = float(self.observed_at_epoch)
        if not math.isfinite(observed) or observed <= 0:
            raise ValueError("observed_at_epoch must be finite and positive")
        object.__setattr__(self, "observed_at_epoch", observed)
        object.__setattr__(self, "producer", _text(self.producer, "producer"))

        object.__setattr__(
            self,
            "change_id",
            _optional_text(self.change_id, "change_id", max_length=240),
        )
        object.__setattr__(
            self,
            "candidate_id",
            _optional_text(self.candidate_id, "candidate_id", max_length=240),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _optional_sha256(self.candidate_digest, "candidate_digest"),
        )
        object.__setattr__(
            self,
            "release_sha",
            _optional_git_sha(self.release_sha, "release_sha"),
        )
        object.__setattr__(
            self,
            "package_id",
            (
                None
                if self.package_id is None
                else _token(self.package_id, "package_id", max_length=240)
            ),
        )
        object.__setattr__(
            self,
            "package_version",
            _optional_text(
                self.package_version,
                "package_version",
                max_length=120,
            ),
        )
        object.__setattr__(
            self,
            "package_digest",
            _optional_sha256(self.package_digest, "package_digest"),
        )

        normalized_id = _text(self.outcome_id, "outcome_id", max_length=80).casefold()
        expected_id = self.expected_outcome_id()
        if normalized_id != expected_id:
            raise ValueError(
                f"outcome_id does not match deterministic identity: {expected_id}"
            )
        object.__setattr__(self, "outcome_id", normalized_id)

    @classmethod
    def create(
        cls,
        *,
        source_kind: EngineeringOutcomeSourceKind,
        source_identity: str,
        subject_type: str,
        subject_id: str,
        subject_digest: str,
        result: EngineeringOutcomeResult,
        attribution: EngineeringOutcomeAttribution,
        reason_codes: tuple[str, ...],
        evidence_references: tuple[str, ...],
        applicability: tuple[OutcomeApplicability, ...],
        observed_at_epoch: float,
        producer: str,
        change_id: str | None = None,
        candidate_id: str | None = None,
        candidate_digest: str | None = None,
        release_sha: str | None = None,
        package_id: str | None = None,
        package_version: str | None = None,
        package_digest: str | None = None,
    ) -> "EngineeringOutcomeV1":
        identity_payload: dict[str, JSONValue] = {
            "schema_version": ENGINEERING_OUTCOME_SCHEMA_VERSION,
            "source_kind": source_kind.value,
            "source_identity": _text(source_identity, "source_identity"),
            "subject_type": _token(subject_type, "subject_type"),
            "subject_id": _text(subject_id, "subject_id"),
            "subject_digest": _sha256(subject_digest, "subject_digest"),
        }
        outcome_id = "outcome_" + canonical_sha256(identity_payload)[:24]
        return cls(
            outcome_id=outcome_id,
            source_kind=source_kind,
            source_identity=source_identity,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_digest=subject_digest,
            result=result,
            attribution=attribution,
            reason_codes=reason_codes,
            evidence_references=evidence_references,
            applicability=applicability,
            observed_at_epoch=observed_at_epoch,
            producer=producer,
            change_id=change_id,
            candidate_id=candidate_id,
            candidate_digest=candidate_digest,
            release_sha=release_sha,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
        )

    def identity_payload(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "source_kind": self.source_kind.value,
            "source_identity": self.source_identity,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "subject_digest": self.subject_digest,
        }

    def expected_outcome_id(self) -> str:
        return "outcome_" + canonical_sha256(self.identity_payload())[:24]

    def canonical_payload(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "outcome_id": self.outcome_id,
            "source_kind": self.source_kind.value,
            "source_identity": self.source_identity,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "subject_digest": self.subject_digest,
            "result": self.result.value,
            "attribution": self.attribution.value,
            "reason_codes": list(self.reason_codes),
            "evidence_references": list(self.evidence_references),
            "applicability": [item.payload() for item in self.applicability],
            "observed_at_epoch": self.observed_at_epoch,
            "producer": self.producer,
            "lineage": {
                "change_id": self.change_id,
                "candidate_id": self.candidate_id,
                "candidate_digest": self.candidate_digest,
                "release_sha": self.release_sha,
                "package_id": self.package_id,
                "package_version": self.package_version,
                "package_digest": self.package_digest,
            },
        }

    @property
    def digest(self) -> str:
        return canonical_sha256(self.canonical_payload())
