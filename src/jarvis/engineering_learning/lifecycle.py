"""Integrity, promotion, revision planning and supersession for Phase-10 learning."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.applicability import build_default_applicability_registry
from jarvis.engineering_knowledge.canonical import canonical_sha256, parse_json_object
from jarvis.engineering_knowledge.defaults import build_default_facet_registry
from jarvis.engineering_knowledge.lifecycle import (
    KnowledgeLifecycleError,
    KnowledgePromotionError,
    KnowledgeTransitionResult,
)
from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRevision,
    KnowledgeEvidenceLink,
    KnowledgeFreshnessState,
    KnowledgeLifecycleEvent,
    KnowledgeLifecycleState,
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
from jarvis.engineering_learning.policy import (
    ENGINEERING_LEARNING_POLICY_ID,
    EngineeringLearningEligibilityPolicy,
    LearningDisposition,
)
from jarvis.engineering_learning.projector import (
    ENGINEERING_LEARNING_ATTESTATION_PREDICATE,
    ENGINEERING_LEARNING_KIND_NAMESPACE,
    ENGINEERING_LEARNING_PROJECTOR_ID,
    EngineeringLearningProjector,
    engineering_learning_evidence_id,
    engineering_learning_revision_digest,
)

ENGINEERING_LEARNING_PROMOTION_POLICY_ID = "engineering-learning-promotion:v1"
ENGINEERING_LEARNING_PROMOTION_ACTOR = "engineering-learning-promotion:v1"
ENGINEERING_LEARNING_SUPERSESSION_ACTOR = "engineering-learning-supersession:v1"
_SHA256_REF = re.compile(r"(?:^|:)sha256:([0-9a-f]{64})(?:$|:)")


class EngineeringLearningLifecycleStore(Protocol):
    def get_engineering_knowledge_revision(
        self,
        revision_id: str,
    ) -> EngineeringKnowledgeRevision | None: ...

    def list_engineering_knowledge_revisions(
        self,
        knowledge_id: str,
    ) -> tuple[EngineeringKnowledgeRevision, ...]: ...

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

    def list_engineering_knowledge_evidence(
        self,
        revision_id: str,
    ) -> tuple[EngineeringEvidence, ...]: ...

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
class EngineeringLearningIntegrityDecision:
    valid: bool
    reason_codes: tuple[str, ...]
    outcome: EngineeringOutcomeV1 | None = None
    disposition: LearningDisposition | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EngineeringLearningPromotionDecision:
    eligible: bool
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    outcome: EngineeringOutcomeV1 | None = None
    disposition: LearningDisposition | None = None


@dataclass(frozen=True, slots=True)
class EngineeringLearningRevisionPlan:
    knowledge_id: str
    revision_number: int
    parent_revision_id: str | None
    supersedes_revision_id: str | None
    replay_revision_id: str | None
    reason_code: str


class EngineeringLearningRevisionPlanningError(KnowledgeLifecycleError):
    """A new immutable learning revision cannot be planned safely."""


def _outcome_from_payload(payload: dict[str, object]) -> EngineeringOutcomeV1:
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("engineering outcome lineage must be an object")
    raw_applicability = payload.get("applicability")
    if not isinstance(raw_applicability, list) or not raw_applicability:
        raise ValueError("engineering outcome applicability must be non-empty")

    applicability: list[OutcomeApplicability] = []
    for raw in raw_applicability:
        if not isinstance(raw, dict):
            raise ValueError("engineering outcome applicability item must be an object")
        constraint = raw.get("constraint")
        if not isinstance(constraint, dict):
            raise ValueError("engineering outcome constraint must be an object")
        applicability.append(
            OutcomeApplicability(
                target_namespace=str(raw.get("target_namespace") or ""),
                target_identity=str(raw.get("target_identity") or ""),
                matcher_type=str(raw.get("matcher_type") or ""),
                constraint=constraint,
                required=raw.get("required") is True,
            )
        )

    reason_codes = payload.get("reason_codes")
    evidence_references = payload.get("evidence_references")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("engineering outcome reason_codes must be strings")
    if not isinstance(evidence_references, list) or not all(
        isinstance(item, str) for item in evidence_references
    ):
        raise ValueError("engineering outcome evidence_references must be strings")

    observed = payload.get("observed_at_epoch")
    if isinstance(observed, bool) or not isinstance(observed, int | float):
        raise ValueError("engineering outcome observed_at_epoch must be numeric")
    observed_epoch = float(observed)
    if not math.isfinite(observed_epoch) or observed_epoch <= 0:
        raise ValueError("engineering outcome observed_at_epoch must be positive")

    return EngineeringOutcomeV1(
        outcome_id=str(payload.get("outcome_id") or ""),
        source_kind=EngineeringOutcomeSourceKind(str(payload.get("source_kind") or "")),
        source_identity=str(payload.get("source_identity") or ""),
        subject_type=str(payload.get("subject_type") or ""),
        subject_id=str(payload.get("subject_id") or ""),
        subject_digest=str(payload.get("subject_digest") or ""),
        result=EngineeringOutcomeResult(str(payload.get("result") or "")),
        attribution=EngineeringOutcomeAttribution(
            str(payload.get("attribution") or "")
        ),
        reason_codes=tuple(reason_codes),
        evidence_references=tuple(evidence_references),
        applicability=tuple(applicability),
        observed_at_epoch=observed_epoch,
        producer=str(payload.get("producer") or ""),
        change_id=(
            str(lineage["change_id"])
            if lineage.get("change_id") is not None
            else None
        ),
        candidate_id=(
            str(lineage["candidate_id"])
            if lineage.get("candidate_id") is not None
            else None
        ),
        candidate_digest=(
            str(lineage["candidate_digest"])
            if lineage.get("candidate_digest") is not None
            else None
        ),
        release_sha=(
            str(lineage["release_sha"])
            if lineage.get("release_sha") is not None
            else None
        ),
        package_id=(
            str(lineage["package_id"])
            if lineage.get("package_id") is not None
            else None
        ),
        package_version=(
            str(lineage["package_version"])
            if lineage.get("package_version") is not None
            else None
        ),
        package_digest=(
            str(lineage["package_digest"])
            if lineage.get("package_digest") is not None
            else None
        ),
    )


def engineering_learning_outcome(
    store: EngineeringLearningLifecycleStore,
    revision_id: str,
) -> EngineeringOutcomeV1:
    facets = store.list_engineering_knowledge_facets(revision_id)
    outcomes = tuple(
        item for item in facets if item.facet_type == ENGINEERING_OUTCOME_FACET_TYPE
    )
    if len(outcomes) != 1 or outcomes[0].payload_json is None:
        raise ValueError("learning revision requires exactly one readable outcome facet")
    payload = parse_json_object(outcomes[0].payload_json)
    return _outcome_from_payload(payload)


def _semantic_applicability(
    items: tuple[EngineeringApplicability, ...],
) -> tuple[tuple[str, str, str, str, bool], ...]:
    return tuple(
        sorted(
            (
                item.target_namespace,
                item.target_identity,
                item.matcher_type,
                canonical_sha256(parse_json_object(item.constraint_json)),
                item.required,
            )
            for item in items
        )
    )


def _outcome_applicability(
    outcome: EngineeringOutcomeV1,
) -> tuple[tuple[str, str, str, str, bool], ...]:
    return tuple(
        sorted(
            (
                item.target_namespace,
                item.target_identity,
                item.matcher_type,
                canonical_sha256(item.constraint),
                item.required,
            )
            for item in outcome.applicability
        )
    )


def _reference_digest(reference: str) -> str | None:
    match = _SHA256_REF.search(reference.casefold())
    return match.group(1) if match is not None else None


class EngineeringLearningIntegrityVerifier:
    """Independently reconstruct and verify one Phase-10 learning revision."""

    def verify(
        self,
        store: EngineeringLearningLifecycleStore,
        revision_id: str,
    ) -> EngineeringLearningIntegrityDecision:
        revision = store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            return EngineeringLearningIntegrityDecision(False, ("unknown_revision",))

        reasons: list[str] = []
        if revision.kind_namespace != ENGINEERING_LEARNING_KIND_NAMESPACE:
            reasons.append("wrong_kind_namespace")
        if revision.created_by != ENGINEERING_LEARNING_PROJECTOR_ID:
            reasons.append("unexpected_revision_producer")
        if revision.freshness_state is not KnowledgeFreshnessState.CURRENT:
            reasons.append("knowledge_not_current")
        if revision.revision_number == 1 and (
            revision.parent_revision_id is not None
            or revision.supersedes_revision_id is not None
        ):
            reasons.append("first_revision_has_parent_or_supersedes")
        if revision.revision_number > 1 and revision.parent_revision_id is None:
            reasons.append("later_revision_missing_parent")

        facets = store.list_engineering_knowledge_facets(revision_id)
        allowed = {
            ENGINEERING_OUTCOME_FACET_TYPE,
            ENGINEERING_REGRESSION_FACET_TYPE,
            ENGINEERING_COMPATIBILITY_FACET_TYPE,
        }
        if not facets:
            reasons.append("missing_facets")
        if any(item.facet_type not in allowed for item in facets):
            reasons.append("unexpected_facet_type")

        registry = build_default_facet_registry()
        validated = []
        for facet in facets:
            assessment = registry.assess_for_decision(facet)
            if not assessment.eligible or assessment.validated is None:
                reasons.append(f"facet:{assessment.reason_code}")
                continue
            validated.append(assessment.validated)

        outcome: EngineeringOutcomeV1 | None = None
        decision = None
        outcome_facets = tuple(
            item for item in validated if item.facet.facet_type == ENGINEERING_OUTCOME_FACET_TYPE
        )
        if len(outcome_facets) != 1:
            reasons.append("requires_exactly_one_outcome_facet")
        else:
            try:
                outcome = _outcome_from_payload(outcome_facets[0].payload)
                decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)
            except (TypeError, ValueError, KeyError) as exc:
                reasons.append(f"outcome_reconstruction_failed:{type(exc).__name__}")

        if outcome is not None and decision is not None:
            if not decision.eligible:
                reasons.append("outcome_no_longer_eligible")
            expected_facet_types = {ENGINEERING_OUTCOME_FACET_TYPE}
            if decision.disposition is LearningDisposition.NEGATIVE:
                expected_facet_types.add(ENGINEERING_REGRESSION_FACET_TYPE)
            elif decision.disposition is LearningDisposition.COMPATIBILITY:
                expected_facet_types.add(ENGINEERING_COMPATIBILITY_FACET_TYPE)
            actual_facet_types = {item.facet.facet_type for item in validated}
            if actual_facet_types != expected_facet_types:
                reasons.append("facet_set_does_not_match_learning_disposition")

            expected_knowledge_id = EngineeringLearningProjector.knowledge_id_for(outcome)
            if revision.knowledge_id != expected_knowledge_id:
                reasons.append("knowledge_identity_mismatch")
            if revision.valid_from_epoch != outcome.observed_at_epoch:
                reasons.append("valid_from_mismatch")
            if revision.system_from_epoch != outcome.observed_at_epoch:
                reasons.append("system_from_mismatch")
            if revision.created_at_epoch != outcome.observed_at_epoch:
                reasons.append("created_at_mismatch")

        applicability = store.list_engineering_knowledge_applicability(revision_id)
        if not applicability:
            reasons.append("missing_applicability")
        elif not any(item.required for item in applicability):
            reasons.append("missing_required_applicability")
        if outcome is not None:
            try:
                if _semantic_applicability(applicability) != _outcome_applicability(
                    outcome
                ):
                    reasons.append("applicability_mismatch")
            except (TypeError, ValueError):
                reasons.append("invalid_persisted_applicability")
        applicability_registry = build_default_applicability_registry()
        if any(
            applicability_registry.matcher_for(item) is None for item in applicability
        ):
            reasons.append("unsupported_applicability_matcher")

        evidence = store.list_engineering_knowledge_evidence(revision_id)
        links = store.list_engineering_knowledge_evidence_links(revision_id)
        evidence_ids = tuple(sorted(item.evidence_id for item in evidence))
        if outcome is not None:
            expected_evidence_ids = tuple(
                sorted(
                    engineering_learning_evidence_id(
                        outcome_id=outcome.outcome_id,
                        ordinal=ordinal,
                        reference=reference,
                    )
                    for ordinal, reference in enumerate(
                        outcome.evidence_references,
                        start=1,
                    )
                )
            )
            if evidence_ids != expected_evidence_ids:
                reasons.append("evidence_identity_mismatch")
            evidence_by_id = {item.evidence_id: item for item in evidence}
            for ordinal, reference in enumerate(
                outcome.evidence_references,
                start=1,
            ):
                expected_id = engineering_learning_evidence_id(
                    outcome_id=outcome.outcome_id,
                    ordinal=ordinal,
                    reference=reference,
                )
                item = evidence_by_id.get(expected_id)
                if item is None:
                    continue
                if item.evidence_type != "engineering_outcome_source":
                    reasons.append("unexpected_evidence_type")
                if item.source_class != "authoritative_engineering_record":
                    reasons.append("unexpected_evidence_source")
                if item.canonical_reference != reference:
                    reasons.append("evidence_reference_mismatch")
                if item.producer != ENGINEERING_LEARNING_PROJECTOR_ID:
                    reasons.append("unexpected_evidence_producer")
                expected_digest = _reference_digest(reference)
                if expected_digest is not None and (
                    item.integrity_algorithm != "sha256"
                    or item.integrity_digest != expected_digest
                ):
                    reasons.append("evidence_integrity_mismatch")
                if expected_digest is None and (
                    item.integrity_algorithm is not None
                    or item.integrity_digest is not None
                ):
                    reasons.append("unexpected_evidence_integrity")

        linked = tuple(
            sorted(
                item.evidence_id
                for item in links
                if item.relation_type == "supports_engineering_outcome"
            )
        )
        if linked != evidence_ids or len(links) != len(evidence_ids):
            reasons.append("evidence_link_mismatch")

        if outcome is not None and decision is not None:
            attestations = store.list_engineering_attestations(
                subject_type="engineering_outcome",
                subject_id=outcome.outcome_id,
            )
            matching = tuple(
                item
                for item in attestations
                if item.predicate_type
                == ENGINEERING_LEARNING_ATTESTATION_PREDICATE
                and item.subject_digest == outcome.digest
                and item.verdict is AttestationVerdict.PASS
                and tuple(sorted(item.evidence_ids)) == evidence_ids
            )
            if len(matching) != 1:
                reasons.append("missing_unique_passing_learning_attestation")
            else:
                try:
                    expected = parse_json_object(matching[0].expected_contract_json)
                    observed = parse_json_object(matching[0].observed_result_json)
                    if (
                        expected.get("policy_id") != ENGINEERING_LEARNING_POLICY_ID
                        or expected.get("eligible") is not True
                        or expected.get("disposition") != decision.disposition.value
                    ):
                        reasons.append("attestation_expected_contract_mismatch")
                    if (
                        observed.get("result") != outcome.result.value
                        or observed.get("attribution") != outcome.attribution.value
                        or observed.get("reason_codes") != list(outcome.reason_codes)
                        or observed.get("decision_reason_codes")
                        != list(decision.reason_codes)
                    ):
                        reasons.append("attestation_observed_result_mismatch")
                except ValueError:
                    reasons.append("attestation_json_invalid")

            expected_digest = engineering_learning_revision_digest(
                policy_id=decision.policy_id,
                knowledge_id=revision.knowledge_id,
                revision_number=revision.revision_number,
                parent_revision_id=revision.parent_revision_id,
                supersedes_revision_id=revision.supersedes_revision_id,
                normalized_summary=revision.normalized_summary,
                outcome=outcome,
                facets=facets,
                applicability=applicability,
                evidence_ids=evidence_ids,
            )
            if revision.canonical_digest != expected_digest:
                reasons.append("revision_digest_mismatch")

        return EngineeringLearningIntegrityDecision(
            valid=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
            outcome=outcome,
            disposition=None if decision is None else decision.disposition,
            evidence_ids=evidence_ids,
        )


class EngineeringLearningPromotionPolicy:
    """Strict model-free promotion policy for Phase-10 learning."""

    policy_id = ENGINEERING_LEARNING_PROMOTION_POLICY_ID

    def evaluate(
        self,
        store: EngineeringLearningLifecycleStore,
        revision_id: str,
    ) -> EngineeringLearningPromotionDecision:
        integrity = EngineeringLearningIntegrityVerifier().verify(store, revision_id)
        reasons = [f"integrity:{item}" for item in integrity.reason_codes]
        if integrity.outcome is None:
            reasons.append("missing_reconstructed_outcome")
        if integrity.disposition not in {
            LearningDisposition.POSITIVE,
            LearningDisposition.NEGATIVE,
            LearningDisposition.COMPATIBILITY,
        }:
            reasons.append("non_promotable_learning_disposition")
        return EngineeringLearningPromotionDecision(
            eligible=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_ids=integrity.evidence_ids,
            outcome=integrity.outcome,
            disposition=integrity.disposition,
        )


class EngineeringLearningLifecycleService:
    def __init__(
        self,
        store: EngineeringLearningLifecycleStore,
        *,
        promotion_policy: EngineeringLearningPromotionPolicy | None = None,
    ) -> None:
        self._store = store
        self._promotion_policy = promotion_policy or EngineeringLearningPromotionPolicy()

    def stage(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        current = self._require_state(revision_id)
        if current is KnowledgeLifecycleState.STAGED:
            return KnowledgeTransitionResult(
                revision_id,
                KnowledgeLifecycleState.CANDIDATE,
                KnowledgeLifecycleState.STAGED,
                False,
            )
        if current is not KnowledgeLifecycleState.CANDIDATE:
            raise KnowledgeLifecycleError(
                f"cannot stage learning knowledge from {current.value}"
            )
        decision = self._promotion_policy.evaluate(self._store, revision_id)
        if not decision.eligible:
            raise KnowledgePromotionError(
                "learning candidate cannot be staged: "
                + ",".join(decision.reason_codes)
            )
        return self._transition(
            revision_id,
            KnowledgeLifecycleState.CANDIDATE,
            KnowledgeLifecycleState.STAGED,
            reason_code="engineering_learning_integrity_verified",
            policy_id=self._promotion_policy.policy_id,
            evidence_ids=decision.evidence_ids,
            now_epoch=now_epoch,
        )

    def accept(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        current = self._require_state(revision_id)
        if current is KnowledgeLifecycleState.ACCEPTED:
            return KnowledgeTransitionResult(
                revision_id,
                KnowledgeLifecycleState.STAGED,
                KnowledgeLifecycleState.ACCEPTED,
                False,
            )
        if current is not KnowledgeLifecycleState.STAGED:
            raise KnowledgeLifecycleError(
                f"cannot accept learning knowledge from {current.value}"
            )
        decision = self._promotion_policy.evaluate(self._store, revision_id)
        if not decision.eligible:
            raise KnowledgePromotionError(
                "staged learning cannot be accepted: "
                + ",".join(decision.reason_codes)
            )
        return self._transition(
            revision_id,
            KnowledgeLifecycleState.STAGED,
            KnowledgeLifecycleState.ACCEPTED,
            reason_code="engineering_learning_policy_satisfied",
            policy_id=self._promotion_policy.policy_id,
            evidence_ids=decision.evidence_ids,
            now_epoch=now_epoch,
        )

    def promote(
        self,
        revision_id: str,
        *,
        staged_at_epoch: float,
        accepted_at_epoch: float,
    ) -> tuple[KnowledgeTransitionResult, KnowledgeTransitionResult]:
        current = self._require_state(revision_id)
        if current is KnowledgeLifecycleState.ACCEPTED:
            no_op = KnowledgeTransitionResult(
                revision_id,
                KnowledgeLifecycleState.STAGED,
                KnowledgeLifecycleState.ACCEPTED,
                False,
            )
            return no_op, no_op
        if current is KnowledgeLifecycleState.CANDIDATE:
            staged = self.stage(revision_id, now_epoch=staged_at_epoch)
        elif current is KnowledgeLifecycleState.STAGED:
            staged = KnowledgeTransitionResult(
                revision_id,
                KnowledgeLifecycleState.CANDIDATE,
                KnowledgeLifecycleState.STAGED,
                False,
            )
        else:
            raise KnowledgeLifecycleError(
                f"cannot promote learning knowledge from {current.value}"
            )
        accepted = self.accept(revision_id, now_epoch=accepted_at_epoch)
        return staged, accepted

    def supersede(
        self,
        *,
        prior_revision_id: str,
        successor_revision_id: str,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        prior = self._require_revision(prior_revision_id)
        successor = self._require_revision(successor_revision_id)
        if prior.knowledge_id != successor.knowledge_id:
            raise KnowledgeLifecycleError(
                "supersession revisions must share knowledge identity"
            )
        if successor.supersedes_revision_id != prior_revision_id:
            raise KnowledgeLifecycleError(
                "successor revision is not bound to prior revision"
            )
        if (
            self._require_state(successor_revision_id)
            is not KnowledgeLifecycleState.ACCEPTED
        ):
            raise KnowledgeLifecycleError(
                "successor must be accepted before prior supersession"
            )
        if self._require_state(prior_revision_id) is KnowledgeLifecycleState.SUPERSEDED:
            return KnowledgeTransitionResult(
                prior_revision_id,
                KnowledgeLifecycleState.ACCEPTED,
                KnowledgeLifecycleState.SUPERSEDED,
                False,
            )
        if (
            self._require_state(prior_revision_id)
            is not KnowledgeLifecycleState.ACCEPTED
        ):
            raise KnowledgeLifecycleError(
                "prior revision must be accepted before supersession"
            )

        prior_outcome = engineering_learning_outcome(self._store, prior_revision_id)
        successor_outcome = engineering_learning_outcome(
            self._store,
            successor_revision_id,
        )
        if not engineering_learning_outcomes_contradict(
            prior_outcome,
            successor_outcome,
        ):
            raise KnowledgeLifecycleError(
                "successor does not materially contradict prior accepted learning"
            )
        successor_links = self._store.list_engineering_knowledge_evidence_links(
            successor_revision_id
        )
        evidence_ids = tuple(
            dict.fromkeys(item.evidence_id for item in successor_links)
        )
        return self._transition(
            prior_revision_id,
            KnowledgeLifecycleState.ACCEPTED,
            KnowledgeLifecycleState.SUPERSEDED,
            reason_code="verified_successor_contradicts_prior_learning",
            policy_id=ENGINEERING_LEARNING_PROMOTION_POLICY_ID,
            evidence_ids=evidence_ids,
            now_epoch=now_epoch,
            actor=ENGINEERING_LEARNING_SUPERSESSION_ACTOR,
        )

    def _require_revision(self, revision_id: str) -> EngineeringKnowledgeRevision:
        revision = self._store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            raise KnowledgeLifecycleError(f"unknown knowledge revision: {revision_id}")
        return revision

    def _require_state(self, revision_id: str) -> KnowledgeLifecycleState:
        current = self._store.get_engineering_knowledge_lifecycle_state(revision_id)
        if current is None:
            raise KnowledgeLifecycleError(f"unknown knowledge revision: {revision_id}")
        return current

    def _transition(
        self,
        revision_id: str,
        from_state: KnowledgeLifecycleState,
        to_state: KnowledgeLifecycleState,
        *,
        reason_code: str,
        policy_id: str | None,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
        actor: str = ENGINEERING_LEARNING_PROMOTION_ACTOR,
    ) -> KnowledgeTransitionResult:
        event = KnowledgeLifecycleEvent(
            event_id="lifecycle-event:"
            + canonical_sha256(
                {
                    "revision_id": revision_id,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "reason_code": reason_code,
                    "policy_id": policy_id,
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
            revision_id,
            from_state,
            to_state,
            created,
        )


def engineering_learning_outcomes_contradict(
    prior: EngineeringOutcomeV1,
    successor: EngineeringOutcomeV1,
) -> bool:
    if EngineeringLearningProjector.knowledge_id_for(
        prior
    ) != EngineeringLearningProjector.knowledge_id_for(successor):
        return False
    policy = EngineeringLearningEligibilityPolicy()
    prior_decision = policy.evaluate(prior)
    successor_decision = policy.evaluate(successor)
    if not prior_decision.eligible or not successor_decision.eligible:
        return False
    polarity = {
        LearningDisposition.POSITIVE: "positive",
        LearningDisposition.NEGATIVE: "negative",
    }
    if prior_decision.disposition in polarity and successor_decision.disposition in polarity:
        return polarity[prior_decision.disposition] != polarity[
            successor_decision.disposition
        ]
    if (
        prior_decision.disposition is LearningDisposition.COMPATIBILITY
        and successor_decision.disposition is LearningDisposition.COMPATIBILITY
    ):
        return prior.result is not successor.result
    return False


class EngineeringLearningRevisionPlanner:
    """Plan immutable replay/new-revision/supersession semantics."""

    def plan(
        self,
        store: EngineeringLearningLifecycleStore,
        outcome: EngineeringOutcomeV1,
    ) -> EngineeringLearningRevisionPlan:
        decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)
        if not decision.eligible:
            raise EngineeringLearningRevisionPlanningError(
                "cannot plan ineligible learning outcome: "
                + ",".join(decision.reason_codes)
            )
        knowledge_id = EngineeringLearningProjector.knowledge_id_for(outcome)
        revisions = store.list_engineering_knowledge_revisions(knowledge_id)
        if not revisions:
            return EngineeringLearningRevisionPlan(
                knowledge_id=knowledge_id,
                revision_number=1,
                parent_revision_id=None,
                supersedes_revision_id=None,
                replay_revision_id=None,
                reason_code="first_learning_revision",
            )

        accepted: list[tuple[EngineeringKnowledgeRevision, EngineeringOutcomeV1]] = []
        for revision in revisions:
            try:
                persisted = engineering_learning_outcome(store, revision.revision_id)
            except (TypeError, ValueError, KeyError):
                continue
            if persisted.digest == outcome.digest:
                return EngineeringLearningRevisionPlan(
                    knowledge_id=knowledge_id,
                    revision_number=revision.revision_number,
                    parent_revision_id=revision.parent_revision_id,
                    supersedes_revision_id=revision.supersedes_revision_id,
                    replay_revision_id=revision.revision_id,
                    reason_code="exact_outcome_replay",
                )
            state = store.get_engineering_knowledge_lifecycle_state(
                revision.revision_id
            )
            if state in {
                KnowledgeLifecycleState.CANDIDATE,
                KnowledgeLifecycleState.STAGED,
            }:
                raise EngineeringLearningRevisionPlanningError(
                    "another learning revision is still pending"
                )
            if state is KnowledgeLifecycleState.ACCEPTED:
                accepted.append((revision, persisted))

        next_number = max(item.revision_number for item in revisions) + 1
        parent = max(revisions, key=lambda item: item.revision_number)
        if not accepted:
            return EngineeringLearningRevisionPlan(
                knowledge_id=knowledge_id,
                revision_number=next_number,
                parent_revision_id=parent.revision_id,
                supersedes_revision_id=None,
                replay_revision_id=None,
                reason_code="new_learning_after_terminal_history",
            )

        prior_revision, prior_outcome = max(
            accepted,
            key=lambda item: item[0].revision_number,
        )
        if engineering_learning_outcomes_contradict(prior_outcome, outcome):
            return EngineeringLearningRevisionPlan(
                knowledge_id=knowledge_id,
                revision_number=next_number,
                parent_revision_id=prior_revision.revision_id,
                supersedes_revision_id=prior_revision.revision_id,
                replay_revision_id=None,
                reason_code="verified_contradiction_requires_successor",
            )

        prior_decision = EngineeringLearningEligibilityPolicy().evaluate(prior_outcome)
        if (
            prior_decision.disposition is decision.disposition
            and prior_outcome.result is outcome.result
            and prior_outcome.attribution is outcome.attribution
        ):
            return EngineeringLearningRevisionPlan(
                knowledge_id=knowledge_id,
                revision_number=prior_revision.revision_number,
                parent_revision_id=prior_revision.parent_revision_id,
                supersedes_revision_id=prior_revision.supersedes_revision_id,
                replay_revision_id=prior_revision.revision_id,
                reason_code="equivalent_conclusion_already_accepted",
            )

        raise EngineeringLearningRevisionPlanningError(
            "new outcome is neither equivalent nor a deterministic contradiction"
        )
