from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.engineering_knowledge import (
    KnowledgeLifecycleError,
    KnowledgeLifecycleState,
    KnowledgePromotionError,
)
from jarvis.engineering_learning.lifecycle import (
    ENGINEERING_LEARNING_PROMOTION_POLICY_ID,
    EngineeringLearningLifecycleService,
    EngineeringLearningPromotionPolicy,
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
EVIDENCE_SHA = "d" * 64
RELEASE = "c" * 40


def _outcome(
    *,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    attribution: EngineeringOutcomeAttribution = (
        EngineeringOutcomeAttribution.NOT_APPLICABLE
    ),
    reason: str = "runtime_healthy",
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity="promotion-1",
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=(reason,),
        evidence_references=(
            "promotion-attempt:promotion-1",
            f"change-artifact:observation-1:sha256:{EVIDENCE_SHA}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=RELEASE,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ),
        observed_at_epoch=100.0,
        producer="phase10-lifecycle-test",
        change_id="change-1",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _successor_outcome(
    *,
    observed_at_epoch: float = 101.0,
    reason: str = "candidate_runtime_regression",
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity="promotion-2",
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason_codes=(reason,),
        evidence_references=(
            "promotion-attempt:promotion-2",
            f"change-artifact:observation-2:sha256:{EVIDENCE_SHA}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=RELEASE,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ),
        observed_at_epoch=observed_at_epoch,
        producer="phase10-lifecycle-test",
        change_id="change-2",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _persist(
    store: SqliteIncidentStore,
    outcome: EngineeringOutcomeV1,
    *,
    revision_number: int = 1,
    parent_revision_id: str | None = None,
    supersedes_revision_id: str | None = None,
):
    projector = EngineeringLearningProjector()
    identity = store.get_engineering_knowledge_identity(
        projector.knowledge_id_for(outcome)
    )
    candidate, _ = projector.build_candidate(
        outcome,
        revision_number=revision_number,
        parent_revision_id=parent_revision_id,
        supersedes_revision_id=supersedes_revision_id,
        identity=identity,
    )
    write = store.persist_engineering_knowledge_candidate(candidate)
    assert write.created is True
    return candidate, write.revision_id


def test_learning_candidate_promotes_to_accepted(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        candidate, revision_id = _persist(store, _outcome())
        policy = EngineeringLearningPromotionPolicy()
        assessment = policy.evaluate(store, revision_id)

        assert assessment.decision.eligible is True
        assert assessment.decision.reason_codes == ()
        assert assessment.outcome is not None
        assert assessment.outcome.digest == _outcome().digest

        staged, accepted = EngineeringLearningLifecycleService(store).promote(
            revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )

        assert staged.created is True
        assert accepted.created is True
        assert (
            store.get_engineering_knowledge_lifecycle_state(revision_id)
            is KnowledgeLifecycleState.ACCEPTED
        )
        assert set(assessment.decision.evidence_ids) == {
            item.evidence_id for item in candidate.evidence
        }
    finally:
        store.close()


def test_learning_promotion_is_idempotent_after_acceptance(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        _, revision_id = _persist(store, _outcome())
        lifecycle = EngineeringLearningLifecycleService(store)
        lifecycle.promote(
            revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )

        staged, accepted = lifecycle.promote(
            revision_id,
            staged_at_epoch=120.0,
            accepted_at_epoch=121.0,
        )

        assert staged.created is False
        assert accepted.created is False
    finally:
        store.close()


def test_missing_learning_attestation_blocks_staging(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        projector = EngineeringLearningProjector()
        candidate, _ = projector.build_candidate(_outcome())
        without_attestation = replace(candidate, attestations=())
        write = store.persist_engineering_knowledge_candidate(without_attestation)

        with pytest.raises(
            KnowledgePromotionError,
            match="missing_unique_passing_learning_attestation",
        ):
            EngineeringLearningLifecycleService(store).stage(
                write.revision_id,
                now_epoch=110.0,
            )
        assert (
            store.get_engineering_knowledge_lifecycle_state(write.revision_id)
            is KnowledgeLifecycleState.CANDIDATE
        )
    finally:
        store.close()


def test_tampered_revision_digest_blocks_staging(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        projector = EngineeringLearningProjector()
        candidate, _ = projector.build_candidate(_outcome())
        tampered_digest = "f" * 64
        tampered_revision = replace(
            candidate.revision,
            canonical_digest=tampered_digest,
        )
        tampered_attestation = replace(
            candidate.attestations[0],
            subject_digest=tampered_digest,
        )
        tampered = replace(
            candidate,
            revision=tampered_revision,
            attestations=(tampered_attestation,),
        )
        write = store.persist_engineering_knowledge_candidate(tampered)

        with pytest.raises(KnowledgePromotionError, match="revision_digest_mismatch"):
            EngineeringLearningLifecycleService(store).stage(
                write.revision_id,
                now_epoch=110.0,
            )
    finally:
        store.close()


def test_successor_must_be_accepted_before_prior_is_superseded(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        first, first_revision_id = _persist(store, _outcome())
        lifecycle = EngineeringLearningLifecycleService(store)
        lifecycle.promote(
            first_revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )

        successor_outcome = _successor_outcome()
        _, successor_revision_id = _persist(
            store,
            successor_outcome,
            revision_number=2,
            parent_revision_id=first.revision.revision_id,
            supersedes_revision_id=first.revision.revision_id,
        )

        with pytest.raises(
            KnowledgeLifecycleError,
            match="must be ACCEPTED",
        ):
            lifecycle.supersede_prior(
                successor_revision_id,
                prior_revision_id=first_revision_id,
                now_epoch=120.0,
            )

        staged, accepted, superseded = lifecycle.promote_successor_and_supersede(
            successor_revision_id,
            prior_revision_id=first_revision_id,
            staged_at_epoch=121.0,
            accepted_at_epoch=122.0,
            superseded_at_epoch=123.0,
        )

        assert staged.created is True
        assert accepted.created is True
        assert superseded.created is True
        assert (
            store.get_engineering_knowledge_lifecycle_state(successor_revision_id)
            is KnowledgeLifecycleState.ACCEPTED
        )
        assert (
            store.get_engineering_knowledge_lifecycle_state(first_revision_id)
            is KnowledgeLifecycleState.SUPERSEDED
        )
    finally:
        store.close()


def test_supersession_replay_is_idempotent(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        first, first_revision_id = _persist(store, _outcome())
        lifecycle = EngineeringLearningLifecycleService(store)
        lifecycle.promote(
            first_revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )
        successor_outcome = _successor_outcome()
        _, successor_revision_id = _persist(
            store,
            successor_outcome,
            revision_number=2,
            parent_revision_id=first.revision.revision_id,
            supersedes_revision_id=first.revision.revision_id,
        )
        lifecycle.promote_successor_and_supersede(
            successor_revision_id,
            prior_revision_id=first_revision_id,
            staged_at_epoch=121.0,
            accepted_at_epoch=122.0,
            superseded_at_epoch=123.0,
        )

        replay = lifecycle.supersede_prior(
            successor_revision_id,
            prior_revision_id=first_revision_id,
            now_epoch=130.0,
        )

        assert replay.created is False
        assert replay.to_state is KnowledgeLifecycleState.SUPERSEDED
    finally:
        store.close()


def test_unrelated_revision_cannot_supersede_accepted_knowledge(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        _first, first_revision_id = _persist(store, _outcome())
        lifecycle = EngineeringLearningLifecycleService(store)
        lifecycle.promote(
            first_revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )

        unrelated = EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.PROMOTION,
            source_identity="promotion-2",
            subject_type="promotion_candidate",
            subject_id="candidate-2",
            subject_digest="b" * 64,
            result=EngineeringOutcomeResult.SUCCESS,
            attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
            reason_codes=("runtime_healthy",),
            evidence_references=("promotion-attempt:promotion-2",),
            applicability=(
                OutcomeApplicability(
                    target_namespace="jarvis.revision",
                    target_identity=RELEASE,
                    matcher_type="exact",
                    constraint={},
                ),
            ),
            observed_at_epoch=100.0,
            producer="phase10-lifecycle-test",
            candidate_id="candidate-2",
            candidate_digest="b" * 64,
            release_sha=RELEASE,
        )
        _, unrelated_revision_id = _persist(store, unrelated)
        lifecycle.promote(
            unrelated_revision_id,
            staged_at_epoch=112.0,
            accepted_at_epoch=113.0,
        )

        with pytest.raises(
            KnowledgeLifecycleError,
            match="stable knowledge identity",
        ):
            lifecycle.supersede_prior(
                unrelated_revision_id,
                prior_revision_id=first_revision_id,
                now_epoch=120.0,
            )
    finally:
        store.close()


def test_lifecycle_events_use_phase10_promotion_policy_id(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        _, revision_id = _persist(store, _outcome())
        service = EngineeringLearningLifecycleService(store)
        staged = service.stage(revision_id, now_epoch=110.0)

        assert staged.to_state is KnowledgeLifecycleState.STAGED
        with store._lock:
            row = store._connection.execute(
                """
                SELECT policy_id
                FROM engineering_knowledge_lifecycle_event
                WHERE revision_id=? AND to_state=?
                """,
                (revision_id, KnowledgeLifecycleState.STAGED.value),
            ).fetchone()
        assert row is not None
        assert row[0] == ENGINEERING_LEARNING_PROMOTION_POLICY_ID
    finally:
        store.close()


def test_older_or_same_time_evidence_cannot_be_promoted_as_successor(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    try:
        first, first_revision_id = _persist(store, _outcome())
        lifecycle = EngineeringLearningLifecycleService(store)
        lifecycle.promote(
            first_revision_id,
            staged_at_epoch=110.0,
            accepted_at_epoch=111.0,
        )

        delayed = _successor_outcome(
            observed_at_epoch=100.0,
            reason="delayed_candidate_regression",
        )
        _, delayed_revision_id = _persist(
            store,
            delayed,
            revision_number=2,
            parent_revision_id=first.revision.revision_id,
            supersedes_revision_id=first.revision.revision_id,
        )

        with pytest.raises(
            KnowledgePromotionError,
            match="supersession_evidence_not_newer",
        ):
            lifecycle.promote(
                delayed_revision_id,
                staged_at_epoch=120.0,
                accepted_at_epoch=121.0,
            )

        assert (
            store.get_engineering_knowledge_lifecycle_state(first_revision_id)
            is KnowledgeLifecycleState.ACCEPTED
        )
        assert (
            store.get_engineering_knowledge_lifecycle_state(delayed_revision_id)
            is KnowledgeLifecycleState.CANDIDATE
        )
    finally:
        store.close()
