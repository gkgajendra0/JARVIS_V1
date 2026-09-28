"""Replay-safe Phase-10 engineering-learning reconciliation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_knowledge.lifecycle import (
    KnowledgeLifecycleError,
    KnowledgePromotionError,
)
from jarvis.engineering_knowledge.models import (
    EngineeringKnowledgeRevision,
    KnowledgeLifecycleState,
)
from jarvis.engineering_knowledge.persistence import (
    EngineeringKnowledgePersistenceConflictError,
)
from jarvis.engineering_knowledge.retrieval import (
    EngineeringKnowledgeRetrievalError,
    EngineeringKnowledgeRetrievalIndex,
)
from jarvis.incidents.store import SqliteIncidentStore

from .lifecycle import (
    EngineeringLearningLifecycleService,
    EngineeringLearningPromotionAssessment,
    EngineeringLearningPromotionPolicy,
)
from .models import EngineeringOutcomeV1
from .policy import EngineeringLearningEligibilityPolicy, LearningDisposition
from .projector import (
    EngineeringLearningProjectionError,
    EngineeringLearningProjector,
)
from .sources import EngineeringOutcomeSource, EngineeringOutcomeSourceScan


class LearningReconciliationStatus(StrEnum):
    LEARNED = "learned"
    RESUMED = "resumed"
    REPLAYED = "replayed"
    INCONCLUSIVE = "inconclusive"
    TERMINAL_IGNORED = "terminal_ignored"
    BLOCKED = "blocked"
    INDEX_RETRY_REQUIRED = "index_retry_required"


@dataclass(frozen=True, slots=True)
class LearningReconciliationItem:
    outcome_id: str
    outcome_digest: str
    knowledge_id: str | None
    revision_id: str | None
    status: LearningReconciliationStatus
    reason_codes: tuple[str, ...]
    disposition: LearningDisposition | None
    created_revision: bool


@dataclass(frozen=True, slots=True)
class EngineeringLearningReconciliationReport:
    items: tuple[LearningReconciliationItem, ...]
    source_errors: tuple[str, ...]
    processed_count: int
    learned_count: int
    blocked_count: int
    replay_count: int
    last_outcome_id: str | None

    @property
    def successful(self) -> bool:
        return self.blocked_count == 0 and not self.source_errors


class EngineeringLearningReconciler:
    """Reconcile bounded canonical outcomes into current accepted learning.

    No cursor store is required for correctness. Deterministic outcome/revision
    identities make a full bounded replay restart-safe. last_outcome_id is an
    advisory scan checkpoint only; losing it cannot duplicate knowledge.
    """

    def __init__(
        self,
        store: SqliteIncidentStore,
        *,
        index: EngineeringKnowledgeRetrievalIndex | None = None,
        projector: EngineeringLearningProjector | None = None,
        lifecycle: EngineeringLearningLifecycleService | None = None,
        promotion_policy: EngineeringLearningPromotionPolicy | None = None,
        eligibility_policy: EngineeringLearningEligibilityPolicy | None = None,
    ) -> None:
        if not isinstance(store, SqliteIncidentStore):
            raise TypeError("store must be SqliteIncidentStore")
        if index is not None and not isinstance(
            index,
            EngineeringKnowledgeRetrievalIndex,
        ):
            raise TypeError("index must be EngineeringKnowledgeRetrievalIndex or None")
        if index is not None and index.path.resolve() != store.path.resolve():
            raise ValueError("learning index must use the canonical engineering DB")
        self._store = store
        self._projector = projector or EngineeringLearningProjector()
        self._promotion_policy = (
            promotion_policy or EngineeringLearningPromotionPolicy()
        )
        self._eligibility = (
            eligibility_policy or EngineeringLearningEligibilityPolicy()
        )
        self._lifecycle = lifecycle or EngineeringLearningLifecycleService(
            store,
            promotion_policy=self._promotion_policy,
        )
        self._owns_index = index is None
        self._index = index or EngineeringKnowledgeRetrievalIndex(store.path)

    def close(self) -> None:
        if self._owns_index:
            self._index.close()
            self._owns_index = False

    def reconcile_source(
        self,
        source: EngineeringOutcomeSource,
        *,
        limit: int,
        now_epoch: float,
    ) -> EngineeringLearningReconciliationReport:
        if type(limit) is not int or limit <= 0:
            raise ValueError("reconciliation limit must be positive")
        timestamp = self._epoch(now_epoch)
        scan = source.scan(limit=limit, observed_at_epoch=timestamp)
        if not isinstance(scan, EngineeringOutcomeSourceScan):
            raise TypeError("outcome source returned an invalid scan result")
        return self.reconcile(
            scan.outcomes,
            limit=limit,
            now_epoch=timestamp,
            source_errors=scan.errors,
        )

    def reconcile(
        self,
        outcomes: tuple[EngineeringOutcomeV1, ...],
        *,
        limit: int,
        now_epoch: float,
        source_errors: tuple[str, ...] = (),
    ) -> EngineeringLearningReconciliationReport:
        if type(limit) is not int or limit <= 0:
            raise ValueError("reconciliation limit must be positive")
        timestamp = self._epoch(now_epoch)
        if not isinstance(outcomes, tuple) or any(
            not isinstance(item, EngineeringOutcomeV1) for item in outcomes
        ):
            raise TypeError("outcomes must be a tuple[EngineeringOutcomeV1, ...]")
        ordered = tuple(
            sorted(
                outcomes,
                key=lambda item: (
                    item.observed_at_epoch,
                    item.outcome_id,
                    item.digest,
                ),
            )
        )[:limit]

        items = tuple(
            self._reconcile_one(item, now_epoch=timestamp) for item in ordered
        )
        learned = sum(
            item.status
            in {
                LearningReconciliationStatus.LEARNED,
                LearningReconciliationStatus.RESUMED,
            }
            for item in items
        )
        blocked = sum(
            item.status
            in {
                LearningReconciliationStatus.BLOCKED,
                LearningReconciliationStatus.INDEX_RETRY_REQUIRED,
            }
            for item in items
        )
        replayed = sum(
            item.status is LearningReconciliationStatus.REPLAYED
            for item in items
        )
        return EngineeringLearningReconciliationReport(
            items=items,
            source_errors=tuple(str(item) for item in source_errors),
            processed_count=len(items),
            learned_count=learned,
            blocked_count=blocked,
            replay_count=replayed,
            last_outcome_id=(items[-1].outcome_id if items else None),
        )

    def _reconcile_one(
        self,
        outcome: EngineeringOutcomeV1,
        *,
        now_epoch: float,
    ) -> LearningReconciliationItem:
        eligibility = self._eligibility.evaluate(outcome)
        knowledge_id = self._projector.knowledge_id_for(outcome)
        if not eligibility.eligible:
            return LearningReconciliationItem(
                outcome_id=outcome.outcome_id,
                outcome_digest=outcome.digest,
                knowledge_id=knowledge_id,
                revision_id=None,
                status=LearningReconciliationStatus.INCONCLUSIVE,
                reason_codes=eligibility.reason_codes,
                disposition=eligibility.disposition,
                created_revision=False,
            )

        revisions = self._store.list_engineering_knowledge_revisions(knowledge_id)
        assessed: dict[str, EngineeringLearningPromotionAssessment] = {}
        for revision in revisions:
            assessment = self._promotion_policy.evaluate(
                self._store,
                revision.revision_id,
            )
            assessed[revision.revision_id] = assessment
            if assessment.outcome is None:
                return self._blocked(
                    outcome,
                    knowledge_id=knowledge_id,
                    revision_id=revision.revision_id,
                    reasons=("existing_revision_unverifiable",),
                    disposition=eligibility.disposition,
                )

        exact = self._find_exact(revisions, assessed, outcome)
        if exact is not None:
            return self._resume_existing(
                outcome,
                exact,
                assessed[exact.revision_id],
                now_epoch=now_epoch,
            )

        current_accepted = tuple(
            revision
            for revision in revisions
            if self._store.get_engineering_knowledge_lifecycle_state(
                revision.revision_id
            )
            is KnowledgeLifecycleState.ACCEPTED
        )
        if len(current_accepted) > 1:
            return self._blocked(
                outcome,
                knowledge_id=knowledge_id,
                revision_id=None,
                reasons=("multiple_current_accepted_revisions",),
                disposition=eligibility.disposition,
            )

        prior = current_accepted[0] if current_accepted else None
        latest = (
            max(revisions, key=lambda item: item.revision_number)
            if revisions
            else None
        )
        parent = prior or latest
        revision_number = (latest.revision_number + 1) if latest is not None else 1

        try:
            projection = self._projector.project(
                self._store,
                outcome,
                revision_number=revision_number,
                parent_revision_id=(
                    None if parent is None else parent.revision_id
                ),
                supersedes_revision_id=(
                    None if prior is None else prior.revision_id
                ),
            )
            self._lifecycle.promote(
                projection.revision_id,
                staged_at_epoch=now_epoch,
                accepted_at_epoch=now_epoch,
            )
            if prior is not None:
                self._lifecycle.supersede_prior(
                    projection.revision_id,
                    prior_revision_id=prior.revision_id,
                    now_epoch=now_epoch,
                )
        except (
            EngineeringLearningProjectionError,
            EngineeringKnowledgePersistenceConflictError,
            KnowledgeLifecycleError,
            KnowledgePromotionError,
            ValueError,
        ) as exc:
            return self._blocked(
                outcome,
                knowledge_id=knowledge_id,
                revision_id=None,
                reasons=(f"learning_write_failed:{type(exc).__name__}",),
                disposition=eligibility.disposition,
            )

        index_error = self._refresh_index(
            projection.revision_id,
            now_epoch=now_epoch,
        )
        if index_error is not None:
            return LearningReconciliationItem(
                outcome_id=outcome.outcome_id,
                outcome_digest=outcome.digest,
                knowledge_id=knowledge_id,
                revision_id=projection.revision_id,
                status=LearningReconciliationStatus.INDEX_RETRY_REQUIRED,
                reason_codes=(index_error,),
                disposition=eligibility.disposition,
                created_revision=projection.created,
            )
        return LearningReconciliationItem(
            outcome_id=outcome.outcome_id,
            outcome_digest=outcome.digest,
            knowledge_id=knowledge_id,
            revision_id=projection.revision_id,
            status=LearningReconciliationStatus.LEARNED,
            reason_codes=(),
            disposition=eligibility.disposition,
            created_revision=projection.created,
        )

    def _resume_existing(
        self,
        outcome: EngineeringOutcomeV1,
        revision: EngineeringKnowledgeRevision,
        assessment: EngineeringLearningPromotionAssessment,
        *,
        now_epoch: float,
    ) -> LearningReconciliationItem:
        state = self._store.get_engineering_knowledge_lifecycle_state(
            revision.revision_id
        )
        if state is None:
            return self._blocked(
                outcome,
                knowledge_id=revision.knowledge_id,
                revision_id=revision.revision_id,
                reasons=("existing_revision_missing_lifecycle_state",),
                disposition=assessment.disposition,
            )
        if state in {
            KnowledgeLifecycleState.REJECTED,
            KnowledgeLifecycleState.RETIRED,
            KnowledgeLifecycleState.SUPERSEDED,
        }:
            return LearningReconciliationItem(
                outcome_id=outcome.outcome_id,
                outcome_digest=outcome.digest,
                knowledge_id=revision.knowledge_id,
                revision_id=revision.revision_id,
                status=LearningReconciliationStatus.TERMINAL_IGNORED,
                reason_codes=(f"existing_revision_{state.value}",),
                disposition=assessment.disposition,
                created_revision=False,
            )

        resumed = state in {
            KnowledgeLifecycleState.CANDIDATE,
            KnowledgeLifecycleState.STAGED,
        }
        if resumed:
            try:
                self._lifecycle.promote(
                    revision.revision_id,
                    staged_at_epoch=now_epoch,
                    accepted_at_epoch=now_epoch,
                )
            except (KnowledgeLifecycleError, KnowledgePromotionError, ValueError) as exc:
                return self._blocked(
                    outcome,
                    knowledge_id=revision.knowledge_id,
                    revision_id=revision.revision_id,
                    reasons=(f"learning_resume_failed:{type(exc).__name__}",),
                    disposition=assessment.disposition,
                )

        if revision.supersedes_revision_id is not None:
            prior_state = self._store.get_engineering_knowledge_lifecycle_state(
                revision.supersedes_revision_id
            )
            if prior_state is KnowledgeLifecycleState.ACCEPTED:
                try:
                    self._lifecycle.supersede_prior(
                        revision.revision_id,
                        prior_revision_id=revision.supersedes_revision_id,
                        now_epoch=now_epoch,
                    )
                    resumed = True
                except (
                    KnowledgeLifecycleError,
                    KnowledgePromotionError,
                    ValueError,
                ) as exc:
                    return self._blocked(
                        outcome,
                        knowledge_id=revision.knowledge_id,
                        revision_id=revision.revision_id,
                        reasons=(
                            f"learning_supersession_resume_failed:{type(exc).__name__}",
                        ),
                        disposition=assessment.disposition,
                    )

        index_error = self._refresh_index(
            revision.revision_id,
            now_epoch=now_epoch,
        )
        if index_error is not None:
            return LearningReconciliationItem(
                outcome_id=outcome.outcome_id,
                outcome_digest=outcome.digest,
                knowledge_id=revision.knowledge_id,
                revision_id=revision.revision_id,
                status=LearningReconciliationStatus.INDEX_RETRY_REQUIRED,
                reason_codes=(index_error,),
                disposition=assessment.disposition,
                created_revision=False,
            )
        return LearningReconciliationItem(
            outcome_id=outcome.outcome_id,
            outcome_digest=outcome.digest,
            knowledge_id=revision.knowledge_id,
            revision_id=revision.revision_id,
            status=(
                LearningReconciliationStatus.RESUMED
                if resumed
                else LearningReconciliationStatus.REPLAYED
            ),
            reason_codes=(),
            disposition=assessment.disposition,
            created_revision=False,
        )

    @staticmethod
    def _find_exact(
        revisions: tuple[EngineeringKnowledgeRevision, ...],
        assessments: dict[str, EngineeringLearningPromotionAssessment],
        outcome: EngineeringOutcomeV1,
    ) -> EngineeringKnowledgeRevision | None:
        for revision in revisions:
            existing = assessments[revision.revision_id].outcome
            if (
                existing is not None
                and existing.outcome_id == outcome.outcome_id
                and existing.digest == outcome.digest
            ):
                return revision
        return None

    def _refresh_index(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> str | None:
        try:
            self._index.refresh_revision(
                revision_id,
                encoder=None,
                now_epoch=now_epoch,
            )
        except EngineeringKnowledgeRetrievalError as exc:
            return f"index_refresh_failed:{type(exc).__name__}"
        return None

    @staticmethod
    def _blocked(
        outcome: EngineeringOutcomeV1,
        *,
        knowledge_id: str | None,
        revision_id: str | None,
        reasons: tuple[str, ...],
        disposition: LearningDisposition | None,
    ) -> LearningReconciliationItem:
        return LearningReconciliationItem(
            outcome_id=outcome.outcome_id,
            outcome_digest=outcome.digest,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            status=LearningReconciliationStatus.BLOCKED,
            reason_codes=reasons,
            disposition=disposition,
            created_revision=False,
        )

    @staticmethod
    def _epoch(value: float) -> float:
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError("now_epoch must be finite and positive")
        return timestamp
