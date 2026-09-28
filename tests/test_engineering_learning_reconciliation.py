from __future__ import annotations

from pathlib import Path

from jarvis.engineering_knowledge import (
    ApplicabilityContext,
    ApplicabilityFact,
    EngineeringKnowledgeRetrievalIndex,
    EngineeringKnowledgeRetrievalPolicy,
    KnowledgeLifecycleService,
    KnowledgeLifecycleState,
)
from jarvis.engineering_learning.lifecycle import EngineeringLearningLifecycleService
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.projector import EngineeringLearningProjector
from jarvis.engineering_learning.reconciliation import (
    EngineeringLearningReconciler,
    LearningReconciliationStatus,
)
from jarvis.engineering_learning.sources import EngineeringOutcomeSourceScan
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
        producer="phase10-reconciliation-test",
        change_id="change-1",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _successor_outcome() -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity="promotion-2",
        subject_type="promotion_candidate",
        subject_id="candidate-1",
        subject_digest=SHA_A,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        reason_codes=("candidate_runtime_regression",),
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
        observed_at_epoch=101.0,
        producer="phase10-reconciliation-test",
        change_id="change-2",
        candidate_id="candidate-1",
        candidate_digest=SHA_A,
        release_sha=RELEASE,
    )


def _context() -> ApplicabilityContext:
    return ApplicabilityContext(
        facts=(
            ApplicabilityFact(
                target_namespace="jarvis.revision",
                target_identity=RELEASE,
                attributes={},
            ),
        )
    )


def test_reconcile_learns_accepts_and_indexes_verified_outcome(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    index = EngineeringKnowledgeRetrievalIndex(store.path)
    reconciler = EngineeringLearningReconciler(store, index=index)
    try:
        report = reconciler.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=110.0,
        )

        assert report.successful is True
        assert report.learned_count == 1
        item = report.items[0]
        assert item.status is LearningReconciliationStatus.LEARNED
        assert item.revision_id is not None
        assert (
            store.get_engineering_knowledge_lifecycle_state(item.revision_id)
            is KnowledgeLifecycleState.ACCEPTED
        )

        hits = index.retrieve(
            "candidate-1 runtime healthy",
            context=_context(),
            encoder=None,
            policy=EngineeringKnowledgeRetrievalPolicy.local(),
            now_epoch=111.0,
            limit=5,
        )
        assert tuple(hit.revision.revision_id for hit in hits) == (item.revision_id,)
    finally:
        index.close()
        store.close()


def test_reconcile_replay_and_restart_create_no_duplicate_revision(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    first = EngineeringLearningReconciler(store)
    try:
        learned = first.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        revision_id = learned.items[0].revision_id
        assert revision_id is not None
    finally:
        first.close()

    restarted = EngineeringLearningReconciler(store)
    try:
        replay = restarted.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=120.0,
        )

        assert replay.items[0].status is LearningReconciliationStatus.REPLAYED
        knowledge_id = replay.items[0].knowledge_id
        assert knowledge_id is not None
        revisions = store.list_engineering_knowledge_revisions(knowledge_id)
        assert tuple(item.revision_id for item in revisions) == (revision_id,)
    finally:
        restarted.close()
        store.close()


