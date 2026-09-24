"""Deterministic EngineeringKnowledge lifecycle and strict repair promotion policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.canonical import canonical_sha256
from jarvis.engineering_knowledge.defaults import build_default_facet_registry
from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRevision,
    KnowledgeEvidenceLink,
    KnowledgeFreshnessState,
    KnowledgeLifecycleEvent,
    KnowledgeLifecycleState,
)
from jarvis.engineering_knowledge.projector import (
    REPAIR_KIND_NAMESPACE,
    REPAIR_VERIFICATION_PREDICATE,
)

REPAIR_PROMOTION_POLICY_ID = "repair-knowledge-promotion:v1"
REPAIR_PROMOTION_ACTOR = "repair-knowledge-promotion:v1"


class KnowledgeLifecycleError(ValueError):
    """A lifecycle transition or promotion request is invalid."""


class KnowledgePromotionError(KnowledgeLifecycleError):
    """A knowledge revision does not satisfy deterministic promotion policy."""


class KnowledgeLifecycleStore(Protocol):
    def get_engineering_knowledge_revision(
        self,
        revision_id: str,
    ) -> EngineeringKnowledgeRevision | None: ...

    def get_engineering_knowledge_lifecycle_state(
        self,
        revision_id: str,
    ) -> KnowledgeLifecycleState | None: ...

    def list_engineering_knowledge_facets(
        self,
        revision_id: str,
    ) -> tuple[EngineeringKnowledgeFacet, ...]: ...

    def list_engineering_knowledge_evidence_links(
        self,
        revision_id: str,
    ) -> tuple[KnowledgeEvidenceLink, ...]: ...

    def list_engineering_knowledge_applicability(
        self,
        revision_id: str,
    ) -> tuple[EngineeringApplicability, ...]: ...

    def list_engineering_attestations(
        self,
        *,
        subject_type: str,
        subject_id: str,
    ) -> tuple[EngineeringAttestation, ...]: ...

    def append_engineering_knowledge_lifecycle_event(
        self,
        event: KnowledgeLifecycleEvent,
        *,
        expected_from_state: KnowledgeLifecycleState,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class KnowledgePromotionDecision:
    eligible: bool
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeTransitionResult:
    revision_id: str
    from_state: KnowledgeLifecycleState
    to_state: KnowledgeLifecycleState
    created: bool


_ALLOWED_TRANSITIONS: dict[
    KnowledgeLifecycleState,
    frozenset[KnowledgeLifecycleState],
] = {
    KnowledgeLifecycleState.CANDIDATE: frozenset(
        {
            KnowledgeLifecycleState.STAGED,
            KnowledgeLifecycleState.REJECTED,
        }
    ),
    KnowledgeLifecycleState.STAGED: frozenset(
        {
            KnowledgeLifecycleState.ACCEPTED,
            KnowledgeLifecycleState.REJECTED,
        }
    ),
    KnowledgeLifecycleState.ACCEPTED: frozenset(
        {
            KnowledgeLifecycleState.RETIRED,
            KnowledgeLifecycleState.SUPERSEDED,
        }
    ),
    KnowledgeLifecycleState.REJECTED: frozenset(),
    KnowledgeLifecycleState.RETIRED: frozenset(),
    KnowledgeLifecycleState.SUPERSEDED: frozenset(),
}


class RepairKnowledgePromotionPolicy:
    """Strict initial policy for model-free, verifier-backed repair knowledge."""

    def evaluate(
        self,
        store: KnowledgeLifecycleStore,
        revision_id: str,
    ) -> KnowledgePromotionDecision:
        revision = store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            raise KnowledgePromotionError(
                f"unknown knowledge revision: {revision_id}"
            )

        reasons: list[str] = []
        evidence_ids: list[str] = []

        if revision.kind_namespace != REPAIR_KIND_NAMESPACE:
            reasons.append("wrong_kind_namespace")
        if revision.freshness_state is not KnowledgeFreshnessState.CURRENT:
            reasons.append("knowledge_not_current")

        facets = store.list_engineering_knowledge_facets(revision_id)
        if len(facets) != 1:
            reasons.append("repair_requires_exactly_one_facet")
        else:
            assessment = build_default_facet_registry().assess_for_decision(facets[0])
            if not assessment.eligible:
                reasons.append(assessment.reason_code)

        applicability = store.list_engineering_knowledge_applicability(revision_id)
        if not applicability:
            reasons.append("missing_applicability")
        elif not any(item.required for item in applicability):
            reasons.append("missing_required_applicability")

        links = store.list_engineering_knowledge_evidence_links(revision_id)
        relation_counts: dict[str, int] = {}
        for link in links:
            relation_counts[link.relation_type] = (
                relation_counts.get(link.relation_type, 0) + 1
            )
            if link.evidence_id not in evidence_ids:
                evidence_ids.append(link.evidence_id)

        if relation_counts.get("derived_from", 0) < 4:
            reasons.append("incomplete_source_provenance")
        if relation_counts.get("verified_by", 0) < 1:
            reasons.append("missing_verifier_evidence")
        if relation_counts.get("refutes", 0) > 0:
            reasons.append("blocking_refutation_present")

        attestations = store.list_engineering_attestations(
            subject_type="knowledge_revision",
            subject_id=revision_id,
        )
        matching = tuple(
            item
            for item in attestations
            if item.predicate_type == REPAIR_VERIFICATION_PREDICATE
            and item.subject_digest == revision.canonical_digest
            and item.verdict is AttestationVerdict.PASS
        )
        if len(matching) != 1:
            reasons.append("missing_unique_passing_repair_attestation")
        else:
            for evidence_id in matching[0].evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)

        return KnowledgePromotionDecision(
            eligible=not reasons,
            reason_codes=tuple(reasons),
            evidence_ids=tuple(evidence_ids),
        )


class KnowledgeLifecycleService:
    def __init__(
        self,
        store: KnowledgeLifecycleStore,
        *,
        repair_policy: RepairKnowledgePromotionPolicy | None = None,
    ) -> None:
        self._store = store
        self._repair_policy = repair_policy or RepairKnowledgePromotionPolicy()

    def stage_verified_repair(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        decision = self._repair_policy.evaluate(self._store, revision_id)
        if not decision.eligible:
            raise KnowledgePromotionError(
                "repair candidate cannot be staged: "
                + ",".join(decision.reason_codes)
            )
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.CANDIDATE,
            to_state=KnowledgeLifecycleState.STAGED,
            reason_code="repair_candidate_structurally_verified",
            actor=REPAIR_PROMOTION_ACTOR,
            policy_id=REPAIR_PROMOTION_POLICY_ID,
            evidence_ids=decision.evidence_ids,
            now_epoch=now_epoch,
        )

    def accept_verified_repair(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        decision = self._repair_policy.evaluate(self._store, revision_id)
        if not decision.eligible:
            raise KnowledgePromotionError(
                "staged repair cannot be accepted: "
                + ",".join(decision.reason_codes)
            )
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.STAGED,
            to_state=KnowledgeLifecycleState.ACCEPTED,
            reason_code="verified_repair_policy_satisfied",
            actor=REPAIR_PROMOTION_ACTOR,
            policy_id=REPAIR_PROMOTION_POLICY_ID,
            evidence_ids=decision.evidence_ids,
            now_epoch=now_epoch,
        )

    def promote_verified_repair(
        self,
        revision_id: str,
        *,
        staged_at_epoch: float,
        accepted_at_epoch: float,
    ) -> tuple[KnowledgeTransitionResult, KnowledgeTransitionResult]:
        current = self._require_state(revision_id)
        if current is KnowledgeLifecycleState.ACCEPTED:
            no_op = KnowledgeTransitionResult(
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.STAGED,
                to_state=KnowledgeLifecycleState.ACCEPTED,
                created=False,
            )
            return no_op, no_op
        if current is KnowledgeLifecycleState.CANDIDATE:
            staged = self.stage_verified_repair(
                revision_id,
                now_epoch=staged_at_epoch,
            )
        elif current is KnowledgeLifecycleState.STAGED:
            staged = KnowledgeTransitionResult(
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.CANDIDATE,
                to_state=KnowledgeLifecycleState.STAGED,
                created=False,
            )
        else:
            raise KnowledgeLifecycleError(
                f"cannot promote repair knowledge from {current.value}"
            )

        accepted = self.accept_verified_repair(
            revision_id,
            now_epoch=accepted_at_epoch,
        )
        return staged, accepted

    def reject(
        self,
        revision_id: str,
        *,
        reason_code: str,
        actor: str,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        current = self._require_state(revision_id)
        if current not in {
            KnowledgeLifecycleState.CANDIDATE,
            KnowledgeLifecycleState.STAGED,
        }:
            raise KnowledgeLifecycleError(
                f"cannot reject knowledge from {current.value}"
            )
        return self._transition(
            revision_id=revision_id,
            from_state=current,
            to_state=KnowledgeLifecycleState.REJECTED,
            reason_code=reason_code,
            actor=actor,
            policy_id=None,
            evidence_ids=evidence_ids,
            now_epoch=now_epoch,
        )

    def retire(
        self,
        revision_id: str,
        *,
        reason_code: str,
        actor: str,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.ACCEPTED,
            to_state=KnowledgeLifecycleState.RETIRED,
            reason_code=reason_code,
            actor=actor,
            policy_id=None,
            evidence_ids=evidence_ids,
            now_epoch=now_epoch,
        )

    def supersede(
        self,
        revision_id: str,
        *,
        reason_code: str,
        actor: str,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.ACCEPTED,
            to_state=KnowledgeLifecycleState.SUPERSEDED,
            reason_code=reason_code,
            actor=actor,
            policy_id=None,
            evidence_ids=evidence_ids,
            now_epoch=now_epoch,
        )

    def _require_state(self, revision_id: str) -> KnowledgeLifecycleState:
        current = self._store.get_engineering_knowledge_lifecycle_state(revision_id)
        if current is None:
            raise KnowledgeLifecycleError(
                f"unknown knowledge revision: {revision_id}"
            )
        return current

    def _transition(
        self,
        *,
        revision_id: str,
        from_state: KnowledgeLifecycleState,
        to_state: KnowledgeLifecycleState,
        reason_code: str,
        actor: str,
        policy_id: str | None,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        if to_state not in _ALLOWED_TRANSITIONS[from_state]:
            raise KnowledgeLifecycleError(
                f"illegal lifecycle transition {from_state.value}->{to_state.value}"
            )
        event = KnowledgeLifecycleEvent(
            event_id="lifecycle-event:"
            + canonical_sha256(
                {
                    "revision_id": revision_id,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "reason_code": str(reason_code).strip().casefold(),
                    "policy_id": str(policy_id).strip() if policy_id else None,
                }
            ),
            revision_id=revision_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            actor=actor,
            policy_id=policy_id,
            evidence_ids=evidence_ids,
            occurred_at_epoch=now_epoch,
        )
        created = self._store.append_engineering_knowledge_lifecycle_event(
            event,
            expected_from_state=from_state,
        )
        return KnowledgeTransitionResult(
            revision_id=revision_id,
            from_state=from_state,
            to_state=to_state,
            created=created,
        )
