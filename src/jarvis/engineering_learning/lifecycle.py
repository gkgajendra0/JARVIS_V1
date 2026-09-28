"""Deterministic Phase-10 learning promotion and supersession lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.canonical import (
    JSONValue,
    canonical_sha256,
    canonicalize_json,
    parse_json_object,
)
from jarvis.engineering_knowledge.defaults import build_default_facet_registry
from jarvis.engineering_knowledge.lifecycle import (
    KnowledgeLifecycleError,
    KnowledgePromotionDecision,
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
)

ENGINEERING_LEARNING_PROMOTION_POLICY_ID = "engineering-learning-promotion:v1"
ENGINEERING_LEARNING_PROMOTION_ACTOR = "phase10.engineering-learning-lifecycle:v1"


class EngineeringLearningLifecycleStore(Protocol):
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
class EngineeringLearningPromotionAssessment:
    decision: KnowledgePromotionDecision
    outcome: EngineeringOutcomeV1 | None
    disposition: LearningDisposition | None


def _canonical_text(value: dict[str, JSONValue]) -> str:
    return canonicalize_json(value).decode("utf-8")


def _applicability_from_payload(
    payload: dict[str, JSONValue],
) -> tuple[OutcomeApplicability, ...]:
    raw = payload.get("applicability")
    if not isinstance(raw, list):
        raise ValueError("outcome applicability must be a list")
    result: list[OutcomeApplicability] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("outcome applicability item must be an object")
        constraint = item.get("constraint")
        if not isinstance(constraint, dict):
            raise ValueError("outcome applicability constraint must be an object")
        required = item.get("required")
        if not isinstance(required, bool):
            raise ValueError("outcome applicability required must be a bool")
        result.append(
            OutcomeApplicability(
                target_namespace=str(item["target_namespace"]),
                target_identity=str(item["target_identity"]),
                matcher_type=str(item["matcher_type"]),
                constraint=constraint,
                required=required,
            )
        )
    return tuple(result)


def _lineage(payload: dict[str, JSONValue]) -> dict[str, JSONValue]:
    value = payload.get("lineage")
    if not isinstance(value, dict):
        raise ValueError("outcome lineage must be an object")
    return value


def _optional_str(value: JSONValue) -> str | None:
    return None if value is None else str(value)


def _outcome_from_payload(payload: dict[str, JSONValue]) -> EngineeringOutcomeV1:
    lineage = _lineage(payload)
    return EngineeringOutcomeV1(
        outcome_id=str(payload["outcome_id"]),
        source_kind=EngineeringOutcomeSourceKind(str(payload["source_kind"])),
        source_identity=str(payload["source_identity"]),
        subject_type=str(payload["subject_type"]),
        subject_id=str(payload["subject_id"]),
        subject_digest=str(payload["subject_digest"]),
        result=EngineeringOutcomeResult(str(payload["result"])),
        attribution=EngineeringOutcomeAttribution(str(payload["attribution"])),
        reason_codes=tuple(str(item) for item in payload["reason_codes"]),
        evidence_references=tuple(str(item) for item in payload["evidence_references"]),
        applicability=_applicability_from_payload(payload),
        observed_at_epoch=float(payload["observed_at_epoch"]),
        producer=str(payload["producer"]),
        change_id=_optional_str(lineage.get("change_id")),
        candidate_id=_optional_str(lineage.get("candidate_id")),
        candidate_digest=_optional_str(lineage.get("candidate_digest")),
        release_sha=_optional_str(lineage.get("release_sha")),
        package_id=_optional_str(lineage.get("package_id")),
        package_version=_optional_str(lineage.get("package_version")),
        package_digest=_optional_str(lineage.get("package_digest")),
    )


def _expected_facet_types(
    outcome: EngineeringOutcomeV1,
    disposition: LearningDisposition,
) -> tuple[str, ...]:
    result = [ENGINEERING_OUTCOME_FACET_TYPE]
    if (
        disposition is LearningDisposition.NEGATIVE
        and outcome.attribution is EngineeringOutcomeAttribution.CANDIDATE
        and outcome.result
        in {
            EngineeringOutcomeResult.FAILURE,
            EngineeringOutcomeResult.ROLLED_BACK,
        }
    ):
        result.append(ENGINEERING_REGRESSION_FACET_TYPE)
    if disposition is LearningDisposition.COMPATIBILITY:
        result.append(ENGINEERING_COMPATIBILITY_FACET_TYPE)
    return tuple(sorted(result))


class EngineeringLearningPromotionPolicy:
    """Re-verify persisted Phase-10 candidate knowledge before lifecycle promotion."""

    def evaluate(
        self,
        store: EngineeringLearningLifecycleStore,
        revision_id: str,
    ) -> EngineeringLearningPromotionAssessment:
        revision = store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            raise KnowledgePromotionError(f"unknown knowledge revision: {revision_id}")

        reasons: list[str] = []
        evidence_ids: list[str] = []
        outcome: EngineeringOutcomeV1 | None = None
        disposition: LearningDisposition | None = None

        if revision.kind_namespace != ENGINEERING_LEARNING_KIND_NAMESPACE:
            reasons.append("wrong_kind_namespace")
        if revision.created_by != ENGINEERING_LEARNING_PROJECTOR_ID:
            reasons.append("unexpected_revision_producer")
        if revision.freshness_state is not KnowledgeFreshnessState.CURRENT:
            reasons.append("knowledge_not_current")

        if revision.supersedes_revision_id is not None:
            prior = store.get_engineering_knowledge_revision(
                revision.supersedes_revision_id
            )
            if prior is None:
                reasons.append("superseded_revision_missing")
            else:
                if prior.knowledge_id != revision.knowledge_id:
                    reasons.append("supersession_knowledge_identity_mismatch")
                if revision.parent_revision_id != prior.revision_id:
                    reasons.append("supersession_parent_mismatch")
                if revision.revision_number <= prior.revision_number:
                    reasons.append("supersession_revision_number_not_newer")
                if (
                    revision.valid_from_epoch is None
                    or prior.valid_from_epoch is None
                    or revision.valid_from_epoch <= prior.valid_from_epoch
                ):
                    reasons.append("supersession_evidence_not_newer")

        facets = store.list_engineering_knowledge_facets(revision_id)
        registry = build_default_facet_registry()
        validated_payloads: dict[str, dict[str, JSONValue]] = {}
        for facet in facets:
            assessment = registry.assess_for_decision(facet)
            if not assessment.eligible or assessment.validated is None:
                reasons.append(f"facet_invalid:{assessment.reason_code}")
                continue
            if facet.facet_type in validated_payloads:
                reasons.append("duplicate_learning_facet_type")
                continue
            validated_payloads[facet.facet_type] = assessment.validated.payload

        outcome_payload = validated_payloads.get(ENGINEERING_OUTCOME_FACET_TYPE)
        if outcome_payload is None:
            reasons.append("missing_engineering_outcome_facet")
        else:
            try:
                outcome = _outcome_from_payload(outcome_payload)
                eligibility = EngineeringLearningEligibilityPolicy().evaluate(outcome)
                if not eligibility.eligible:
                    reasons.append("outcome_no_longer_learning_eligible")
                else:
                    disposition = eligibility.disposition
                    if tuple(sorted(validated_payloads)) != _expected_facet_types(
                        outcome,
                        disposition,
                    ):
                        reasons.append("unexpected_learning_facet_set")
            except (KeyError, TypeError, ValueError) as exc:
                reasons.append(f"outcome_reconstruction_failed:{type(exc).__name__}")

        applicability = store.list_engineering_knowledge_applicability(revision_id)
        if not applicability:
            reasons.append("missing_applicability")
        elif not any(item.required for item in applicability):
            reasons.append("missing_required_applicability")

        evidence = store.list_engineering_knowledge_evidence(revision_id)
        if not evidence:
            reasons.append("missing_evidence")
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            reasons.append("duplicate_evidence_identity")
        for item in evidence:
            if item.source_class != "authoritative_engineering_record":
                reasons.append("unexpected_evidence_source")
            if item.producer != ENGINEERING_LEARNING_PROJECTOR_ID:
                reasons.append("unexpected_evidence_producer")

        links = store.list_engineering_knowledge_evidence_links(revision_id)
        linked_ids: list[str] = []
        for link in links:
            if link.relation_type != "supports_engineering_outcome":
                reasons.append("unexpected_evidence_relation")
            if link.evidence_id not in evidence_by_id:
                reasons.append("evidence_link_missing_record")
            if link.evidence_id not in linked_ids:
                linked_ids.append(link.evidence_id)
        if set(linked_ids) != set(evidence_by_id):
            reasons.append("incomplete_evidence_links")
        evidence_ids.extend(linked_ids)

        if outcome is not None:
            persisted_refs = sorted(item.canonical_reference for item in evidence)
            if persisted_refs != sorted(outcome.evidence_references):
                reasons.append("outcome_evidence_reference_mismatch")

            persisted_applicability = sorted(
                (
                    item.target_namespace,
                    item.target_identity,
                    item.matcher_type,
                    item.constraint_json,
                    item.required,
                )
                for item in applicability
            )
            outcome_applicability = sorted(
                (
                    item.target_namespace,
                    item.target_identity,
                    item.matcher_type,
                    _canonical_text(item.constraint),
                    item.required,
                )
                for item in outcome.applicability
            )
            if persisted_applicability != outcome_applicability:
                reasons.append("outcome_applicability_mismatch")

        attestations = store.list_engineering_attestations(
            subject_type="knowledge_revision",
            subject_id=revision_id,
        )
        passing = tuple(
            item
            for item in attestations
            if item.predicate_type == ENGINEERING_LEARNING_ATTESTATION_PREDICATE
            and item.subject_digest == revision.canonical_digest
            and item.verdict is AttestationVerdict.PASS
        )
        if len(passing) != 1:
            reasons.append("missing_unique_passing_learning_attestation")
            attestation = None
        else:
            attestation = passing[0]
            if set(attestation.evidence_ids) != set(evidence_by_id):
                reasons.append("attestation_evidence_mismatch")
            for evidence_id in attestation.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)

        outcome_digest: str | None = None
        attested_outcome_id: str | None = None
        if attestation is not None:
            try:
                expected = parse_json_object(attestation.expected_contract_json)
                observed = parse_json_object(attestation.observed_result_json)
                if set(expected) != {
                    "policy_id",
                    "eligible",
                    "disposition",
                    "outcome_id",
                    "outcome_digest",
                }:
                    reasons.append("attestation_expected_contract_shape_mismatch")
                if expected.get("policy_id") != ENGINEERING_LEARNING_POLICY_ID:
                    reasons.append("attestation_policy_mismatch")
                if expected.get("eligible") is not True:
                    reasons.append("attestation_not_eligible")
                if (
                    disposition is not None
                    and expected.get("disposition") != disposition.value
                ):
                    reasons.append("attestation_disposition_mismatch")
                attested_outcome_id = str(expected.get("outcome_id") or "")
                outcome_digest = str(expected.get("outcome_digest") or "")
                if observed.get("outcome_id") != attested_outcome_id:
                    reasons.append("attestation_outcome_id_mismatch")
                if observed.get("outcome_digest") != outcome_digest:
                    reasons.append("attestation_outcome_digest_mismatch")
                if outcome is not None:
                    if attested_outcome_id != outcome.outcome_id:
                        reasons.append("facet_attestation_outcome_id_mismatch")
                    if outcome_digest != outcome.digest:
                        reasons.append("facet_attestation_outcome_digest_mismatch")
                    if observed.get("result") != outcome.result.value:
                        reasons.append("attestation_result_mismatch")
                    if observed.get("attribution") != outcome.attribution.value:
                        reasons.append("attestation_attribution_mismatch")
            except (TypeError, ValueError) as exc:
                reasons.append(f"attestation_parse_failed:{type(exc).__name__}")

        if outcome is not None and outcome_digest is not None:
            reconstructed_digest = canonical_sha256(
                {
                    "projector": ENGINEERING_LEARNING_PROJECTOR_ID,
                    "policy_id": ENGINEERING_LEARNING_POLICY_ID,
                    "knowledge_id": revision.knowledge_id,
                    "revision_number": revision.revision_number,
                    "parent_revision_id": revision.parent_revision_id,
                    "supersedes_revision_id": revision.supersedes_revision_id,
                    "kind_namespace": revision.kind_namespace,
                    "normalized_summary": revision.normalized_summary,
                    "outcome_id": outcome.outcome_id,
                    "outcome_digest": outcome_digest,
                    "facets": sorted(
                        (
                            {
                                "facet_type": facet.facet_type,
                                "schema_id": facet.schema_id,
                                "schema_version": facet.schema_version,
                                "payload_digest": facet.payload_digest,
                            }
                            for facet in facets
                        ),
                        key=lambda item: (
                            str(item["facet_type"]),
                            str(item["schema_id"]),
                            str(item["schema_version"]),
                            str(item["payload_digest"]),
                        ),
                    ),
                    "applicability": sorted(
                        (
                            {
                                "target_namespace": item.target_namespace,
                                "target_identity": item.target_identity,
                                "matcher_type": item.matcher_type,
                                "constraint_json": item.constraint_json,
                                "required": item.required,
                            }
                            for item in applicability
                        ),
                        key=lambda item: (
                            str(item["target_namespace"]),
                            str(item["target_identity"]),
                            str(item["matcher_type"]),
                            str(item["constraint_json"]),
                            bool(item["required"]),
                        ),
                    ),
                    "evidence_ids": sorted(evidence_by_id),
                }
            )
            if reconstructed_digest != revision.canonical_digest:
                reasons.append("revision_digest_mismatch")
        else:
            reasons.append("revision_digest_not_reconstructable")

        return EngineeringLearningPromotionAssessment(
            decision=KnowledgePromotionDecision(
                eligible=not reasons,
                reason_codes=tuple(dict.fromkeys(reasons)),
                evidence_ids=tuple(evidence_ids),
            ),
            outcome=outcome,
            disposition=disposition,
        )


class EngineeringLearningLifecycleService:
    """Stage, accept, and supersede verified Phase-10 EngineeringKnowledge."""

    def __init__(
        self,
        store: EngineeringLearningLifecycleStore,
        *,
        promotion_policy: EngineeringLearningPromotionPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = promotion_policy or EngineeringLearningPromotionPolicy()

    def stage(
        self,
        revision_id: str,
        *,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        current = self._require_state(revision_id)
        if current is KnowledgeLifecycleState.STAGED:
            return KnowledgeTransitionResult(
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.CANDIDATE,
                to_state=KnowledgeLifecycleState.STAGED,
                created=False,
            )
        if current is not KnowledgeLifecycleState.CANDIDATE:
            raise KnowledgeLifecycleError(
                f"cannot stage engineering learning from {current.value}"
            )
        assessment = self._policy.evaluate(self._store, revision_id)
        if not assessment.decision.eligible:
            raise KnowledgePromotionError(
                "engineering learning candidate cannot be staged: "
                + ",".join(assessment.decision.reason_codes)
            )
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.CANDIDATE,
            to_state=KnowledgeLifecycleState.STAGED,
            reason_code="engineering_learning_structurally_verified",
            evidence_ids=assessment.decision.evidence_ids,
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
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.STAGED,
                to_state=KnowledgeLifecycleState.ACCEPTED,
                created=False,
            )
        if current is not KnowledgeLifecycleState.STAGED:
            raise KnowledgeLifecycleError(
                f"cannot accept engineering learning from {current.value}"
            )
        assessment = self._policy.evaluate(self._store, revision_id)
        if not assessment.decision.eligible:
            raise KnowledgePromotionError(
                "staged engineering learning cannot be accepted: "
                + ",".join(assessment.decision.reason_codes)
            )
        return self._transition(
            revision_id=revision_id,
            from_state=KnowledgeLifecycleState.STAGED,
            to_state=KnowledgeLifecycleState.ACCEPTED,
            reason_code="verified_engineering_learning_policy_satisfied",
            evidence_ids=assessment.decision.evidence_ids,
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
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.STAGED,
                to_state=KnowledgeLifecycleState.ACCEPTED,
                created=False,
            )
            return no_op, no_op
        if current is KnowledgeLifecycleState.CANDIDATE:
            staged = self.stage(revision_id, now_epoch=staged_at_epoch)
        elif current is KnowledgeLifecycleState.STAGED:
            staged = KnowledgeTransitionResult(
                revision_id=revision_id,
                from_state=KnowledgeLifecycleState.CANDIDATE,
                to_state=KnowledgeLifecycleState.STAGED,
                created=False,
            )
        else:
            raise KnowledgeLifecycleError(
                f"cannot promote engineering learning from {current.value}"
            )
        accepted = self.accept(revision_id, now_epoch=accepted_at_epoch)
        return staged, accepted

    def supersede_prior(
        self,
        successor_revision_id: str,
        *,
        prior_revision_id: str,
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        successor = self._require_revision(successor_revision_id)
        prior = self._require_revision(prior_revision_id)
        successor_state = self._require_state(successor_revision_id)
        prior_state = self._require_state(prior_revision_id)

        if successor_state is not KnowledgeLifecycleState.ACCEPTED:
            raise KnowledgeLifecycleError(
                "successor must be ACCEPTED before prior revision can be superseded"
            )
        if prior_state is KnowledgeLifecycleState.SUPERSEDED:
            return KnowledgeTransitionResult(
                revision_id=prior_revision_id,
                from_state=KnowledgeLifecycleState.ACCEPTED,
                to_state=KnowledgeLifecycleState.SUPERSEDED,
                created=False,
            )
        if prior_state is not KnowledgeLifecycleState.ACCEPTED:
            raise KnowledgeLifecycleError(
                f"cannot supersede prior knowledge from {prior_state.value}"
            )
        if successor.knowledge_id != prior.knowledge_id:
            raise KnowledgeLifecycleError(
                "successor and prior must share stable knowledge identity"
            )
        if successor.supersedes_revision_id != prior_revision_id:
            raise KnowledgeLifecycleError(
                "successor does not declare the prior revision as superseded"
            )
        if successor.parent_revision_id != prior_revision_id:
            raise KnowledgeLifecycleError(
                "successor must directly descend from the prior revision"
            )
        if successor.revision_number <= prior.revision_number:
            raise KnowledgeLifecycleError(
                "successor revision number must advance the prior revision"
            )
        if (
            successor.valid_from_epoch is None
            or prior.valid_from_epoch is None
            or successor.valid_from_epoch <= prior.valid_from_epoch
        ):
            raise KnowledgeLifecycleError(
                "successor evidence must be newer than the prior revision"
            )

        assessment = self._policy.evaluate(self._store, successor_revision_id)
        if not assessment.decision.eligible:
            raise KnowledgePromotionError(
                "accepted successor no longer satisfies learning promotion policy: "
                + ",".join(assessment.decision.reason_codes)
            )
        return self._transition(
            revision_id=prior_revision_id,
            from_state=KnowledgeLifecycleState.ACCEPTED,
            to_state=KnowledgeLifecycleState.SUPERSEDED,
            reason_code="verified_successor_revision_accepted",
            evidence_ids=assessment.decision.evidence_ids,
            now_epoch=now_epoch,
        )

    def promote_successor_and_supersede(
        self,
        successor_revision_id: str,
        *,
        prior_revision_id: str,
        staged_at_epoch: float,
        accepted_at_epoch: float,
        superseded_at_epoch: float,
    ) -> tuple[
        KnowledgeTransitionResult,
        KnowledgeTransitionResult,
        KnowledgeTransitionResult,
    ]:
        staged, accepted = self.promote(
            successor_revision_id,
            staged_at_epoch=staged_at_epoch,
            accepted_at_epoch=accepted_at_epoch,
        )
        superseded = self.supersede_prior(
            successor_revision_id,
            prior_revision_id=prior_revision_id,
            now_epoch=superseded_at_epoch,
        )
        return staged, accepted, superseded

    def _require_state(self, revision_id: str) -> KnowledgeLifecycleState:
        state = self._store.get_engineering_knowledge_lifecycle_state(revision_id)
        if state is None:
            raise KnowledgeLifecycleError(f"unknown knowledge revision: {revision_id}")
        return state

    def _require_revision(self, revision_id: str) -> EngineeringKnowledgeRevision:
        revision = self._store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            raise KnowledgeLifecycleError(f"unknown knowledge revision: {revision_id}")
        return revision

    def _transition(
        self,
        *,
        revision_id: str,
        from_state: KnowledgeLifecycleState,
        to_state: KnowledgeLifecycleState,
        reason_code: str,
        evidence_ids: tuple[str, ...],
        now_epoch: float,
    ) -> KnowledgeTransitionResult:
        event = KnowledgeLifecycleEvent(
            event_id="lifecycle-event:"
            + canonical_sha256(
                {
                    "revision_id": revision_id,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "reason_code": reason_code,
                    "policy_id": ENGINEERING_LEARNING_PROMOTION_POLICY_ID,
                }
            ),
            revision_id=revision_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            actor=ENGINEERING_LEARNING_PROMOTION_ACTOR,
            policy_id=ENGINEERING_LEARNING_PROMOTION_POLICY_ID,
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