def test_reconciler_recovers_accepted_successor_before_prior_supersession(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    reconciler = EngineeringLearningReconciler(store)
    try:
        first = reconciler.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        prior_id = first.items[0].revision_id
        assert prior_id is not None

        successor_outcome = _successor_outcome()
        projector = EngineeringLearningProjector()
        projection = projector.project(
            store,
            successor_outcome,
            revision_number=2,
            parent_revision_id=prior_id,
            supersedes_revision_id=prior_id,
        )
        EngineeringLearningLifecycleService(store).promote(
            projection.revision_id,
            staged_at_epoch=120.0,
            accepted_at_epoch=121.0,
        )
        assert (
            store.get_engineering_knowledge_lifecycle_state(prior_id)
            is KnowledgeLifecycleState.ACCEPTED
        )

        recovered = reconciler.reconcile(
            (successor_outcome,),
            limit=10,
            now_epoch=130.0,
        )

        assert recovered.items[0].status is LearningReconciliationStatus.RESUMED
        assert (
            store.get_engineering_knowledge_lifecycle_state(prior_id)
            is KnowledgeLifecycleState.SUPERSEDED
        )
        assert (
            store.get_engineering_knowledge_lifecycle_state(projection.revision_id)
            is KnowledgeLifecycleState.ACCEPTED
        )
    finally:
        reconciler.close()
        store.close()


def test_new_verified_contradiction_supersedes_prior_and_retrieval_excludes_old(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    index = EngineeringKnowledgeRetrievalIndex(store.path)
    reconciler = EngineeringLearningReconciler(store, index=index)
    try:
        first = reconciler.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        old_id = first.items[0].revision_id
        assert old_id is not None

        regression = _successor_outcome()
        second = reconciler.reconcile(
            (regression,),
            limit=10,
            now_epoch=120.0,
        )
        new_id = second.items[0].revision_id
        assert new_id is not None
        assert new_id != old_id
        assert (
            store.get_engineering_knowledge_lifecycle_state(old_id)
            is KnowledgeLifecycleState.SUPERSEDED
        )
        assert (
            store.get_engineering_knowledge_lifecycle_state(new_id)
            is KnowledgeLifecycleState.ACCEPTED
        )

        hits = index.retrieve(
            "candidate runtime regression",
            context=_context(),
            encoder=None,
            policy=EngineeringKnowledgeRetrievalPolicy.local(),
            now_epoch=121.0,
            limit=10,
        )
        assert tuple(hit.revision.revision_id for hit in hits) == (new_id,)
    finally:
        index.close()
        store.close()


def test_external_failure_remains_inconclusive_and_creates_no_revision(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    reconciler = EngineeringLearningReconciler(store)
    try:
        external = _outcome(
            result=EngineeringOutcomeResult.FAILURE,
            attribution=EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
            reason="provider_quota",
        )
        report = reconciler.reconcile(
            (external,),
            limit=10,
            now_epoch=110.0,
        )

        assert report.items[0].status is LearningReconciliationStatus.INCONCLUSIVE
        knowledge_id = report.items[0].knowledge_id
        assert knowledge_id is not None
        assert store.list_engineering_knowledge_revisions(knowledge_id) == ()
    finally:
        reconciler.close()
        store.close()


def test_rejected_exact_outcome_is_never_resurrected(
    tmp_path: Path,
) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    reconciler = EngineeringLearningReconciler(store)
    try:
        projector = EngineeringLearningProjector()
        projection = projector.project(store, _outcome())
        evidence_ids = tuple(
            item.evidence_id
            for item in store.list_engineering_knowledge_evidence(
                projection.revision_id
            )
        )
        KnowledgeLifecycleService(store).reject(
            projection.revision_id,
            reason_code="review_rejected",
            actor="phase10-test",
            evidence_ids=evidence_ids,
            now_epoch=105.0,
        )

        report = reconciler.reconcile(
            (_outcome(),),
            limit=10,
            now_epoch=110.0,
        )

        assert report.items[0].status is LearningReconciliationStatus.TERMINAL_IGNORED
        assert (
            store.get_engineering_knowledge_lifecycle_state(projection.revision_id)
            is KnowledgeLifecycleState.REJECTED
        )
        knowledge_id = report.items[0].knowledge_id
        assert knowledge_id is not None
        assert len(store.list_engineering_knowledge_revisions(knowledge_id)) == 1
    finally:
        reconciler.close()
        store.close()


def test_reconciliation_is_bounded_and_reports_source_errors(tmp_path: Path) -> None:
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite3")
    reconciler = EngineeringLearningReconciler(store)

    class Source:
        source_id = "test"

        def scan(self, *, limit: int, observed_at_epoch: float):
            del limit, observed_at_epoch
            second = EngineeringOutcomeV1.create(
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
                observed_at_epoch=101.0,
                producer="phase10-test",
                candidate_id="candidate-2",
                candidate_digest="b" * 64,
                release_sha=RELEASE,
            )
            return EngineeringOutcomeSourceScan(
                source_id="test",
                outcomes=(_outcome(), second),
                errors=("source-record-3:invalid",),
            )

    try:
        report = reconciler.reconcile_source(
            Source(),
            limit=1,
            now_epoch=110.0,
        )

        assert report.processed_count == 1
        assert report.source_errors == ("source-record-3:invalid",)
        assert report.successful is False
        assert report.last_outcome_id == _outcome().outcome_id
    finally:
        reconciler.close()
        store.close()
