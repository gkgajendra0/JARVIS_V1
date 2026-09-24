"""Versioned EngineeringKnowledge facet registry and fail-closed decision boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.canonical import (
    JSONValue,
    canonical_sha256,
    canonicalize_json_object_text,
)
from jarvis.engineering_knowledge.models import EngineeringKnowledgeFacet


class FacetRegistryError(RuntimeError):
    """Base error for facet registration, integrity or decision validation."""


class FacetRegistrationError(FacetRegistryError):
    """A facet handler conflicts with an existing exact schema registration."""


class UnsupportedFacetSchemaError(FacetRegistryError):
    """No exact handler exists for the facet type/schema/version tuple."""


class FacetValidationError(FacetRegistryError):
    """A registered facet payload violates its reviewed schema contract."""


class FacetIntegrityError(FacetValidationError):
    """A registered facet schema or payload digest does not match canonical data."""


class FacetPayloadUnavailableError(FacetValidationError):
    """The payload is protected/unavailable and therefore cannot drive decisions."""


class UnsupportedApplicabilityMatcherError(FacetValidationError):
    """A required applicability matcher is not registered."""


@dataclass(frozen=True, order=True, slots=True)
class FacetSchemaKey:
    facet_type: str
    schema_id: str
    schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "facet_type", _token(self.facet_type, "facet_type"))
        object.__setattr__(self, "schema_id", _text(self.schema_id, "schema_id"))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )


@dataclass(frozen=True, order=True, slots=True)
class ApplicabilityMatcherKey:
    target_namespace: str
    matcher_type: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "matcher_type",
            _token(self.matcher_type, "matcher_type"),
        )


@dataclass(frozen=True, slots=True)
class FacetApplicabilityConstraint:
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
            _text(self.target_identity, "target_identity"),
        )
        object.__setattr__(
            self,
            "matcher_type",
            _token(self.matcher_type, "matcher_type"),
        )
        if not isinstance(self.constraint, dict):
            raise TypeError("constraint must be a JSON object")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")


class FacetHandler(Protocol):
    """Reviewed semantics for one exact facet schema."""

    @property
    def key(self) -> FacetSchemaKey: ...

    @property
    def schema_descriptor(self) -> dict[str, JSONValue]: ...

    @property
    def protected_fields(self) -> tuple[str, ...]: ...

    def validate_payload(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]: ...

    def duplicate_key(self, payload: dict[str, JSONValue]) -> str: ...

    def searchable_text(self, payload: dict[str, JSONValue]) -> str: ...

    def applicability(
        self,
        payload: dict[str, JSONValue],
    ) -> tuple[FacetApplicabilityConstraint, ...]: ...

    def revalidation_rules(
        self,
        payload: dict[str, JSONValue],
    ) -> dict[str, JSONValue]: ...


@dataclass(frozen=True, slots=True)
class ValidatedFacet:
    facet: EngineeringKnowledgeFacet
    schema_key: FacetSchemaKey
    canonical_payload: bytes
    payload: dict[str, JSONValue]
    duplicate_key: str
    searchable_text: str
    applicability: tuple[FacetApplicabilityConstraint, ...]
    revalidation_rules: dict[str, JSONValue]
    protected_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FacetDecisionAssessment:
    eligible: bool
    reason_code: str
    validated: ValidatedFacet | None = None


class ApplicabilityMatcherRegistry:
    """Registration boundary only; matching semantics are implemented in Phase 2E."""

    def __init__(self) -> None:
        self._registered: set[ApplicabilityMatcherKey] = set()

    def register(self, *, target_namespace: str, matcher_type: str) -> None:
        key = ApplicabilityMatcherKey(target_namespace, matcher_type)
        if key in self._registered:
            raise FacetRegistrationError(
                "applicability matcher is already registered: "
                f"{key.target_namespace}/{key.matcher_type}"
            )
        self._registered.add(key)

    def supports(self, constraint: FacetApplicabilityConstraint) -> bool:
        if not isinstance(constraint, FacetApplicabilityConstraint):
            raise TypeError("constraint must be a FacetApplicabilityConstraint")
        return (
            ApplicabilityMatcherKey(
                constraint.target_namespace,
                constraint.matcher_type,
            )
            in self._registered
        )

    def require_supported(
        self,
        constraints: tuple[FacetApplicabilityConstraint, ...],
    ) -> None:
        for constraint in constraints:
            if constraint.required and not self.supports(constraint):
                raise UnsupportedApplicabilityMatcherError(
                    "required applicability matcher is not registered: "
                    f"{constraint.target_namespace}/{constraint.matcher_type}"
                )


class EngineeringKnowledgeFacetRegistry:
    """Exact-schema registry used before a facet may influence engineering decisions."""

    def __init__(self) -> None:
        self._handlers: dict[FacetSchemaKey, FacetHandler] = {}

    def register(self, handler: FacetHandler) -> None:
        key = handler.key
        if not isinstance(key, FacetSchemaKey):
            raise TypeError("handler.key must be a FacetSchemaKey")
        if key in self._handlers:
            raise FacetRegistrationError(
                "facet schema is already registered: "
                f"{key.facet_type}/{key.schema_id}/{key.schema_version}"
            )
        expected_schema_digest = canonical_sha256(handler.schema_descriptor)
        declared_schema_digest = _handler_schema_digest(handler)
        if declared_schema_digest != expected_schema_digest:
            raise FacetRegistrationError(
                "handler schema digest does not match its canonical descriptor"
            )
        self._handlers[key] = handler

    def registered_schema_keys(self) -> tuple[FacetSchemaKey, ...]:
        return tuple(sorted(self._handlers))

    def handler_for(self, facet: EngineeringKnowledgeFacet) -> FacetHandler | None:
        if not isinstance(facet, EngineeringKnowledgeFacet):
            raise TypeError("facet must be an EngineeringKnowledgeFacet")
        return self._handlers.get(
            FacetSchemaKey(
                facet.facet_type,
                facet.schema_id,
                facet.schema_version,
            )
        )

    def validate_for_decision(
        self,
        facet: EngineeringKnowledgeFacet,
        *,
        applicability_registry: ApplicabilityMatcherRegistry | None = None,
    ) -> ValidatedFacet:
        handler = self.handler_for(facet)
        if handler is None:
            raise UnsupportedFacetSchemaError(
                "facet schema is not registered for decision use"
            )

        expected_schema_digest = _handler_schema_digest(handler)
        if facet.schema_digest != expected_schema_digest:
            raise FacetIntegrityError(
                "facet schema digest does not match the registered schema"
            )
        if facet.payload_json is None:
            raise FacetPayloadUnavailableError(
                "protected facet payload is unavailable for decision validation"
            )

        try:
            payload, canonical, actual_payload_digest = canonicalize_json_object_text(
                facet.payload_json
            )
        except ValueError as exc:
            raise FacetValidationError(str(exc)) from exc
        if actual_payload_digest != facet.payload_digest:
            raise FacetIntegrityError(
                "facet payload digest does not match RFC-8785 canonical payload"
            )

        try:
            validated_payload = handler.validate_payload(payload)
        except FacetValidationError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise FacetValidationError(str(exc)) from exc

        if canonical_sha256(validated_payload) != actual_payload_digest:
            raise FacetValidationError(
                "facet validator must not mutate canonical payload semantics"
            )

        duplicate_key = _text(handler.duplicate_key(validated_payload), "duplicate_key")
        searchable_text = _text(
            handler.searchable_text(validated_payload),
            "searchable_text",
        )
        applicability = handler.applicability(validated_payload)
        if not isinstance(applicability, tuple) or not all(
            isinstance(item, FacetApplicabilityConstraint) for item in applicability
        ):
            raise FacetValidationError(
                "facet applicability extractor returned an invalid contract"
            )
        if applicability_registry is not None:
            applicability_registry.require_supported(applicability)

        revalidation_rules = handler.revalidation_rules(validated_payload)
        if not isinstance(revalidation_rules, dict):
            raise FacetValidationError("facet revalidation rules must be a JSON object")

        return ValidatedFacet(
            facet=facet,
            schema_key=handler.key,
            canonical_payload=canonical,
            payload=validated_payload,
            duplicate_key=duplicate_key,
            searchable_text=searchable_text,
            applicability=applicability,
            revalidation_rules=revalidation_rules,
            protected_fields=tuple(handler.protected_fields),
        )

    def assess_for_decision(
        self,
        facet: EngineeringKnowledgeFacet,
        *,
        applicability_registry: ApplicabilityMatcherRegistry | None = None,
    ) -> FacetDecisionAssessment:
        try:
            validated = self.validate_for_decision(
                facet,
                applicability_registry=applicability_registry,
            )
        except UnsupportedFacetSchemaError:
            return FacetDecisionAssessment(
                eligible=False,
                reason_code="unsupported_facet_schema",
            )
        except FacetPayloadUnavailableError:
            return FacetDecisionAssessment(
                eligible=False,
                reason_code="facet_payload_unavailable",
            )
        except UnsupportedApplicabilityMatcherError:
            return FacetDecisionAssessment(
                eligible=False,
                reason_code="unsupported_applicability_matcher",
            )
        except FacetIntegrityError:
            return FacetDecisionAssessment(
                eligible=False,
                reason_code="facet_integrity_failure",
            )
        except FacetValidationError:
            return FacetDecisionAssessment(
                eligible=False,
                reason_code="facet_validation_failure",
            )
        return FacetDecisionAssessment(
            eligible=True,
            reason_code="validated_registered_facet",
            validated=validated,
        )


def _handler_schema_digest(handler: FacetHandler) -> str:
    digest = getattr(handler, "schema_digest", None)
    if not isinstance(digest, str) or len(digest) != 64:
        raise FacetRegistrationError("handler must expose a 64-character schema_digest")
    normalized = digest.casefold()
    if any(char not in "0123456789abcdef" for char in normalized):
        raise FacetRegistrationError("handler schema_digest must be lowercase hex")
    return normalized


def _text(value: object, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _token(value: object, field: str) -> str:
    return _text(value, field).casefold()


FacetHandlerFactory = Callable[[], FacetHandler]
FacetHandlerMap = Mapping[FacetSchemaKey, FacetHandler]
