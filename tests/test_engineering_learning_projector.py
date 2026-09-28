from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.engineering_knowledge import (
    KnowledgeLifecycleState,
    build_default_facet_registry,
)
from jarvis.engineering_learning.facets import (
    ENGINEERING_COMPATIBILITY_FACET_TYPE,
    ENGINEERING_OUTCOME_FACET_TYPE,
    ENGINEERING_REGRESSION_FACET_TYPE,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.projector import (
    ENGINEERING_LEARNING_ATTESTATION_PREDICATE,
    ENGINEERING_LEARNING_KIND_NAMESPACE,
    EngineeringLearningProjectionError,
    EngineeringLearningProjector,
)
from jarvis.incidents.store import SqliteIncidentStore

SHA_A = "a" * 64
SHA_B = "b" * 64
EVIDENCE_SHA = "d" * 64
RELEASE = "c" * 40


def _applicability(
    *,
    package: bool = False,
) -> tuple[OutcomeApplicability, ...]:
    if package:
        return (
            OutcomeApplicability(
                target_namespace="package",
                target_identity="tv.control",
                matcher_type="version_exact",
                constraint={"version": "1.0.0"},
                required=True,
            ),
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=RELEASE,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        )
    return (
        OutcomeApplicability(
            target_namespace="jarvis.revision",
            target_identity=RELEASE,
            matcher_type="exact",
            constraint={},
            required=True,
        ),
    )


def _promotion(
    *,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    attribution: EngineeringOutcomeAttribution = (
        EngineeringOutcomeAttribution.NOT_APPLICABLE
    ),
    evidence: tuple[str, ...] | None = None,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity="promotion-1",
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=("runtime_healthy",),
        evidence_references=(
            evidence
            if evidence is not None
            else (
                "promotion-attempt:promotion-1",
                f"change-artifact:observation-1:sha256:{EVIDENCE_SHA}",
            )
        ),
        applicability=_applicability(),
        observed_at_epoch=100.0,
        producer="phase10-projector-test",
        change_id="change-1",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _compatibility(
    *,
    result: EngineeringOutcomeResult,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
        source_identity="compatibility-report-1",
        subject_type="capability_package",
        subject_id="tv.control@1.0.0",
        subject_digest=SHA_B,
        result=result,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
        reason_codes=(
            "ready" if result is EngineeringOutcomeResult.SUCCESS else "blocked",
        ),
        evidence_references=(f"capability-compatibility-report:sha256:{EVIDENCE_SHA}",),
        applicability=_applicability(package=True),
        observed_at_epoch=100.0,
        producer="phase10-projector-test",
        release_sha=RELEASE,
        package_id="tv.control",
        package_version="1.0.0",
        package_digest=SHA_B,
    )


def test_positive_outcome_projects_complete_candidate_bundle() -> None:
    projector = EngineeringLearningProjector()
    bundle, decision = projector.build_candidate(_promotion())

    assert decision.eligible is True
    assert bundle.revision.kind_namespace == ENGINEERING_LEARNING_KIND_NAMESPACE
    assert bundle.lifecycle_event.to_state is KnowledgeLifecycleState.CANDIDATE
    assert bundle.lifecycle_event.from_state is None
    assert len(bundle.facets) == 1
    assert bundle.facets[0].facet_type == ENGINEERING_OUTCOME_FACET_TYPE
    assert len(bundle.applicability) == 1
    assert len(bundle.evidence) == 2
    assert len(bundle.evidence_links) == 2
    assert len(bundle.attestations) == 1
    assert (
        bundle.attestations[0].predicate_type
        == ENGINEERING_LEARNING_ATTESTATION_PREDICATE
    )
    assert bundle.attestations[0].subject_type == "knowledge_revision"
    assert bundle.attestations[0].subject_id == bundle.revision.revision_id
    assert bundle.attestations[0].subject_digest == bundle.revision.canonical_digest

    digest_evidence = next(
        item for item in bundle.evidence if item.integrity_digest is not None
    )
    assert digest_evidence.integrity_algorithm == "sha256"
    assert digest_evidence.integrity_digest == EVIDENCE_SHA


def test_projected_facets_validate_against_registered_schemas() -> None:
    registry = build_default_facet_registry()
    projector = EngineeringLearningProjector()
    bundle, _ = projector.build_candidate(_promotion())

    validated = tuple(registry.validate_for_decision(item) for item in bundle.facets)

    assert tuple(item.schema_key.facet_type for item in validated) == (
        ENGINEERING_OUTCOME_FACET_TYPE,
    )


def test_candidate_local_failure_projects_regression_facet() -> None:
    outcome = _promotion(
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
    )
    bundle, decision = EngineeringLearningProjector().build_candidate(outcome)

    assert decision.eligible is True
    assert {item.facet_type for item in bundle.facets} == {
        ENGINEERING_OUTCOME_FACET_TYPE,
        ENGINEERING_REGRESSION_FACET_TYPE,
    }


@pytest.mark.parametrize(
    "result",
    [EngineeringOutcomeResult.SUCCESS, EngineeringOutcomeResult.BLOCKED],
)
def test_compatibility_projects_exact_compatibility_facet(
    result: EngineeringOutcomeResult,
) -> None:
    bundle, decision = EngineeringLearningProjector().build_candidate(
        _compatibility(result=result)
    )

    assert decision.eligible is True
    assert {item.facet_type for item in bundle.facets} == {
        ENGINEERING_OUTCOME_FACET_TYPE,
        ENGINEERING_COMPATIBILITY_FACET_TYPE,
    }
    assert {item.target_namespace for item in bundle.applicability} == {
        "package",
        "jarvis.revision",
    }


def test_external_promotion_failure_cannot_be_projected() -> None:
    outcome = _promotion(
        result=EngineeringOutcomeResult.FAILURE,
        attribution=EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
    )

    with pytest.raises(EngineeringLearningProjectionError, match="not eligible"):
        EngineeringLearningProjector().build_candidate(outcome)


def test_malformed_claimed_evidence_digest_fails_closed() -> None:
    outcome = _promotion(
        evidence=(
            "promotion-attempt:promotion-1",
            "change-artifact:observation-1:sha256:not-a-digest",
        )
    )

    with pytest.raises(
        EngineeringLearningProjectionError,
        match="malformed sha256",
    ):
        EngineeringLearningProjector().build_candidate(outcome)


def test_projection_is_idempotent_in_sqlite_store(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    projector = EngineeringLearningProjector()
    outcome = _promotion()
    try:
        first = projector.project(store, outcome)
        replay = projector.project(store, outcome)

        assert first.created is True
        assert replay.created is False
        assert replay.knowledge_id == first.knowledge_id
        assert replay.revision_id == first.revision_id
        assert (
            store.get_engineering_knowledge_lifecycle_state(first.revision_id)
            is KnowledgeLifecycleState.CANDIDATE
        )
        assert len(store.list_engineering_knowledge_facets(first.revision_id)) == 1
        assert len(store.list_engineering_knowledge_evidence(first.revision_id)) == 2
    finally:
        store.close()


def test_same_proposition_can_build_immutable_successor_revision() -> None:
    projector = EngineeringLearningProjector()
    first, _ = projector.build_candidate(_promotion())
    changed = replace(
        _promotion(),
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason_codes=("candidate_runtime_regression",),
    )
    successor, decision = projector.build_candidate(
        changed,
        revision_number=2,
        parent_revision_id=first.revision.revision_id,
        supersedes_revision_id=first.revision.revision_id,
    )

    assert decision.eligible is True
    assert successor.identity.knowledge_id == first.identity.knowledge_id
    assert successor.revision.revision_number == 2
    assert successor.revision.revision_id != first.revision.revision_id
    assert successor.revision.parent_revision_id == first.revision.revision_id
    assert successor.revision.supersedes_revision_id == first.revision.revision_id


def test_revision_identity_binds_outcome_digest() -> None:
    projector = EngineeringLearningProjector()
    original, _ = projector.build_candidate(_promotion())
    changed = replace(_promotion(), reason_codes=("runtime_healthy_again",))
    changed_bundle, _ = projector.build_candidate(changed)

    assert original.identity.knowledge_id == changed_bundle.identity.knowledge_id
    assert original.revision.revision_id != changed_bundle.revision.revision_id
    assert (
        original.revision.canonical_digest != changed_bundle.revision.canonical_digest
    )
