from __future__ import annotations

import json
from dataclasses import replace

import pytest

from jarvis.engineering_knowledge import (
    ApplicabilityMatcherRegistry,
    EngineeringKnowledgeFacet,
    FacetValidationError,
    build_default_facet_registry,
    canonical_sha256,
)
from jarvis.engineering_learning import (
    ENGINEERING_COMPATIBILITY_FACET_TYPE,
    ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID,
    ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION,
    ENGINEERING_OUTCOME_FACET_TYPE,
    ENGINEERING_OUTCOME_V1_SCHEMA_ID,
    ENGINEERING_OUTCOME_V1_SCHEMA_VERSION,
    ENGINEERING_REGRESSION_FACET_TYPE,
    ENGINEERING_REGRESSION_V1_SCHEMA_ID,
    ENGINEERING_REGRESSION_V1_SCHEMA_VERSION,
    EngineeringCompatibilityV1Handler,
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    EngineeringOutcomeV1Handler,
    EngineeringRegressionV1Handler,
    OutcomeApplicability,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
RELEASE_SHA = "c" * 40


def _applicability() -> tuple[OutcomeApplicability, ...]:
    return (
        OutcomeApplicability(
            target_namespace="jarvis.component",
            target_identity="runtime.voice",
            matcher_type="exact",
            constraint={},
            required=True,
        ),
    )


def _outcome(
    *,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    attribution: EngineeringOutcomeAttribution = (
        EngineeringOutcomeAttribution.NOT_APPLICABLE
    ),
    source_kind: EngineeringOutcomeSourceKind = EngineeringOutcomeSourceKind.PROMOTION,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=source_kind,
        source_identity="promotion_123",
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=("production_observation_healthy",),
        evidence_references=("promotion:promotion_123", "observation:1"),
        applicability=_applicability(),
        observed_at_epoch=100.0,
        producer="phase10-test",
        change_id="change-1",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE_SHA,
    )


def _common_payload(
    outcome: EngineeringOutcomeV1,
) -> dict[str, object]:
    return {
        "outcome_id": outcome.outcome_id,
        "source_kind": outcome.source_kind.value,
        "source_identity": outcome.source_identity,
        "subject_type": outcome.subject_type,
        "subject_id": outcome.subject_id,
        "subject_digest": outcome.subject_digest,
        "reason_codes": list(outcome.reason_codes),
        "evidence_references": list(outcome.evidence_references),
        "applicability": [item.payload() for item in outcome.applicability],
        "revalidation": {
            "strategy": "source_outcome",
            "source_kind": outcome.source_kind.value,
            "source_identity": outcome.source_identity,
        },
    }


def _facet(
    *,
    facet_type: str,
    schema_id: str,
    schema_version: str,
    schema_digest: str,
    payload: dict[str, object],
) -> EngineeringKnowledgeFacet:
    return EngineeringKnowledgeFacet(
        facet_id=f"facet-{facet_type}",
        revision_id="revision-1",
        facet_type=facet_type,
        schema_id=schema_id,
        schema_version=schema_version,
        schema_digest=schema_digest,
        producer="phase10-test",
        payload_json=json.dumps(payload, separators=(",", ":")),
        payload_digest=canonical_sha256(payload),
        created_at_epoch=100.0,
    )


def test_engineering_outcome_identity_is_deterministic_and_result_sensitive() -> None:
    first = _outcome()
    replay = _outcome()
    failed = replace(
        first,
        result=EngineeringOutcomeResult.FAILURE,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
    )

    assert replay.outcome_id == first.outcome_id
    assert replay.digest == first.digest
    assert failed.outcome_id == first.outcome_id
    assert failed.digest != first.digest


def test_engineering_outcome_rejects_wrong_identity_and_unscoped_inputs() -> None:
    outcome = _outcome()

    with pytest.raises(ValueError, match="deterministic identity"):
        replace(outcome, outcome_id="outcome_wrong")

    with pytest.raises(ValueError, match="applicability must not be empty"):
        EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.PROMOTION,
            source_identity="promotion_123",
            subject_type="promotion_candidate",
            subject_id="candidate-1",
            subject_digest=SHA_A,
            result=EngineeringOutcomeResult.SUCCESS,
            attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
            reason_codes=("healthy",),
            evidence_references=("promotion:promotion_123",),
            applicability=(),
            observed_at_epoch=100.0,
            producer="phase10-test",
        )


