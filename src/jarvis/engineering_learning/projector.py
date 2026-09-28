"""Deterministic projection from eligible Phase-10 outcomes to EngineeringKnowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.canonical import (
    JSONValue,
    canonical_sha256,
    canonicalize_json,
)
from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeIdentity,
    EngineeringKnowledgeRevision,
    KnowledgeEvidenceLink,
    KnowledgeFreshnessState,
    KnowledgeLifecycleEvent,
    KnowledgeLifecycleState,
    KnowledgeSensitivity,
)
from jarvis.engineering_knowledge.persistence import (
    EngineeringKnowledgeCandidateBundle,
    EngineeringKnowledgeCandidateWriteResult,
)
from jarvis.engineering_learning.facets import (
    EngineeringCompatibilityV1Handler,
    EngineeringOutcomeV1Handler,
    EngineeringRegressionV1Handler,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.policy import (
    EngineeringLearningEligibilityPolicy,
    LearningDisposition,
    LearningEligibilityDecision,
)

ENGINEERING_LEARNING_KIND_NAMESPACE = "engineering.learning"
ENGINEERING_LEARNING_PROJECTOR_ID = "phase10.engineering-learning-projector:v1"
ENGINEERING_LEARNING_ATTESTATION_PREDICATE = (
    "urn:jarvis:engineering-learning:eligibility:v1"
)
_MAX_LINKED_EVIDENCE = 32
_SHA256_REF = re.compile(r"(?:^|:)sha256:([0-9a-f]{64})(?:$|:)")


class EngineeringLearningProjectionError(ValueError):
    """An eligible outcome cannot be projected into immutable knowledge."""


class EngineeringLearningProjectionStore(Protocol):
    def persist_engineering_knowledge_candidate(
        self,
        candidate: EngineeringKnowledgeCandidateBundle,
    ) -> EngineeringKnowledgeCandidateWriteResult: ...


@dataclass(frozen=True, slots=True)
class EngineeringLearningProjectionResult:
    knowledge_id: str
    revision_id: str
    outcome_id: str
    disposition: LearningDisposition
    created: bool


def _canonical_text(payload: dict[str, JSONValue]) -> str:
    return canonicalize_json(payload).decode("utf-8")


def _stable_id(prefix: str, payload: dict[str, JSONValue]) -> str:
    return f"{prefix}:{canonical_sha256(payload)}"


def _applicability_payload(item: OutcomeApplicability) -> dict[str, JSONValue]:
    return {
        "target_namespace": item.target_namespace,
        "target_identity": item.target_identity,
        "matcher_type": item.matcher_type,
        "constraint": item.constraint,
        "required": item.required,
    }


def _required_applicability_key(
    applicability: tuple[OutcomeApplicability, ...],
) -> list[JSONValue]:
    required = [
        _applicability_payload(item)
        for item in applicability
        if item.required
    ]
    return sorted(
        required,
        key=lambda item: (
            str(item["target_namespace"]),
            str(item["target_identity"]),
            str(item["matcher_type"]),
            canonical_sha256(item["constraint"]),
        ),
    )


def _reference_digest(reference: str) -> str | None:
    normalized = reference.casefold()
    match = _SHA256_REF.search(normalized)
    if match is not None:
        return match.group(1)
    if "sha256:" in normalized:
        raise EngineeringLearningProjectionError(
            "evidence reference contains malformed sha256 integrity syntax"
        )
    return None


class EngineeringLearningProjector:
    """Build immutable candidate knowledge from one deterministic eligibility decision."""

    def __init__(
        self,
        *,
        policy: EngineeringLearningEligibilityPolicy | None = None,
    ) -> None:
        self._policy = policy or EngineeringLearningEligibilityPolicy()

    def project(
        self,
        store: EngineeringLearningProjectionStore,
        outcome: EngineeringOutcomeV1,
        *,
        revision_number: int = 1,
        parent_revision_id: str | None = None,
        supersedes_revision_id: str | None = None,
    ) -> EngineeringLearningProjectionResult:
        candidate, decision = self.build_candidate(
            outcome,
            revision_number=revision_number,
            parent_revision_id=parent_revision_id,
            supersedes_revision_id=supersedes_revision_id,
        )
        write = store.persist_engineering_knowledge_candidate(candidate)
        return EngineeringLearningProjectionResult(
            knowledge_id=write.knowledge_id,
            revision_id=write.revision_id,
            outcome_id=outcome.outcome_id,
            disposition=decision.disposition,
            created=write.created,
        )

    def build_candidate(
        self,
        outcome: EngineeringOutcomeV1,
        *,
        revision_number: int = 1,
        parent_revision_id: str | None = None,
        supersedes_revision_id: str | None = None,
    ) -> tuple[EngineeringKnowledgeCandidateBundle, LearningEligibilityDecision]:
        if not isinstance(outcome, EngineeringOutcomeV1):
            raise TypeError("outcome must be an EngineeringOutcomeV1")
        if isinstance(revision_number, bool) or not isinstance(revision_number, int):
            raise TypeError("revision_number must be an integer")
        if revision_number <= 0:
            raise ValueError("revision_number must be positive")

        decision = self._policy.evaluate(outcome)
        if not decision.eligible:
            raise EngineeringLearningProjectionError(
                "outcome is not eligible for durable engineering learning: "
                + ",".join(decision.reason_codes)
            )
        if len(outcome.evidence_references) > _MAX_LINKED_EVIDENCE:
            raise EngineeringLearningProjectionError(
                "eligible outcome exceeds EngineeringKnowledge evidence-link limit"
            )

        knowledge_id = self.knowledge_id_for(outcome)
        revision_id = _stable_id(
            "revision",
            {
                "projector": ENGINEERING_LEARNING_PROJECTOR_ID,
                "knowledge_id": knowledge_id,
                "revision_number": revision_number,
                "outcome_id": outcome.outcome_id,
                "outcome_digest": outcome.digest,
            },
        )
        created_at = outcome.observed_at_epoch

        evidence = self._evidence(outcome)
        evidence_ids = tuple(item.evidence_id for item in evidence)
        facets = self._facets(
            outcome,
            decision,
            revision_id=revision_id,
            created_at=created_at,
        )
        applicability = self._applicability(
            outcome,
            revision_id=revision_id,
            created_at=created_at,
        )
        summary = self._summary(outcome, decision)
        revision_digest = canonical_sha256(
            {
                "projector": ENGINEERING_LEARNING_PROJECTOR_ID,
                "policy_id": decision.policy_id,
                "knowledge_id": knowledge_id,
                "revision_number": revision_number,
                "parent_revision_id": parent_revision_id,
                "supersedes_revision_id": supersedes_revision_id,
                "kind_namespace": ENGINEERING_LEARNING_KIND_NAMESPACE,
                "normalized_summary": summary,
                "outcome_id": outcome.outcome_id,
                "outcome_digest": outcome.digest,
                "facet_digests": [facet.payload_digest for facet in facets],
                "applicability": [
                    {
                        "target_namespace": item.target_namespace,
                        "target_identity": item.target_identity,
                        "matcher_type": item.matcher_type,
                        "constraint_json": item.constraint_json,
                        "required": item.required,
                    }
                    for item in applicability
                ],
                "evidence_ids": list(evidence_ids),
            }
        )

        identity = EngineeringKnowledgeIdentity(
            knowledge_id=knowledge_id,
            stable_label=self._stable_label(outcome),
            created_at_epoch=created_at,
            created_by=ENGINEERING_LEARNING_PROJECTOR_ID,
        )
        revision = EngineeringKnowledgeRevision(
            revision_id=revision_id,
            knowledge_id=knowledge_id,
            revision_number=revision_number,
            parent_revision_id=parent_revision_id,
            supersedes_revision_id=supersedes_revision_id,
            kind_namespace=ENGINEERING_LEARNING_KIND_NAMESPACE,
            normalized_summary=summary,
            valid_from_epoch=outcome.observed_at_epoch,
            valid_to_epoch=None,
            system_from_epoch=created_at,
            system_to_epoch=None,
            sensitivity=KnowledgeSensitivity.STANDARD,
            freshness_state=KnowledgeFreshnessState.CURRENT,
            canonical_digest=revision_digest,
            created_at_epoch=created_at,
            created_by=ENGINEERING_LEARNING_PROJECTOR_ID,
        )
        links = tuple(
            KnowledgeEvidenceLink(
                revision_id=revision_id,
                evidence_id=item.evidence_id,
                relation_type="supports_engineering_outcome",
                created_at_epoch=created_at,
            )
            for item in evidence
        )
        lifecycle = KnowledgeLifecycleEvent(
            event_id=_stable_id(
                "lifecycle-event",
                {
                    "revision_id": revision_id,
                    "to_state": KnowledgeLifecycleState.CANDIDATE.value,
                    "policy_id": decision.policy_id,
                },
            ),
            revision_id=revision_id,
            from_state=None,
            to_state=KnowledgeLifecycleState.CANDIDATE,
            reason_code="engineering_learning_candidate_projected",
            actor=ENGINEERING_LEARNING_PROJECTOR_ID,
            policy_id=decision.policy_id,
            evidence_ids=evidence_ids,
            occurred_at_epoch=created_at,
        )
        attestation = EngineeringAttestation(
            attestation_id=_stable_id(
                "attestation",
                {
                    "outcome_id": outcome.outcome_id,
                    "outcome_digest": outcome.digest,
                    "policy_id": decision.policy_id,
                    "disposition": decision.disposition.value,
                },
            ),
            subject_type="knowledge_revision",
            subject_id=revision_id,
            subject_digest=revision_digest,
            predicate_type=ENGINEERING_LEARNING_ATTESTATION_PREDICATE,
            producer=ENGINEERING_LEARNING_PROJECTOR_ID,
            expected_contract_json=_canonical_text(
                {
                    "policy_id": decision.policy_id,
                    "eligible": True,
                    "disposition": decision.disposition.value,
                    "outcome_id": outcome.outcome_id,
                    "outcome_digest": outcome.digest,
                }
            ),
            observed_result_json=_canonical_text(
                {
                    "outcome_id": outcome.outcome_id,
                    "outcome_digest": outcome.digest,
                    "result": outcome.result.value,
                    "attribution": outcome.attribution.value,
                    "reason_codes": list(outcome.reason_codes),
                    "decision_reason_codes": list(decision.reason_codes),
                }
            ),
            verdict=AttestationVerdict.PASS,
            evidence_ids=evidence_ids,
            observed_at_epoch=outcome.observed_at_epoch,
            created_at_epoch=created_at,
        )

        bundle = EngineeringKnowledgeCandidateBundle(
            identity=identity,
            revision=revision,
            facets=facets,
            applicability=applicability,
            evidence=evidence,
            evidence_links=links,
            lifecycle_event=lifecycle,
            attestations=(attestation,),
        )
        return bundle, decision

    @staticmethod
    def knowledge_id_for(outcome: EngineeringOutcomeV1) -> str:
        if not isinstance(outcome, EngineeringOutcomeV1):
            raise TypeError("outcome must be an EngineeringOutcomeV1")
        return _stable_id(
            "knowledge",
            {
                "kind_namespace": ENGINEERING_LEARNING_KIND_NAMESPACE,
                "source_kind": outcome.source_kind.value,
                "subject_type": outcome.subject_type,
                "subject_id": outcome.subject_id,
                "subject_digest": outcome.subject_digest,
                "required_applicability": _required_applicability_key(
                    outcome.applicability
                ),
            },
        )

    @staticmethod
    def _stable_label(outcome: EngineeringOutcomeV1) -> str:
        return (
            f"engineering-learning:{outcome.source_kind.value}:"
            f"{outcome.subject_type}:{outcome.subject_id}"
        )

    @staticmethod
    def _summary(
        outcome: EngineeringOutcomeV1,
        decision: LearningEligibilityDecision,
    ) -> str:
        reasons = ",".join(outcome.reason_codes[:4])
        return (
            f"{outcome.source_kind.value} {outcome.subject_type} "
            f"{outcome.subject_id} -> {decision.disposition.value}/"
            f"{outcome.result.value}; {reasons}"
        )

    @staticmethod
    def _evidence(
        outcome: EngineeringOutcomeV1,
    ) -> tuple[EngineeringEvidence, ...]:
        evidence: list[EngineeringEvidence] = []
        for ordinal, reference in enumerate(outcome.evidence_references, start=1):
            digest = _reference_digest(reference)
            evidence.append(
                EngineeringEvidence(
                    evidence_id=_stable_id(
                        "evidence",
                        {
                            "outcome_id": outcome.outcome_id,
                            "ordinal": ordinal,
                            "reference": reference,
                        },
                    ),
                    evidence_type="engineering_outcome_source",
                    source_class="authoritative_engineering_record",
                    canonical_reference=reference,
                    summary=(
                        f"Canonical engineering evidence for {outcome.outcome_id} "
                        f"({ordinal}/{len(outcome.evidence_references)})"
                    ),
                    occurred_at_epoch=outcome.observed_at_epoch,
                    observed_at_epoch=outcome.observed_at_epoch,
                    sensitivity=KnowledgeSensitivity.STANDARD,
                    producer=ENGINEERING_LEARNING_PROJECTOR_ID,
                    integrity_algorithm="sha256" if digest is not None else None,
                    integrity_digest=digest,
                    created_at_epoch=outcome.observed_at_epoch,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _common_facet_payload(
        outcome: EngineeringOutcomeV1,
    ) -> dict[str, JSONValue]:
        return {
            "outcome_id": outcome.outcome_id,
            "source_kind": outcome.source_kind.value,
            "source_identity": outcome.source_identity,
            "subject_type": outcome.subject_type,
            "subject_id": outcome.subject_id,
            "subject_digest": outcome.subject_digest,
            "reason_codes": list(outcome.reason_codes),
            "evidence_references": list(outcome.evidence_references),
            "applicability": [
                _applicability_payload(item) for item in outcome.applicability
            ],
            "revalidation": {
                "strategy": "source_outcome",
                "source_kind": outcome.source_kind.value,
                "source_identity": outcome.source_identity,
            },
        }

    def _facets(
        self,
        outcome: EngineeringOutcomeV1,
        decision: LearningEligibilityDecision,
        *,
        revision_id: str,
        created_at: float,
    ) -> tuple[EngineeringKnowledgeFacet, ...]:
        common = self._common_facet_payload(outcome)
        result: list[EngineeringKnowledgeFacet] = []

        outcome_handler = EngineeringOutcomeV1Handler()
        outcome_payload: dict[str, JSONValue] = {
            **common,
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
        outcome_handler.validate_payload(outcome_payload)
        result.append(
            self._facet(
                handler=outcome_handler,
                payload=outcome_payload,
                revision_id=revision_id,
                created_at=created_at,
            )
        )

        if (
            decision.disposition is LearningDisposition.NEGATIVE
            and outcome.attribution is EngineeringOutcomeAttribution.CANDIDATE
            and outcome.result
            in {
                EngineeringOutcomeResult.FAILURE,
                EngineeringOutcomeResult.ROLLED_BACK,
            }
        ):
            regression_handler = EngineeringRegressionV1Handler()
            regression_payload: dict[str, JSONValue] = {
                **common,
                "result": outcome.result.value,
                "attribution": outcome.attribution.value,
            }
            regression_handler.validate_payload(regression_payload)
            result.append(
                self._facet(
                    handler=regression_handler,
                    payload=regression_payload,
                    revision_id=revision_id,
                    created_at=created_at,
                )
            )

        if decision.disposition is LearningDisposition.COMPATIBILITY:
            compatibility_handler = EngineeringCompatibilityV1Handler()
            compatibility_payload: dict[str, JSONValue] = {
                **common,
                "verdict": (
                    "ready"
                    if outcome.result is EngineeringOutcomeResult.SUCCESS
                    else "blocked"
                ),
            }
            compatibility_handler.validate_payload(compatibility_payload)
            result.append(
                self._facet(
                    handler=compatibility_handler,
                    payload=compatibility_payload,
                    revision_id=revision_id,
                    created_at=created_at,
                )
            )

        return tuple(result)

    @staticmethod
    def _facet(
        *,
        handler: (
            EngineeringOutcomeV1Handler
            | EngineeringRegressionV1Handler
            | EngineeringCompatibilityV1Handler
        ),
        payload: dict[str, JSONValue],
        revision_id: str,
        created_at: float,
    ) -> EngineeringKnowledgeFacet:
        payload_digest = canonical_sha256(payload)
        key = handler.key
        return EngineeringKnowledgeFacet(
            facet_id=_stable_id(
                "facet",
                {
                    "revision_id": revision_id,
                    "facet_type": key.facet_type,
                    "schema_id": key.schema_id,
                    "schema_version": key.schema_version,
                    "payload_digest": payload_digest,
                },
            ),
            revision_id=revision_id,
            facet_type=key.facet_type,
            schema_id=key.schema_id,
            schema_version=key.schema_version,
            schema_digest=handler.schema_digest,
            producer=ENGINEERING_LEARNING_PROJECTOR_ID,
            payload_json=_canonical_text(payload),
            payload_digest=payload_digest,
            created_at_epoch=created_at,
        )

    @staticmethod
    def _applicability(
        outcome: EngineeringOutcomeV1,
        *,
        revision_id: str,
        created_at: float,
    ) -> tuple[EngineeringApplicability, ...]:
        rows: list[EngineeringApplicability] = []
        for ordinal, item in enumerate(outcome.applicability, start=1):
            constraint_json = _canonical_text(item.constraint)
            rows.append(
                EngineeringApplicability(
                    applicability_id=_stable_id(
                        "applicability",
                        {
                            "revision_id": revision_id,
                            "ordinal": ordinal,
                            "target_namespace": item.target_namespace,
                            "target_identity": item.target_identity,
                            "matcher_type": item.matcher_type,
                            "constraint": item.constraint,
                            "required": item.required,
                        },
                    ),
                    revision_id=revision_id,
                    target_namespace=item.target_namespace,
                    target_identity=item.target_identity,
                    matcher_type=item.matcher_type,
                    constraint_json=constraint_json,
                    required=item.required,
                    created_at_epoch=created_at,
                )
            )
        return tuple(rows)
