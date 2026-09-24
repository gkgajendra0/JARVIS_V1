"""Persistence contracts for atomic EngineeringKnowledge candidates."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_knowledge.models import (
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeIdentity,
    EngineeringKnowledgeRevision,
    KnowledgeEvidenceLink,
    KnowledgeLifecycleEvent,
    KnowledgeLifecycleState,
)


class EngineeringKnowledgePersistenceConflictError(RuntimeError):
    """A deterministic candidate identity already exists with different content."""


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeCandidateBundle:
    """One complete immutable CANDIDATE persisted atomically."""

    identity: EngineeringKnowledgeIdentity
    revision: EngineeringKnowledgeRevision
    facets: tuple[EngineeringKnowledgeFacet, ...]
    applicability: tuple[EngineeringApplicability, ...]
    evidence: tuple[EngineeringEvidence, ...]
    evidence_links: tuple[KnowledgeEvidenceLink, ...]
    lifecycle_event: KnowledgeLifecycleEvent
    attestations: tuple[EngineeringAttestation, ...] = ()

    def __post_init__(self) -> None:
        revision_id = self.revision.revision_id
        if self.revision.knowledge_id != self.identity.knowledge_id:
            raise ValueError("revision knowledge_id must match candidate identity")
        if self.lifecycle_event.revision_id != revision_id:
            raise ValueError("lifecycle event must target candidate revision")
        if self.lifecycle_event.from_state is not None:
            raise ValueError("candidate creation lifecycle event must start from None")
        if self.lifecycle_event.to_state is not KnowledgeLifecycleState.CANDIDATE:
            raise ValueError("candidate creation lifecycle event must target CANDIDATE")

        facet_ids: set[str] = set()
        for facet in self.facets:
            if facet.revision_id != revision_id:
                raise ValueError("facet must target candidate revision")
            if facet.facet_id in facet_ids:
                raise ValueError("candidate facets must have unique facet_id values")
            facet_ids.add(facet.facet_id)

        applicability_ids: set[str] = set()
        for item in self.applicability:
            if item.revision_id != revision_id:
                raise ValueError("applicability must target candidate revision")
            if item.applicability_id in applicability_ids:
                raise ValueError(
                    "candidate applicability must have unique applicability_id values"
                )
            applicability_ids.add(item.applicability_id)

        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("candidate evidence must have unique evidence_id values")
        for link in self.evidence_links:
            if link.revision_id != revision_id:
                raise ValueError("evidence link must target candidate revision")
            if link.evidence_id not in evidence_ids:
                raise ValueError("evidence link references unknown candidate evidence")

        lifecycle_evidence = set(self.lifecycle_event.evidence_ids)
        if not lifecycle_evidence.issubset(evidence_ids):
            raise ValueError("lifecycle event references unknown candidate evidence")

        attestation_ids: set[str] = set()
        for attestation in self.attestations:
            if attestation.attestation_id in attestation_ids:
                raise ValueError(
                    "candidate attestations must have unique attestation_id values"
                )
            attestation_ids.add(attestation.attestation_id)
            if attestation.subject_type == "knowledge_revision":
                if attestation.subject_id != revision_id:
                    raise ValueError(
                        "knowledge revision attestation targets another revision"
                    )
                if attestation.subject_digest != self.revision.canonical_digest:
                    raise ValueError(
                        "knowledge revision attestation digest must match revision"
                    )
            if not set(attestation.evidence_ids).issubset(evidence_ids):
                raise ValueError("attestation references unknown candidate evidence")


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeCandidateWriteResult:
    knowledge_id: str
    revision_id: str
    created: bool
