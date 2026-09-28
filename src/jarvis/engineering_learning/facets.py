"""Registered Phase-10 EngineeringKnowledge learning facet schemas."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass

from jarvis.engineering_knowledge.canonical import JSONValue, canonical_sha256
from jarvis.engineering_knowledge.registry import (
    FacetApplicabilityConstraint,
    FacetSchemaKey,
    FacetValidationError,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
)

ENGINEERING_OUTCOME_FACET_TYPE = "jarvis.engineering.outcome"
ENGINEERING_OUTCOME_V1_SCHEMA_ID = (
    "urn:jarvis:engineering-knowledge:engineering-outcome:v1"
)
ENGINEERING_OUTCOME_V1_SCHEMA_VERSION = "1"

ENGINEERING_REGRESSION_FACET_TYPE = "jarvis.engineering.regression"
ENGINEERING_REGRESSION_V1_SCHEMA_ID = (
    "urn:jarvis:engineering-knowledge:engineering-regression:v1"
)
ENGINEERING_REGRESSION_V1_SCHEMA_VERSION = "1"

ENGINEERING_COMPATIBILITY_FACET_TYPE = "jarvis.engineering.compatibility"
ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID = (
    "urn:jarvis:engineering-knowledge:engineering-compatibility:v1"
)
ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION = "1"

_LINEAGE_FIELDS = {
    "change_id",
    "candidate_id",
    "candidate_digest",
    "release_sha",
    "package_id",
    "package_version",
    "package_digest",
}
_COMMON_FIELDS = {
    "outcome_id",
    "source_kind",
    "source_identity",
    "subject_type",
    "subject_id",
    "subject_digest",
    "reason_codes",
    "evidence_references",
    "applicability",
    "revalidation",
}

ENGINEERING_OUTCOME_V1_SCHEMA: dict[str, JSONValue] = {
    "facet_type": ENGINEERING_OUTCOME_FACET_TYPE,
    "schema_id": ENGINEERING_OUTCOME_V1_SCHEMA_ID,
    "schema_version": ENGINEERING_OUTCOME_V1_SCHEMA_VERSION,
    "additional_properties": False,
    "required": sorted(
        _COMMON_FIELDS
        | {
            "result",
            "attribution",
            "observed_at_epoch",
            "producer",
            "lineage",
        }
    ),
    "properties": {
        "result": [item.value for item in EngineeringOutcomeResult],
        "attribution": [item.value for item in EngineeringOutcomeAttribution],
        "source_kind": [item.value for item in EngineeringOutcomeSourceKind],
        "revalidation_strategy": ["source_outcome"],
    },
}

ENGINEERING_REGRESSION_V1_SCHEMA: dict[str, JSONValue] = {
    "facet_type": ENGINEERING_REGRESSION_FACET_TYPE,
    "schema_id": ENGINEERING_REGRESSION_V1_SCHEMA_ID,
    "schema_version": ENGINEERING_REGRESSION_V1_SCHEMA_VERSION,
    "additional_properties": False,
    "required": sorted(_COMMON_FIELDS | {"result", "attribution"}),
    "properties": {
        "result": [
            EngineeringOutcomeResult.FAILURE.value,
            EngineeringOutcomeResult.ROLLED_BACK.value,
        ],
        "attribution": [EngineeringOutcomeAttribution.CANDIDATE.value],
        "source_kind": [item.value for item in EngineeringOutcomeSourceKind],
        "revalidation_strategy": ["source_outcome"],
    },
}

ENGINEERING_COMPATIBILITY_V1_SCHEMA: dict[str, JSONValue] = {
    "facet_type": ENGINEERING_COMPATIBILITY_FACET_TYPE,
    "schema_id": ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID,
    "schema_version": ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION,
    "additional_properties": False,
    "required": sorted(_COMMON_FIELDS | {"verdict"}),
    "properties": {
        "verdict": ["ready", "blocked", "restart_required"],
        "source_kind": [
            EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY.value,
        ],
        "revalidation_strategy": ["source_outcome"],
    },
}

ENGINEERING_OUTCOME_V1_SCHEMA_DIGEST = canonical_sha256(
    ENGINEERING_OUTCOME_V1_SCHEMA
)
ENGINEERING_REGRESSION_V1_SCHEMA_DIGEST = canonical_sha256(
    ENGINEERING_REGRESSION_V1_SCHEMA
)
ENGINEERING_COMPATIBILITY_V1_SCHEMA_DIGEST = canonical_sha256(
    ENGINEERING_COMPATIBILITY_V1_SCHEMA
)


def _exact_keys(
    value: dict[str, JSONValue],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise FacetValidationError(
            f"{field} keys mismatch: missing={missing}, extra={extra}"
        )


def _object(value: JSONValue, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise FacetValidationError(f"{field} must be a JSON object")
    return value


def _string(
    value: JSONValue,
    field: str,
    *,
    max_length: int,
    casefold: bool = False,
) -> str:
    if not isinstance(value, str):
        raise FacetValidationError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise FacetValidationError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise FacetValidationError(f"{field} exceeds {max_length} characters")
    if normalized != value:
        raise FacetValidationError(f"{field} must not contain outer whitespace")
    return normalized.casefold() if casefold else normalized


def _nullable_string(
    value: JSONValue,
    field: str,
    *,
    max_length: int,
    casefold: bool = False,
) -> str | None:
    if value is None:
        return None
    return _string(
        value,
        field,
        max_length=max_length,
        casefold=casefold,
    )


def _sha256(value: JSONValue, field: str) -> str:
    normalized = _string(value, field, max_length=64, casefold=True)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise FacetValidationError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _nullable_sha256(value: JSONValue, field: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field)


def _nullable_release_sha(value: JSONValue, field: str) -> str | None:
    if value is None:
        return None
    normalized = _string(value, field, max_length=64, casefold=True)
    if len(normalized) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise FacetValidationError(
            f"{field} must be a hexadecimal Git/release SHA"
        )
    return normalized


def _positive_number(value: JSONValue, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacetValidationError(f"{field} must be a number")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved <= 0:
        raise FacetValidationError(f"{field} must be finite and positive")
    return resolved


def _string_list(
    value: JSONValue,
    field: str,
    *,
    max_items: int,
    tokens: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FacetValidationError(f"{field} must be a non-empty list")
    if len(value) > max_items:
        raise FacetValidationError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _string(
            item,
            f"{field}[{index}]",
            max_length=512 if not tokens else 200,
            casefold=tokens,
        )
        for index, item in enumerate(value)
    )
    if len(set(normalized)) != len(normalized):
        raise FacetValidationError(f"{field} must not contain duplicates")
    return normalized


def _applicability(
    value: JSONValue,
) -> tuple[FacetApplicabilityConstraint, ...]:
    if not isinstance(value, list) or not value:
        raise FacetValidationError("applicability must be a non-empty list")
    if len(value) > 32:
        raise FacetValidationError("applicability exceeds 32 items")
    result: list[FacetApplicabilityConstraint] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"applicability[{index}]")
        _exact_keys(
            item,
            {
                "target_namespace",
                "target_identity",
                "matcher_type",
                "constraint",
                "required",
            },
            f"applicability[{index}]",
        )
        constraint = _object(
            item["constraint"],
            f"applicability[{index}].constraint",
        )
        required = item["required"]
        if not isinstance(required, bool):
            raise FacetValidationError(
                f"applicability[{index}].required must be a bool"
            )
        result.append(
            FacetApplicabilityConstraint(
                target_namespace=_string(
                    item["target_namespace"],
                    f"applicability[{index}].target_namespace",
                    max_length=160,
                    casefold=True,
                ),
                target_identity=_string(
                    item["target_identity"],
                    f"applicability[{index}].target_identity",
                    max_length=256,
                ),
                matcher_type=_string(
                    item["matcher_type"],
                    f"applicability[{index}].matcher_type",
                    max_length=100,
                    casefold=True,
                ),
                constraint=deepcopy(constraint),
                required=required,
            )
        )
    if not any(item.required for item in result):
        raise FacetValidationError(
            "at least one applicability constraint must be required"
        )
    return tuple(result)


def _revalidation(
    value: JSONValue,
    *,
    source_kind: str,
    source_identity: str,
) -> dict[str, JSONValue]:
    item = _object(value, "revalidation")
    _exact_keys(
        item,
        {"strategy", "source_kind", "source_identity"},
        "revalidation",
    )
    strategy = _string(
        item["strategy"],
        "revalidation.strategy",
        max_length=80,
        casefold=True,
    )
    if strategy != "source_outcome":
        raise FacetValidationError(
            "revalidation.strategy must be 'source_outcome'"
        )
    if (
        _string(
            item["source_kind"],
            "revalidation.source_kind",
            max_length=100,
            casefold=True,
        )
        != source_kind
    ):
        raise FacetValidationError(
            "revalidation.source_kind must match source_kind"
        )
    if (
        _string(
            item["source_identity"],
            "revalidation.source_identity",
            max_length=512,
        )
        != source_identity
    ):
        raise FacetValidationError(
            "revalidation.source_identity must match source_identity"
        )
    return dict(item)


def _common(
    payload: dict[str, JSONValue],
) -> tuple[
    str,
    str,
    str,
    str,
    str,
    tuple[str, ...],
    tuple[str, ...],
    tuple[FacetApplicabilityConstraint, ...],
    dict[str, JSONValue],
]:
    outcome_id = _string(
        payload["outcome_id"],
        "outcome_id",
        max_length=80,
        casefold=True,
    )
    if not outcome_id.startswith("outcome_"):
        raise FacetValidationError("outcome_id must use outcome_ prefix")
    source_kind = _string(
        payload["source_kind"],
        "source_kind",
        max_length=100,
        casefold=True,
    )
    if source_kind not in {item.value for item in EngineeringOutcomeSourceKind}:
        raise FacetValidationError("source_kind is unsupported")
    source_identity = _string(
        payload["source_identity"],
        "source_identity",
        max_length=512,
    )
    subject_type = _string(
        payload["subject_type"],
        "subject_type",
        max_length=160,
        casefold=True,
    )
    subject_id = _string(payload["subject_id"], "subject_id", max_length=512)
    _sha256(payload["subject_digest"], "subject_digest")
    reason_codes = _string_list(
        payload["reason_codes"],
        "reason_codes",
        max_items=32,
        tokens=True,
    )
    evidence = _string_list(
        payload["evidence_references"],
        "evidence_references",
        max_items=64,
    )
    applicability = _applicability(payload["applicability"])
    revalidation = _revalidation(
        payload["revalidation"],
        source_kind=source_kind,
        source_identity=source_identity,
    )
    return (
        outcome_id,
        source_kind,
        source_identity,
        subject_type,
        subject_id,
        reason_codes,
        evidence,
        applicability,
        revalidation,
    )


@dataclass(frozen=True, slots=True)
class EngineeringOutcomeV1Handler:
    @property
    def key(self) -> FacetSchemaKey:
        return FacetSchemaKey(
            ENGINEERING_OUTCOME_FACET_TYPE,
            ENGINEERING_OUTCOME_V1_SCHEMA_ID,
            ENGINEERING_OUTCOME_V1_SCHEMA_VERSION,
        )

    @property
    def schema_descriptor(self) -> dict[str, JSONValue]:
        return deepcopy(ENGINEERING_OUTCOME_V1_SCHEMA)

    @property
    def schema_digest(self) -> str:
        return ENGINEERING_OUTCOME_V1_SCHEMA_DIGEST

    @property
    def protected_fields(self) -> tuple[str, ...]:
        return ()

    def validate_payload(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        _exact_keys(
            payload,
            _COMMON_FIELDS
            | {
                "result",
                "attribution",
                "observed_at_epoch",
                "producer",
                "lineage",
            },
            "engineering outcome",
        )
        (
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = _common(payload)

        result = _string(
            payload["result"],
            "result",
            max_length=80,
            casefold=True,
        )
        if result not in {item.value for item in EngineeringOutcomeResult}:
            raise FacetValidationError("result is unsupported")
        attribution = _string(
            payload["attribution"],
            "attribution",
            max_length=100,
            casefold=True,
        )
        if attribution not in {
            item.value for item in EngineeringOutcomeAttribution
        }:
            raise FacetValidationError("attribution is unsupported")
        _positive_number(payload["observed_at_epoch"], "observed_at_epoch")
        _string(payload["producer"], "producer", max_length=240)

        lineage = _object(payload["lineage"], "lineage")
        _exact_keys(lineage, _LINEAGE_FIELDS, "lineage")
        _nullable_string(lineage["change_id"], "lineage.change_id", max_length=240)
        _nullable_string(
            lineage["candidate_id"],
            "lineage.candidate_id",
            max_length=240,
        )
        _nullable_sha256(
            lineage["candidate_digest"],
            "lineage.candidate_digest",
        )
        _nullable_release_sha(lineage["release_sha"], "lineage.release_sha")
        _nullable_string(
            lineage["package_id"],
            "lineage.package_id",
            max_length=240,
            casefold=True,
        )
        _nullable_string(
            lineage["package_version"],
            "lineage.package_version",
            max_length=120,
        )
        _nullable_sha256(lineage["package_digest"], "lineage.package_digest")
        return payload

    def duplicate_key(self, payload: dict[str, JSONValue]) -> str:
        return "sha256:" + canonical_sha256(
            {
                "outcome_id": payload["outcome_id"],
                "subject_digest": payload["subject_digest"],
            }
        )

    def searchable_text(self, payload: dict[str, JSONValue]) -> str:
        common = _common(payload)
        return " ".join(
            dict.fromkeys(
                (
                    common[1],
                    common[3],
                    common[4],
                    _string(payload["result"], "result", max_length=80),
                    _string(
                        payload["attribution"],
                        "attribution",
                        max_length=100,
                    ),
                    *common[5],
                )
            )
        )

    def applicability(
        self,
        payload: dict[str, JSONValue],
    ) -> tuple[FacetApplicabilityConstraint, ...]:
        return _applicability(payload["applicability"])

    def revalidation_rules(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        common = _common(payload)
        return common[8]


@dataclass(frozen=True, slots=True)
class EngineeringRegressionV1Handler:
    @property
    def key(self) -> FacetSchemaKey:
        return FacetSchemaKey(
            ENGINEERING_REGRESSION_FACET_TYPE,
            ENGINEERING_REGRESSION_V1_SCHEMA_ID,
            ENGINEERING_REGRESSION_V1_SCHEMA_VERSION,
        )

    @property
    def schema_descriptor(self) -> dict[str, JSONValue]:
        return deepcopy(ENGINEERING_REGRESSION_V1_SCHEMA)

    @property
    def schema_digest(self) -> str:
        return ENGINEERING_REGRESSION_V1_SCHEMA_DIGEST

    @property
    def protected_fields(self) -> tuple[str, ...]:
        return ()

    def validate_payload(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        _exact_keys(
            payload,
            _COMMON_FIELDS | {"result", "attribution"},
            "engineering regression",
        )
        _common(payload)
        result = _string(
            payload["result"],
            "result",
            max_length=80,
            casefold=True,
        )
        if result not in {
            EngineeringOutcomeResult.FAILURE.value,
            EngineeringOutcomeResult.ROLLED_BACK.value,
        }:
            raise FacetValidationError(
                "regression result must be failure or rolled_back"
            )
        attribution = _string(
            payload["attribution"],
            "attribution",
            max_length=100,
            casefold=True,
        )
        if attribution != EngineeringOutcomeAttribution.CANDIDATE.value:
            raise FacetValidationError(
                "regression attribution must be candidate"
            )
        return payload

    def duplicate_key(self, payload: dict[str, JSONValue]) -> str:
        return "sha256:" + canonical_sha256(
            {
                "outcome_id": payload["outcome_id"],
                "subject_digest": payload["subject_digest"],
                "result": payload["result"],
            }
        )

    def searchable_text(self, payload: dict[str, JSONValue]) -> str:
        common = _common(payload)
        return " ".join(
            dict.fromkeys(
                (
                    "regression",
                    common[3],
                    common[4],
                    _string(payload["result"], "result", max_length=80),
                    *common[5],
                )
            )
        )

    def applicability(
        self,
        payload: dict[str, JSONValue],
    ) -> tuple[FacetApplicabilityConstraint, ...]:
        return _applicability(payload["applicability"])

    def revalidation_rules(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        return _common(payload)[8]


@dataclass(frozen=True, slots=True)
class EngineeringCompatibilityV1Handler:
    @property
    def key(self) -> FacetSchemaKey:
        return FacetSchemaKey(
            ENGINEERING_COMPATIBILITY_FACET_TYPE,
            ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID,
            ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION,
        )

    @property
    def schema_descriptor(self) -> dict[str, JSONValue]:
        return deepcopy(ENGINEERING_COMPATIBILITY_V1_SCHEMA)

    @property
    def schema_digest(self) -> str:
        return ENGINEERING_COMPATIBILITY_V1_SCHEMA_DIGEST

    @property
    def protected_fields(self) -> tuple[str, ...]:
        return ()

    def validate_payload(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        _exact_keys(
            payload,
            _COMMON_FIELDS | {"verdict"},
            "engineering compatibility",
        )
        common = _common(payload)
        if common[1] != EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY.value:
            raise FacetValidationError(
                "compatibility source_kind must be capability_compatibility"
            )
        verdict = _string(
            payload["verdict"],
            "verdict",
            max_length=80,
            casefold=True,
        )
        if verdict not in {"ready", "blocked", "restart_required"}:
            raise FacetValidationError("compatibility verdict is unsupported")
        return payload

    def duplicate_key(self, payload: dict[str, JSONValue]) -> str:
        return "sha256:" + canonical_sha256(
            {
                "outcome_id": payload["outcome_id"],
                "subject_digest": payload["subject_digest"],
                "verdict": payload["verdict"],
            }
        )

    def searchable_text(self, payload: dict[str, JSONValue]) -> str:
        common = _common(payload)
        return " ".join(
            dict.fromkeys(
                (
                    "compatibility",
                    common[3],
                    common[4],
                    _string(payload["verdict"], "verdict", max_length=80),
                    *common[5],
                )
            )
        )

    def applicability(
        self,
        payload: dict[str, JSONValue],
    ) -> tuple[FacetApplicabilityConstraint, ...]:
        return _applicability(payload["applicability"])

    def revalidation_rules(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        return _common(payload)[8]
