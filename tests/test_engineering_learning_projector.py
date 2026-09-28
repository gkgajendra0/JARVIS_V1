from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.engineering_knowledge import KnowledgeLifecycleState
from jarvis.engineering_knowledge.persistence import (
    EngineeringKnowledgePersistenceConflictError,
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
from jarvis.engineering_learning.policy import LearningDisposition
from jarvis.engineering_learning.projector import (
    ENGINEERING_LEARNING_ATTESTATION_PREDICATE,
    ENGINEERING_LEARNING_KIND_NAMESPACE,
    EngineeringLearningProjectionError,
    EngineeringLearningProjector,
)
from jarvis.incidents.store import SqliteIncidentStore

SHA_A = "a" * 64
SHA_B = "b" * 64
RELEASE = "c" * 40


def _outcome(
    *,
    source: EngineeringOutcomeSourceKind = EngineeringOutcomeSourceKind.PROMOTION,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    attribution: EngineeringOutcomeAttribution = (
        EngineeringOutcomeAttribution.NOT_APPLICABLE
    ),
    package: bool = False,
) -> EngineeringOutcomeV1:
    kwargs: dict[str, object] = {
        "change_id": "change-1",
    }
    if source is EngineeringOutcomeSourceKind.PROMOTION:
        kwargs.update(
            {
                "candidate_id": "candidate-1",
                "candidate_digest": SHA_A,
                "release_sha": RELEASE,
            }
        )
    if package:
        kwargs.update(
            {
                "package_id": "tv.control",
                "package_version": "1.0.0",
                "package_digest": SHA_B,
                "release_sha": RELEASE,
            }
        )
    return EngineeringOutcomeV1.create(
        source_kind=source,
        source_identity=f"{source.value}:source-1",
        subject_type=(
            "capability_package"
            if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
            else "promotion_candidate"
        ),
        subject_id=(
            "tv.control@1.0.0"
            if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
            else "candidate-1"
        ),
        subject_digest=SHA_B if package else SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=(
            "ready"
            if result is EngineeringOutcomeResult.SUCCESS
            else "candidate_runtime_regression",
        ),
        evidence_references=(
            "promotion-attempt:promotion-1",
            f"change-artifact:artifact-1:sha256:{SHA_A}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace=(
                    "package"
                    if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
                    else "jarvis.revision"
                ),
                target_identity=(
                    "tv.control"
                    if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
                    else RELEASE
                ),
                matcher_type=(
                    "version_exact"
                    if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
                    else "exact"
                ),
                constraint=(
                    {"version": "1.0.0"}
                    if source is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY
                    else {}
                ),
            ),
        ),
        observed_at_epoch=100.0,
        producer="phase10-projector-test",
        **kwargs,
    )


def test_positive_outcome_projects_and_persists_idempotently(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    projector = EngineeringLearningProjector()
    outcome = _outcome()

    first = projector.project(store, outcome)
    replay = projector.project(store, outcome)

    assert first == replace(first, created=True)
    assert replay == replace(first, created=False)
    revision = store.get_engineering_knowledge_revision(first.revision_id)
    assert revision is not None
    assert revision.kind_namespace == ENGINEERING_LEARNING_KIND_NAMESPACE
    assert revision.revision_number == 1
    assert (
        store.get_engineering_knowledge_lifecycle_state(first.revision_id)
        is KnowledgeLifecycleState.CANDIDATE
    )

    facets = store.list_engineering_knowledge_facets(first.revision_id)
    assert tuple(item.facet_type for item in facets) == (
        ENGINEERING_OUTCOME_FACET_TYPE,
    )
    assert json.loads(facets[0].payload_json or "{}")["result"] == "success"

    evidence = store.list_engineering_knowledge_evidence(first.revision_id)
    assert len(evidence) == 2
    digested = next(
        item
        for item in evidence
        if item.canonical_reference.startswith("change-artifact:")
    )
    assert digested.integrity_algorithm == "sha256"
    assert digested.integrity_digest == SHA_A

    attestations = store.list_engineering_attestations(
        subject_type="engineering_outcome",
        subject_id=outcome.outcome_id,
    )
    assert len(attestations) == 1
    assert (
        attestations[0].predicate_type
        == ENGINEERING_LEARNING_ATTESTATION_PREDICATE
    )


def test_candidate_local_failure_projects_outcome_and_regression_facets() -> None:
    outcome = _outcome(
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
    )

    candidate, decision = EngineeringLearningProjector().build_candidate(outcome)

    assert decision.disposition is LearningDisposition.NEGATIVE
    assert {item.facet_type for item in candidate.facets} == {
        ENGINEERING_OUTCOME_FACET_TYPE,
        ENGINEERING_REGRESSION_FACET_TYPE,
    }


def test_compatibility_projects_exact_compatibility_facet() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
        package=True,
    )

    candidate, decision = EngineeringLearningProjector().build_candidate(outcome)

    assert decision.disposition is LearningDisposition.COMPATIBILITY
    assert {item.facet_type for item in candidate.facets} == {
        ENGINEERING_OUTCOME_FACET_TYPE,
        ENGINEERING_COMPATIBILITY_FACET_TYPE,
    }
    compatibility = next(
        item
        for item in candidate.facets
        if item.facet_type == ENGINEERING_COMPATIBILITY_FACET_TYPE
    )
    payload = json.loads(compatibility.payload_json or "{}")
    assert payload["verdict"] == "ready"
    assert payload["applicability"][0]["constraint"] == {"version": "1.0.0"}


def test_external_provider_failure_is_rejected_before_projection() -> None:
    outcome = _outcome(
        result=EngineeringOutcomeResult.FAILURE,
        attribution=EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
    )

    with pytest.raises(
        EngineeringLearningProjectionError,
        match="not eligible",
    ):
        EngineeringLearningProjector().build_candidate(outcome)


def test_knowledge_identity_is_stable_across_contradictory_result() -> None:
    success = _outcome()
    failure = replace(
        success,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason_codes=("candidate_runtime_regression",),
    )
    projector = EngineeringLearningProjector()

    assert projector.knowledge_id_for(success) == projector.knowledge_id_for(failure)
    success_bundle, _ = projector.build_candidate(success)
    failure_bundle, _ = projector.build_candidate(failure)

    assert success_bundle.revision.revision_id != failure_bundle.revision.revision_id


def test_second_contradictory_revision_requires_explicit_revision_planning(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    projector = EngineeringLearningProjector()
    success = _outcome()
    failure = replace(
        success,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason_codes=("candidate_runtime_regression",),
    )

    projector.project(store, success)

    with pytest.raises(EngineeringKnowledgePersistenceConflictError):
        projector.project(store, failure)

    second = projector.project(
        store,
        failure,
        revision_number=2,
        parent_revision_id=projector.build_candidate(success)[0].revision.revision_id,
        supersedes_revision_id=projector.build_candidate(success)[0].revision.revision_id,
    )
    assert second.created is True
    revision = store.get_engineering_knowledge_revision(second.revision_id)
    assert revision is not None
    assert revision.revision_number == 2
    assert revision.parent_revision_id is not None
    assert revision.supersedes_revision_id == revision.parent_revision_id


def test_projection_fails_when_evidence_exceeds_knowledge_link_limit() -> None:
    outcome = replace(
        _outcome(),
        evidence_references=tuple(f"evidence:{index}" for index in range(33)),
    )

    with pytest.raises(
        EngineeringLearningProjectionError,
        match="evidence-link limit",
    ):
        EngineeringLearningProjector().build_candidate(outcome)
