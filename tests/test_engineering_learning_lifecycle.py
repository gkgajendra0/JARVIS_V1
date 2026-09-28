from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.engineering_knowledge import KnowledgeLifecycleState
from jarvis.engineering_knowledge.canonical import canonical_sha256
from jarvis.engineering_knowledge.lifecycle import (
    KnowledgeLifecycleError,
    KnowledgePromotionError,
)
from jarvis.engineering_knowledge.persistence import EngineeringKnowledgeCandidateBundle
from jarvis.engineering_learning.lifecycle import (
    EngineeringLearningIntegrityVerifier,
    EngineeringLearningLifecycleService,
    EngineeringLearningRevisionPlanner,
    EngineeringLearningRevisionPlanningError,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.projector import EngineeringLearningProjector
from jarvis.incidents.store import SqliteIncidentStore

SHA_A = "a" * 64
RELEASE = "c" * 40


def _promotion_outcome(
    *,
    source_identity: str,
    result: EngineeringOutcomeResult,
    attribution: EngineeringOutcomeAttribution,
    reason: str,
    evidence: str,
    observed: float,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity=source_identity,
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=(reason,),
        evidence_references=(evidence,),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=RELEASE,
                matcher_type="exact",
                constraint={},
            ),
        ),
        observed_at_epoch=observed,
        producer="phase10-lifecycle-test",
        change_id="change-1",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _success(
    *,
    source_identity: str = "promotion-success",
    observed: float = 100.0,
    evidence: str = "promotion-attempt:success",
) -> EngineeringOutcomeV1:
    return _promotion_outcome(
        source_identity=source_identity,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
        reason="runtime_healthy",
        evidence=evidence,
        observed=observed,
    )


def _failure(
    *,
    source_identity: str = "promotion-failure",
    observed: float = 200.0,
    evidence: str = "promotion-attempt:failure",
) -> EngineeringOutcomeV1:
    return _promotion_outcome(
        source_identity=source_identity,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason="candidate_runtime_regression",
        evidence=evidence,
        observed=observed,
    )


def _persist(
    store: SqliteIncidentStore,
    outcome: EngineeringOutcomeV1,
    *,
    revision_number: int = 1,
    parent_revision_id: str | None = None,
    supersedes_revision_id: str | None = None,
) -> str:
    result = EngineeringLearningProjector().project(
        store,
        outcome,
        revision_number=revision_number,
        parent_revision_id=parent_revision_id,
        supersedes_revision_id=supersedes_revision_id,
    )
    return result.revision_id