def test_default_registry_validates_engineering_outcome_v1() -> None:
    outcome = _outcome()
    payload = {
        **_common_payload(outcome),
        "result": outcome.result.value,
        "attribution": outcome.attribution.value,
        "observed_at_epoch": outcome.observed_at_epoch,
        "producer": outcome.producer,
        "lineage": {
            "change_id": outcome.change_id,
            "candidate_id": outcome.candidate_id,
            "candidate_digest": outcome.candidate_digest,
            "release_sha": outcome.release_sha,
            "package_id": outcome.package_id,
            "package_version": outcome.package_version,
            "package_digest": outcome.package_digest,
        },
    }
    handler = EngineeringOutcomeV1Handler()
    facet = _facet(
        facet_type=ENGINEERING_OUTCOME_FACET_TYPE,
        schema_id=ENGINEERING_OUTCOME_V1_SCHEMA_ID,
        schema_version=ENGINEERING_OUTCOME_V1_SCHEMA_VERSION,
        schema_digest=handler.schema_digest,
        payload=payload,
    )

    matchers = ApplicabilityMatcherRegistry()
    matchers.register(target_namespace="jarvis.component", matcher_type="exact")
    validated = build_default_facet_registry().validate_for_decision(
        facet,
        applicability_registry=matchers,
    )

    assert validated.schema_key.facet_type == ENGINEERING_OUTCOME_FACET_TYPE
    assert "runtime.voice" in validated.searchable_text
    assert "success" in validated.searchable_text
    assert validated.revalidation_rules == {
        "strategy": "source_outcome",
        "source_kind": "promotion",
        "source_identity": "promotion_123",
    }


def test_regression_facet_accepts_candidate_failure_and_rejects_external_failure() -> None:
    outcome = _outcome(
        result=EngineeringOutcomeResult.FAILURE,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
    )
    payload = {
        **_common_payload(outcome),
        "result": outcome.result.value,
        "attribution": outcome.attribution.value,
    }
    handler = EngineeringRegressionV1Handler()
    facet = _facet(
        facet_type=ENGINEERING_REGRESSION_FACET_TYPE,
        schema_id=ENGINEERING_REGRESSION_V1_SCHEMA_ID,
        schema_version=ENGINEERING_REGRESSION_V1_SCHEMA_VERSION,
        schema_digest=handler.schema_digest,
        payload=payload,
    )

    validated = build_default_facet_registry().validate_for_decision(facet)
    assert "regression" in validated.searchable_text

    poisoned = dict(payload)
    poisoned["attribution"] = EngineeringOutcomeAttribution.EXTERNAL_PROVIDER.value
    bad_facet = _facet(
        facet_type=ENGINEERING_REGRESSION_FACET_TYPE,
        schema_id=ENGINEERING_REGRESSION_V1_SCHEMA_ID,
        schema_version=ENGINEERING_REGRESSION_V1_SCHEMA_VERSION,
        schema_digest=handler.schema_digest,
        payload=poisoned,
    )
    with pytest.raises(FacetValidationError, match="must be candidate"):
        build_default_facet_registry().validate_for_decision(bad_facet)


def test_compatibility_facet_requires_exact_compatibility_source() -> None:
    outcome = _outcome(
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
        source_kind=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
    )
    payload = {
        **_common_payload(outcome),
        "verdict": "ready",
    }
    handler = EngineeringCompatibilityV1Handler()
    facet = _facet(
        facet_type=ENGINEERING_COMPATIBILITY_FACET_TYPE,
        schema_id=ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID,
        schema_version=ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION,
        schema_digest=handler.schema_digest,
        payload=payload,
    )

    validated = build_default_facet_registry().validate_for_decision(facet)
    assert "compatibility" in validated.searchable_text
    assert "ready" in validated.searchable_text

    wrong_source = dict(payload)
    wrong_source["source_kind"] = "promotion"
    wrong_source["revalidation"] = {
        "strategy": "source_outcome",
        "source_kind": "promotion",
        "source_identity": outcome.source_identity,
    }
    wrong_facet = _facet(
        facet_type=ENGINEERING_COMPATIBILITY_FACET_TYPE,
        schema_id=ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID,
        schema_version=ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION,
        schema_digest=handler.schema_digest,
        payload=wrong_source,
    )
    with pytest.raises(
        FacetValidationError,
        match="must be capability_compatibility",
    ):
        build_default_facet_registry().validate_for_decision(wrong_facet)


def test_learning_facet_handlers_have_stable_schema_descriptors() -> None:
    handlers = (
        EngineeringOutcomeV1Handler(),
        EngineeringRegressionV1Handler(),
        EngineeringCompatibilityV1Handler(),
    )
    for handler in handlers:
        descriptor = handler.schema_descriptor
        descriptor["facet_type"] = "mutated"
        assert handler.schema_descriptor["facet_type"] != "mutated"
        assert len(handler.schema_digest) == 64
