"""Deterministic applicability evaluation for accepted EngineeringKnowledge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.engineering_knowledge.canonical import JSONValue, parse_json_object
from jarvis.engineering_knowledge.models import EngineeringApplicability


class ApplicabilityMatchStatus(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNKNOWN = "unknown"


class ApplicabilityEvaluationError(ValueError):
    """Applicability input or matcher registration is invalid."""


@dataclass(frozen=True, slots=True)
class ApplicabilityFact:
    """One observed fact about the current engineering target/environment."""

    target_namespace: str
    target_identity: str
    attributes: dict[str, str]

    def __post_init__(self) -> None:
        namespace = str(self.target_namespace).strip().casefold()
        identity = str(self.target_identity).strip()
        if not namespace:
            raise ApplicabilityEvaluationError("target_namespace must not be empty")
        if not identity:
            raise ApplicabilityEvaluationError("target_identity must not be empty")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in self.attributes.items():
            key = str(raw_key).strip().casefold()
            value = str(raw_value).strip()
            if not key:
                raise ApplicabilityEvaluationError(
                    "applicability fact attribute key must not be empty"
                )
            if not value:
                raise ApplicabilityEvaluationError(
                    f"applicability fact attribute {key!r} must not be empty"
                )
            normalized[key] = value
        object.__setattr__(self, "target_namespace", namespace)
        object.__setattr__(self, "target_identity", identity)
        object.__setattr__(self, "attributes", normalized)


@dataclass(frozen=True, slots=True)
class ApplicabilityContext:
    facts: tuple[ApplicabilityFact, ...]

    def facts_for_namespace(self, namespace: str) -> tuple[ApplicabilityFact, ...]:
        normalized = str(namespace).strip().casefold()
        return tuple(fact for fact in self.facts if fact.target_namespace == normalized)

    def facts_for_identity(
        self,
        namespace: str,
        identity: str,
    ) -> tuple[ApplicabilityFact, ...]:
        normalized_namespace = str(namespace).strip().casefold()
        normalized_identity = str(identity).strip().casefold()
        return tuple(
            fact
            for fact in self.facts
            if fact.target_namespace == normalized_namespace
            and fact.target_identity.casefold() == normalized_identity
        )


@dataclass(frozen=True, slots=True)
class ApplicabilityConstraintResult:
    applicability_id: str
    required: bool
    status: ApplicabilityMatchStatus
    reason_code: str


@dataclass(frozen=True, slots=True)
class ApplicabilityDecision:
    eligible: bool
    results: tuple[ApplicabilityConstraintResult, ...]
    blocking_applicability_ids: tuple[str, ...]


class ApplicabilityMatcher(Protocol):
    def evaluate(
        self,
        applicability: EngineeringApplicability,
        constraint: dict[str, JSONValue],
        context: ApplicabilityContext,
    ) -> ApplicabilityConstraintResult: ...


@dataclass(frozen=True, order=True, slots=True)
class ApplicabilityMatcherKey:
    target_namespace: str
    matcher_type: str

    def __post_init__(self) -> None:
        namespace = str(self.target_namespace).strip().casefold()
        matcher = str(self.matcher_type).strip().casefold()
        if not namespace:
            raise ApplicabilityEvaluationError("target_namespace must not be empty")
        if not matcher:
            raise ApplicabilityEvaluationError("matcher_type must not be empty")
        object.__setattr__(self, "target_namespace", namespace)
        object.__setattr__(self, "matcher_type", matcher)


class EngineeringApplicabilityRegistry:
    """Exact namespace/matcher registry. Unknown required semantics fail closed."""

    def __init__(self) -> None:
        self._matchers: dict[ApplicabilityMatcherKey, ApplicabilityMatcher] = {}

    def register(
        self,
        *,
        target_namespace: str,
        matcher_type: str,
        matcher: ApplicabilityMatcher,
    ) -> None:
        key = ApplicabilityMatcherKey(target_namespace, matcher_type)
        if key in self._matchers:
            raise ApplicabilityEvaluationError(
                "applicability matcher already registered: "
                f"{key.target_namespace}/{key.matcher_type}"
            )
        self._matchers[key] = matcher

    def matcher_for(
        self,
        applicability: EngineeringApplicability,
    ) -> ApplicabilityMatcher | None:
        if not isinstance(applicability, EngineeringApplicability):
            raise TypeError("applicability must be an EngineeringApplicability")
        return self._matchers.get(
            ApplicabilityMatcherKey(
                applicability.target_namespace,
                applicability.matcher_type,
            )
        )

    def evaluate(
        self,
        applicability: EngineeringApplicability,
        context: ApplicabilityContext,
    ) -> ApplicabilityConstraintResult:
        matcher = self.matcher_for(applicability)
        if matcher is None:
            return ApplicabilityConstraintResult(
                applicability_id=applicability.applicability_id,
                required=applicability.required,
                status=ApplicabilityMatchStatus.UNKNOWN,
                reason_code="unsupported_applicability_matcher",
            )
        try:
            constraint = parse_json_object(applicability.constraint_json)
            return matcher.evaluate(applicability, constraint, context)
        except ApplicabilityEvaluationError as exc:
            return ApplicabilityConstraintResult(
                applicability_id=applicability.applicability_id,
                required=applicability.required,
                status=ApplicabilityMatchStatus.UNKNOWN,
                reason_code=f"invalid_applicability_constraint:{exc}",
            )


class ExactIdentityMatcher:
    """Match one target identity inside an explicitly known namespace."""

    def evaluate(
        self,
        applicability: EngineeringApplicability,
        constraint: dict[str, JSONValue],
        context: ApplicabilityContext,
    ) -> ApplicabilityConstraintResult:
        if constraint:
            raise ApplicabilityEvaluationError(
                "exact identity matcher requires an empty constraint object"
            )
        identity_facts = context.facts_for_identity(
            applicability.target_namespace,
            applicability.target_identity,
        )
        if identity_facts:
            return _result(
                applicability,
                ApplicabilityMatchStatus.MATCH,
                "exact_identity_match",
            )
        if context.facts_for_namespace(applicability.target_namespace):
            return _result(
                applicability,
                ApplicabilityMatchStatus.NO_MATCH,
                "exact_identity_mismatch",
            )
        return _result(
            applicability,
            ApplicabilityMatchStatus.UNKNOWN,
            "target_namespace_not_observed",
        )


class ExactVersionMatcher:
    """Match an exact version attribute for one target identity."""

    def evaluate(
        self,
        applicability: EngineeringApplicability,
        constraint: dict[str, JSONValue],
        context: ApplicabilityContext,
    ) -> ApplicabilityConstraintResult:
        if set(constraint) != {"version"}:
            raise ApplicabilityEvaluationError(
                "version_exact requires only a version field"
            )
        expected = constraint["version"]
        if not isinstance(expected, str) or not expected.strip():
            raise ApplicabilityEvaluationError(
                "version_exact version must be a non-empty string"
            )
        facts = context.facts_for_identity(
            applicability.target_namespace,
            applicability.target_identity,
        )
        if not facts:
            if context.facts_for_namespace(applicability.target_namespace):
                return _result(
                    applicability,
                    ApplicabilityMatchStatus.NO_MATCH,
                    "target_identity_mismatch",
                )
            return _result(
                applicability,
                ApplicabilityMatchStatus.UNKNOWN,
                "target_namespace_not_observed",
            )

        observed_versions = tuple(fact.attributes.get("version") for fact in facts)
        if any(
            version is not None and version.casefold() == expected.strip().casefold()
            for version in observed_versions
        ):
            return _result(
                applicability,
                ApplicabilityMatchStatus.MATCH,
                "exact_version_match",
            )
        if any(version is None for version in observed_versions):
            return _result(
                applicability,
                ApplicabilityMatchStatus.UNKNOWN,
                "version_attribute_not_observed",
            )
        return _result(
            applicability,
            ApplicabilityMatchStatus.NO_MATCH,
            "exact_version_mismatch",
        )


class NumericVersionRangeMatcher:
    """Bounded dotted-integer version matcher for domains with deterministic ordering."""

    def evaluate(
        self,
        applicability: EngineeringApplicability,
        constraint: dict[str, JSONValue],
        context: ApplicabilityContext,
    ) -> ApplicabilityConstraintResult:
        allowed = {"min_inclusive", "max_exclusive"}
        if not constraint or not set(constraint).issubset(allowed):
            raise ApplicabilityEvaluationError(
                "numeric_version_range requires min_inclusive and/or max_exclusive"
            )

        lower = _optional_numeric_version(
            constraint.get("min_inclusive"),
            field="min_inclusive",
        )
        upper = _optional_numeric_version(
            constraint.get("max_exclusive"),
            field="max_exclusive",
        )
        if lower is not None and upper is not None and lower >= upper:
            raise ApplicabilityEvaluationError(
                "min_inclusive must be lower than max_exclusive"
            )

        facts = context.facts_for_identity(
            applicability.target_namespace,
            applicability.target_identity,
        )
        if not facts:
            if context.facts_for_namespace(applicability.target_namespace):
                return _result(
                    applicability,
                    ApplicabilityMatchStatus.NO_MATCH,
                    "target_identity_mismatch",
                )
            return _result(
                applicability,
                ApplicabilityMatchStatus.UNKNOWN,
                "target_namespace_not_observed",
            )

        parsed_any = False
        missing_or_unparseable = False
        for fact in facts:
            raw_version = fact.attributes.get("version")
            if raw_version is None:
                missing_or_unparseable = True
                continue
            try:
                observed = _numeric_version(raw_version)
            except ApplicabilityEvaluationError:
                missing_or_unparseable = True
                continue
            parsed_any = True
            if lower is not None and observed < lower:
                continue
            if upper is not None and observed >= upper:
                continue
            return _result(
                applicability,
                ApplicabilityMatchStatus.MATCH,
                "numeric_version_range_match",
            )

        if parsed_any and not missing_or_unparseable:
            return _result(
                applicability,
                ApplicabilityMatchStatus.NO_MATCH,
                "numeric_version_range_mismatch",
            )
        return _result(
            applicability,
            ApplicabilityMatchStatus.UNKNOWN,
            "version_not_deterministically_comparable",
        )


def build_default_applicability_registry() -> EngineeringApplicabilityRegistry:
    registry = EngineeringApplicabilityRegistry()
    exact_namespaces = (
        "jarvis.component",
        "platform",
        "jarvis.revision",
        "package",
        "device.model",
        "firmware",
        "protocol",
    )
    version_namespaces = (
        "jarvis.revision",
        "package",
        "firmware",
        "protocol",
    )
    for namespace in exact_namespaces:
        registry.register(
            target_namespace=namespace,
            matcher_type="exact",
            matcher=ExactIdentityMatcher(),
        )
    for namespace in version_namespaces:
        registry.register(
            target_namespace=namespace,
            matcher_type="version_exact",
            matcher=ExactVersionMatcher(),
        )
        registry.register(
            target_namespace=namespace,
            matcher_type="numeric_version_range",
            matcher=NumericVersionRangeMatcher(),
        )
    return registry


class EngineeringKnowledgeApplicabilityStore(Protocol):
    def list_engineering_knowledge_applicability(
        self,
        revision_id: str,
    ) -> tuple[EngineeringApplicability, ...]: ...


class EngineeringKnowledgeApplicabilityService:
    def __init__(
        self,
        store: EngineeringKnowledgeApplicabilityStore,
        *,
        registry: EngineeringApplicabilityRegistry | None = None,
    ) -> None:
        self._store = store
        self._registry = registry or build_default_applicability_registry()

    def evaluate(
        self,
        revision_id: str,
        context: ApplicabilityContext,
    ) -> ApplicabilityDecision:
        constraints = self._store.list_engineering_knowledge_applicability(revision_id)
        if not constraints:
            return ApplicabilityDecision(
                eligible=False,
                results=(),
                blocking_applicability_ids=("missing_applicability",),
            )

        results = tuple(self._registry.evaluate(item, context) for item in constraints)
        blocking = tuple(
            result.applicability_id
            for result in results
            if result.required and result.status is not ApplicabilityMatchStatus.MATCH
        )
        return ApplicabilityDecision(
            eligible=not blocking,
            results=results,
            blocking_applicability_ids=blocking,
        )


def _result(
    applicability: EngineeringApplicability,
    status: ApplicabilityMatchStatus,
    reason_code: str,
) -> ApplicabilityConstraintResult:
    return ApplicabilityConstraintResult(
        applicability_id=applicability.applicability_id,
        required=applicability.required,
        status=status,
        reason_code=reason_code,
    )


def _optional_numeric_version(
    value: JSONValue | None,
    *,
    field: str,
) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApplicabilityEvaluationError(f"{field} must be a string")
    return _numeric_version(value)


def _numeric_version(value: str) -> tuple[int, ...]:
    text = str(value).strip()
    if not text:
        raise ApplicabilityEvaluationError("version must not be empty")
    parts = text.split(".")
    if not all(part.isdigit() for part in parts):
        raise ApplicabilityEvaluationError(
            "version must contain only dot-separated non-negative integers"
        )
    return tuple(int(part) for part in parts)
