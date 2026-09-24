"""Reviewed versioned repair facet schemas for EngineeringKnowledge."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from jarvis.engineering_knowledge.canonical import JSONValue, canonical_sha256
from jarvis.engineering_knowledge.registry import (
    FacetApplicabilityConstraint,
    FacetSchemaKey,
    FacetValidationError,
)

REPAIR_FINDING_FACET_TYPE = "jarvis.repair.finding"
REPAIR_FINDING_V1_SCHEMA_ID = "urn:jarvis:engineering-knowledge:repair-finding:v1"
REPAIR_FINDING_V1_SCHEMA_VERSION = "1"

REPAIR_FINDING_V1_SCHEMA: dict[str, JSONValue] = {
    "facet_type": REPAIR_FINDING_FACET_TYPE,
    "schema_id": REPAIR_FINDING_V1_SCHEMA_ID,
    "schema_version": REPAIR_FINDING_V1_SCHEMA_VERSION,
    "additional_properties": False,
    "required": [
        "component_id",
        "trigger",
        "repair",
        "verification",
        "applicability",
        "required_resources",
        "revalidation",
    ],
    "properties": {
        "component_id": "non_empty_string",
        "trigger": {
            "required": ["source", "reason_code", "failure_signature"],
            "additional_properties": False,
        },
        "repair": {
            "required": [
                "policy_id",
                "policy_version",
                "action_kind",
                "preconditions",
                "successful_sequence",
            ],
            "additional_properties": False,
        },
        "verification": {
            "required": ["contract_id", "verdict"],
            "verdict": ["recovered"],
            "additional_properties": False,
        },
        "applicability": {
            "item_required": [
                "target_namespace",
                "target_identity",
                "matcher_type",
                "constraint",
                "required",
            ],
            "additional_properties": False,
        },
        "required_resources": "list_of_strings",
        "revalidation": {
            "required": ["strategy", "contract_id"],
            "strategy": ["verification_contract"],
            "additional_properties": False,
        },
    },
}

REPAIR_FINDING_V1_SCHEMA_DIGEST = canonical_sha256(REPAIR_FINDING_V1_SCHEMA)


@dataclass(frozen=True, slots=True)
class RepairFindingV1Handler:
    """Strict deterministic handler for the first repair knowledge facet."""

    @property
    def key(self) -> FacetSchemaKey:
        return FacetSchemaKey(
            REPAIR_FINDING_FACET_TYPE,
            REPAIR_FINDING_V1_SCHEMA_ID,
            REPAIR_FINDING_V1_SCHEMA_VERSION,
        )

    @property
    def schema_descriptor(self) -> dict[str, JSONValue]:
        return deepcopy(REPAIR_FINDING_V1_SCHEMA)

    @property
    def schema_digest(self) -> str:
        return REPAIR_FINDING_V1_SCHEMA_DIGEST

    @property
    def protected_fields(self) -> tuple[str, ...]:
        return ()

    def validate_payload(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        _exact_keys(
            payload,
            {
                "component_id",
                "trigger",
                "repair",
                "verification",
                "applicability",
                "required_resources",
                "revalidation",
            },
            "repair finding",
        )
        component_id = _string(payload["component_id"], "component_id", max_length=200)

        trigger = _object(payload["trigger"], "trigger")
        _exact_keys(
            trigger,
            {"source", "reason_code", "failure_signature"},
            "trigger",
        )
        _string(trigger["source"], "trigger.source", max_length=100)
        _string(trigger["reason_code"], "trigger.reason_code", max_length=160)
        _string(
            trigger["failure_signature"],
            "trigger.failure_signature",
            max_length=512,
        )

        repair = _object(payload["repair"], "repair")
        _exact_keys(
            repair,
            {
                "policy_id",
                "policy_version",
                "action_kind",
                "preconditions",
                "successful_sequence",
            },
            "repair",
        )
        _string(repair["policy_id"], "repair.policy_id", max_length=200)
        _positive_int(repair["policy_version"], "repair.policy_version")
        _string(repair["action_kind"], "repair.action_kind", max_length=160)
        _string_list(
            repair["preconditions"],
            "repair.preconditions",
            max_items=32,
            allow_empty=True,
        )
        _string_list(
            repair["successful_sequence"],
            "repair.successful_sequence",
            max_items=16,
            allow_empty=False,
        )

        verification = _object(payload["verification"], "verification")
        _exact_keys(
            verification,
            {"contract_id", "verdict"},
            "verification",
        )
        verification_contract = _string(
            verification["contract_id"],
            "verification.contract_id",
            max_length=200,
        )
        verdict = _string(
            verification["verdict"],
            "verification.verdict",
            max_length=40,
        ).casefold()
        if verdict != "recovered":
            raise FacetValidationError(
                "repair finding verification.verdict must be 'recovered'"
            )

        applicability = payload["applicability"]
        if not isinstance(applicability, list) or not applicability:
            raise FacetValidationError(
                "repair finding applicability must be a non-empty list"
            )
        if len(applicability) > 32:
            raise FacetValidationError(
                "repair finding applicability exceeds 32 constraints"
            )
        has_component_constraint = False
        for index, raw_constraint in enumerate(applicability):
            constraint = _object(raw_constraint, f"applicability[{index}]")
            _exact_keys(
                constraint,
                {
                    "target_namespace",
                    "target_identity",
                    "matcher_type",
                    "constraint",
                    "required",
                },
                f"applicability[{index}]",
            )
            namespace = _string(
                constraint["target_namespace"],
                f"applicability[{index}].target_namespace",
                max_length=160,
            ).casefold()
            identity = _string(
                constraint["target_identity"],
                f"applicability[{index}].target_identity",
                max_length=256,
            )
            matcher_type = _string(
                constraint["matcher_type"],
                f"applicability[{index}].matcher_type",
                max_length=100,
            ).casefold()
            _object(
                constraint["constraint"],
                f"applicability[{index}].constraint",
            )
            if not isinstance(constraint["required"], bool):
                raise FacetValidationError(
                    f"applicability[{index}].required must be a bool"
                )
            if (
                namespace == "jarvis.component"
                and matcher_type == "exact"
                and identity == component_id
                and constraint["required"]
            ):
                has_component_constraint = True
        if not has_component_constraint:
            raise FacetValidationError(
                "repair finding requires exact required applicability for component_id"
            )

        _string_list(
            payload["required_resources"],
            "required_resources",
            max_items=32,
            allow_empty=True,
        )

        revalidation = _object(payload["revalidation"], "revalidation")
        _exact_keys(
            revalidation,
            {"strategy", "contract_id"},
            "revalidation",
        )
        strategy = _string(
            revalidation["strategy"],
            "revalidation.strategy",
            max_length=80,
        ).casefold()
        if strategy != "verification_contract":
            raise FacetValidationError(
                "repair finding revalidation.strategy must be 'verification_contract'"
            )
        revalidation_contract = _string(
            revalidation["contract_id"],
            "revalidation.contract_id",
            max_length=200,
        )
        if revalidation_contract != verification_contract:
            raise FacetValidationError(
                "revalidation.contract_id must match verification.contract_id"
            )

        return payload

    def duplicate_key(self, payload: dict[str, JSONValue]) -> str:
        trigger = _object(payload["trigger"], "trigger")
        repair = _object(payload["repair"], "repair")
        return "sha256:" + canonical_sha256(
            {
                "component_id": payload["component_id"],
                "trigger": {
                    "source": trigger["source"],
                    "reason_code": trigger["reason_code"],
                    "failure_signature": trigger["failure_signature"],
                },
                "repair": {
                    "policy_id": repair["policy_id"],
                    "policy_version": repair["policy_version"],
                    "action_kind": repair["action_kind"],
                },
            }
        )

    def searchable_text(self, payload: dict[str, JSONValue]) -> str:
        trigger = _object(payload["trigger"], "trigger")
        repair = _object(payload["repair"], "repair")
        verification = _object(payload["verification"], "verification")
        resources = _string_list(
            payload["required_resources"],
            "required_resources",
            max_items=32,
            allow_empty=True,
        )
        parts = (
            _string(payload["component_id"], "component_id", max_length=200),
            _string(trigger["source"], "trigger.source", max_length=100),
            _string(trigger["reason_code"], "trigger.reason_code", max_length=160),
            _string(
                trigger["failure_signature"],
                "trigger.failure_signature",
                max_length=512,
            ),
            _string(repair["policy_id"], "repair.policy_id", max_length=200),
            _string(repair["action_kind"], "repair.action_kind", max_length=160),
            _string(
                verification["contract_id"],
                "verification.contract_id",
                max_length=200,
            ),
            *resources,
        )
        return " ".join(_dedupe(parts))

    def applicability(
        self,
        payload: dict[str, JSONValue],
    ) -> tuple[FacetApplicabilityConstraint, ...]:
        raw_items = payload["applicability"]
        assert isinstance(raw_items, list)
        result: list[FacetApplicabilityConstraint] = []
        for index, raw in enumerate(raw_items):
            item = _object(raw, f"applicability[{index}]")
            constraint = _object(
                item["constraint"],
                f"applicability[{index}].constraint",
            )
            required = item["required"]
            assert isinstance(required, bool)
            result.append(
                FacetApplicabilityConstraint(
                    target_namespace=_string(
                        item["target_namespace"],
                        f"applicability[{index}].target_namespace",
                        max_length=160,
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
                    ),
                    constraint=constraint,
                    required=required,
                )
            )
        return tuple(result)

    def revalidation_rules(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        return dict(_object(payload["revalidation"], "revalidation"))


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


def _string(value: JSONValue, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise FacetValidationError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise FacetValidationError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise FacetValidationError(f"{field} exceeds {max_length} characters")
    if normalized != value:
        raise FacetValidationError(f"{field} must not contain outer whitespace")
    return normalized


def _positive_int(value: JSONValue, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FacetValidationError(f"{field} must be an integer")
    if value <= 0:
        raise FacetValidationError(f"{field} must be positive")
    return value


def _string_list(
    value: JSONValue,
    field: str,
    *,
    max_items: int,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FacetValidationError(f"{field} must be a list")
    if not allow_empty and not value:
        raise FacetValidationError(f"{field} must not be empty")
    if len(value) > max_items:
        raise FacetValidationError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _string(item, f"{field}[{index}]", max_length=256)
        for index, item in enumerate(value)
    )
    if len(set(normalized)) != len(normalized):
        raise FacetValidationError(f"{field} must not contain duplicates")
    return normalized


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)