def test_learning_integrity_and_promotion_are_deterministic(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    revision_id = _persist(store, _success())

    integrity = EngineeringLearningIntegrityVerifier().verify(store, revision_id)
    assert integrity.valid is True
    assert integrity.reason_codes == ()

    lifecycle = EngineeringLearningLifecycleService(store)
    staged, accepted = lifecycle.promote(
        revision_id,
        staged_at_epoch=101.0,
        accepted_at_epoch=102.0,
    )

    assert staged.created is True
    assert accepted.created is True
    assert (
        store.get_engineering_knowledge_lifecycle_state(revision_id)
        is KnowledgeLifecycleState.ACCEPTED
    )

    replay = lifecycle.promote(
        revision_id,
        staged_at_epoch=103.0,
        accepted_at_epoch=104.0,
    )
    assert replay[0].created is False
    assert replay[1].created is False


def test_tampered_facet_payload_cannot_be_promoted(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    projector = EngineeringLearningProjector()
    candidate, _ = projector.build_candidate(_success())

    original = candidate.facets[0]
    assert original.payload_json is not None
    tampered_payload = original.payload_json.replace(
        '"runtime_healthy"',
        '"fabricated_healthy"',
    )
    tampered = replace(
        original,
        payload_json=tampered_payload,
        payload_digest=canonical_sha256(
            {
                **__import__("json").loads(tampered_payload),
            }
        ),
    )
    bad = EngineeringKnowledgeCandidateBundle(
        identity=candidate.identity,
        revision=candidate.revision,
        facets=(tampered,),
        applicability=candidate.applicability,
        evidence=candidate.evidence,
        evidence_links=candidate.evidence_links,
        lifecycle_event=candidate.lifecycle_event,
        attestations=candidate.attestations,
    )
    store.persist_engineering_knowledge_candidate(bad)

    integrity = EngineeringLearningIntegrityVerifier().verify(
        store,
        candidate.revision.revision_id,
    )
    assert integrity.valid is False
    assert "revision_digest_mismatch" in integrity.reason_codes

    with pytest.raises(KnowledgePromotionError, match="cannot be staged"):
        EngineeringLearningLifecycleService(store).stage(
            candidate.revision.revision_id,
            now_epoch=101.0,
        )


def test_revision_planner_replays_exact_outcome(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    outcome = _success()
    revision_id = _persist(store, outcome)
    EngineeringLearningLifecycleService(store).promote(
        revision_id,
        staged_at_epoch=101.0,
        accepted_at_epoch=102.0,
    )

    plan = EngineeringLearningRevisionPlanner().plan(store, outcome)

    assert plan.replay_revision_id == revision_id
    assert plan.revision_number == 1
    assert plan.reason_code == "exact_outcome_replay"


def test_equivalent_new_evidence_reuses_accepted_conclusion(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    first = _success()
    revision_id = _persist(store, first)
    EngineeringLearningLifecycleService(store).promote(
        revision_id,
        staged_at_epoch=101.0,
        accepted_at_epoch=102.0,
    )
    equivalent = _success(
        source_identity="promotion-success-2",
        observed=150.0,
        evidence="promotion-attempt:success-2",
    )

    plan = EngineeringLearningRevisionPlanner().plan(store, equivalent)

    assert plan.replay_revision_id == revision_id
    assert plan.reason_code == "equivalent_conclusion_already_accepted"


def test_contradiction_creates_successor_then_supersedes_prior(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    first = _success()
    first_revision = _persist(store, first)
    lifecycle = EngineeringLearningLifecycleService(store)
    lifecycle.promote(
        first_revision,
        staged_at_epoch=101.0,
        accepted_at_epoch=102.0,
    )

    contradiction = _failure()
    plan = EngineeringLearningRevisionPlanner().plan(store, contradiction)
    assert plan.revision_number == 2
    assert plan.parent_revision_id == first_revision
    assert plan.supersedes_revision_id == first_revision
    assert plan.replay_revision_id is None

    second_revision = _persist(
        store,
        contradiction,
        revision_number=plan.revision_number,
        parent_revision_id=plan.parent_revision_id,
        supersedes_revision_id=plan.supersedes_revision_id,
    )

    with pytest.raises(KnowledgeLifecycleError, match="successor must be accepted"):
        lifecycle.supersede(
            prior_revision_id=first_revision,
            successor_revision_id=second_revision,
            now_epoch=202.0,
        )

    lifecycle.promote(
        second_revision,
        staged_at_epoch=203.0,
        accepted_at_epoch=204.0,
    )
    result = lifecycle.supersede(
        prior_revision_id=first_revision,
        successor_revision_id=second_revision,
        now_epoch=205.0,
    )

    assert result.created is True
    assert (
        store.get_engineering_knowledge_lifecycle_state(first_revision)
        is KnowledgeLifecycleState.SUPERSEDED
    )
    assert (
        store.get_engineering_knowledge_lifecycle_state(second_revision)
        is KnowledgeLifecycleState.ACCEPTED
    )

    replay = lifecycle.supersede(
        prior_revision_id=first_revision,
        successor_revision_id=second_revision,
        now_epoch=206.0,
    )
    assert replay.created is False


def test_noncontradictory_successor_cannot_supersede_prior(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    first = _success()
    first_revision = _persist(store, first)
    lifecycle = EngineeringLearningLifecycleService(store)
    lifecycle.promote(
        first_revision,
        staged_at_epoch=101.0,
        accepted_at_epoch=102.0,
    )
    equivalent = _success(
        source_identity="promotion-success-2",
        observed=150.0,
        evidence="promotion-attempt:success-2",
    )

    second_revision = _persist(
        store,
        equivalent,
        revision_number=2,
        parent_revision_id=first_revision,
        supersedes_revision_id=first_revision,
    )
    lifecycle.promote(
        second_revision,
        staged_at_epoch=151.0,
        accepted_at_epoch=152.0,
    )

    with pytest.raises(KnowledgeLifecycleError, match="does not materially contradict"):
        lifecycle.supersede(
            prior_revision_id=first_revision,
            successor_revision_id=second_revision,
            now_epoch=153.0,
        )


def test_revision_planner_blocks_competing_pending_revision(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    _persist(store, _success())

    with pytest.raises(
        EngineeringLearningRevisionPlanningError,
        match="still pending",
    ):
        EngineeringLearningRevisionPlanner().plan(store, _failure())
