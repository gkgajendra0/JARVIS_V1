"""Security and integrity gates for durable EngineeringKnowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.engineering_knowledge.canonical import canonical_sha256
from jarvis.engineering_knowledge.defaults import build_default_facet_registry
from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRevision,
    KnowledgeSensitivity,
)
from jarvis.engineering_knowledge.projector import (
    PROJECTOR_ID,
    REPAIR_KIND_NAMESPACE,
    REPAIR_VERIFICATION_PREDICATE,
)
from jarvis.engineering_knowledge.repair_facets import REPAIR_FINDING_FACET_TYPE


class EngineeringKnowledgeSecurityError(RuntimeError):
    """A security or integrity gate rejected durable engineering knowledge."""


class EvidenceTrustClass(StrEnum):
    OWNER = "owner"
    AUTHORITATIVE_RUNTIME = "authoritative_runtime"
    VERIFIED_REPOSITORY = "verified_repository"
    VENDOR_DOCUMENTATION = "vendor_documentation"
    MODEL_GENERATED = "model_generated"
    EXTERNAL_UNTRUSTED = "external_untrusted"


class EvidenceAdmissionOutcome(StrEnum):
    ADMIT_CANDIDATE_EVIDENCE = "admit_candidate_evidence"
    QUARANTINE = "quarantine"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class EvidenceAdmissionRequest:
    source_class: str
    content: str
    sensitivity: KnowledgeSensitivity = KnowledgeSensitivity.STANDARD

    def __post_init__(self) -> None:
        source = str(self.source_class).strip().casefold()
        content = str(self.content)
        if not source:
            raise ValueError("source_class must not be empty")
        if not content.strip():
            raise ValueError("content must not be empty")
        if not isinstance(self.sensitivity, KnowledgeSensitivity):
            raise TypeError("sensitivity must be a KnowledgeSensitivity")
        object.__setattr__(self, "source_class", source)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class EvidenceAdmissionDecision:
    outcome: EvidenceAdmissionOutcome
    trust_class: EvidenceTrustClass
    reason_codes: tuple[str, ...]
    secret_indicators: tuple[str, ...]
    poisoning_indicators: tuple[str, ...]

    @property
    def admissible(self) -> bool:
        return self.outcome is EvidenceAdmissionOutcome.ADMIT_CANDIDATE_EVIDENCE


_SOURCE_TRUST = {
    "owner_explicit": EvidenceTrustClass.OWNER,
    "authoritative_engineering_record": EvidenceTrustClass.AUTHORITATIVE_RUNTIME,
    "authoritative_runtime": EvidenceTrustClass.AUTHORITATIVE_RUNTIME,
    "ci": EvidenceTrustClass.VERIFIED_REPOSITORY,
    "deterministic_test": EvidenceTrustClass.VERIFIED_REPOSITORY,
    "repository_verified": EvidenceTrustClass.VERIFIED_REPOSITORY,
    "vendor_documentation": EvidenceTrustClass.VENDOR_DOCUMENTATION,
    "model_generated": EvidenceTrustClass.MODEL_GENERATED,
    "external_research": EvidenceTrustClass.EXTERNAL_UNTRUSTED,
    "web": EvidenceTrustClass.EXTERNAL_UNTRUSTED,
}

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "openai_style_key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{12,}"),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret)"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}"
        ),
    ),
)

_POISONING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?i)\b(?:ignore|disregard|override)\b.{0,40}"
            r"\b(?:previous|system|developer|authority|policy|instructions?)\b"
        ),
    ),
    (
        "authority_bypass",
        re.compile(
            r"(?i)\b(?:bypass|disable|weaken|skip)\b.{0,40}"
            r"\b(?:authority|approval|security|verifier|verification|policy)\b"
        ),
    ),
    (
        "fabricated_approval",
        re.compile(
            r"(?i)\b(?:owner|admin|administrator)\b.{0,24}"
            r"\b(?:approved|authorized|already approved)\b"
        ),
    ),
    (
        "execution_instruction",
        re.compile(
            r"(?i)\b(?:execute|run|launch|invoke)\b.{0,36}"
            r"\b(?:command|shell|powershell|bash|script|payload)\b"
        ),
    ),
    (
        "permission_escalation",
        re.compile(
            r"(?i)\b(?:grant|elevate|expand)\b.{0,32}"
            r"\b(?:permission|authority|privilege|access)\b"
        ),
    ),
    (
        "credential_persistence",
        re.compile(
            r"(?i)\b(?:save|remember|store|persist)\b.{0,40}"
            r"\b(?:credential|password|token|api[_-]?key|secret)\b"
        ),
    ),
)


class EngineeringEvidenceAdmissionGate:
    """Deterministic write-screening for future evidence admission paths."""

    def assess(self, request: EvidenceAdmissionRequest) -> EvidenceAdmissionDecision:
        if not isinstance(request, EvidenceAdmissionRequest):
            raise TypeError("request must be an EvidenceAdmissionRequest")
        trust = _SOURCE_TRUST.get(
            request.source_class,
            EvidenceTrustClass.EXTERNAL_UNTRUSTED,
        )
        secrets = tuple(
            name
            for name, pattern in _SECRET_PATTERNS
            if pattern.search(request.content)
        )
        poisoning = tuple(
            name
            for name, pattern in _POISONING_PATTERNS
            if pattern.search(request.content)
        )
        reasons: list[str] = []
        if secrets:
            reasons.append("secret_prohibited")
            return EvidenceAdmissionDecision(
                outcome=EvidenceAdmissionOutcome.REJECT,
                trust_class=trust,
                reason_codes=tuple(reasons),
                secret_indicators=secrets,
                poisoning_indicators=poisoning,
            )
        if poisoning:
            reasons.append("instruction_like_content_quarantined")
            return EvidenceAdmissionDecision(
                outcome=EvidenceAdmissionOutcome.QUARANTINE,
                trust_class=trust,
                reason_codes=tuple(reasons),
                secret_indicators=(),
                poisoning_indicators=poisoning,
            )
        if trust in {
            EvidenceTrustClass.EXTERNAL_UNTRUSTED,
            EvidenceTrustClass.MODEL_GENERATED,
        }:
            reasons.append("untrusted_source_requires_staging")
        else:
            reasons.append("deterministic_evidence_admission")
        return EvidenceAdmissionDecision(
            outcome=EvidenceAdmissionOutcome.ADMIT_CANDIDATE_EVIDENCE,
            trust_class=trust,
            reason_codes=tuple(reasons),
            secret_indicators=(),
            poisoning_indicators=(),
        )

    def require_admissible_evidence(self, evidence: EngineeringEvidence) -> None:
        if not isinstance(evidence, EngineeringEvidence):
            raise TypeError("evidence must be an EngineeringEvidence")
        decision = self.assess(
            EvidenceAdmissionRequest(
                source_class=evidence.source_class,
                content=f"{evidence.canonical_reference}\n{evidence.summary}",
                sensitivity=evidence.sensitivity,
            )
        )
        if not decision.admissible:
            reasons = ",".join(decision.reason_codes)
            raise EngineeringKnowledgeSecurityError(
                f"engineering evidence admission blocked: {reasons}"
            )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeIntegrityDecision:
    valid: bool
    reason_codes: tuple[str, ...]


class EngineeringKnowledgeIntegrityStore(Protocol):
    def get_engineering_knowledge_revision(
        self,
        revision_id: str,
    ) -> EngineeringKnowledgeRevision | None: ...

    def list_engineering_knowledge_facets(
        self,
        revision_id: str,
    ) -> tuple[EngineeringKnowledgeFacet, ...]: ...

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


class EngineeringKnowledgeIntegrityVerifier:
    """Verify the current deterministic REPAIR vertical from canonical records."""

    def verify(
        self,
        store: EngineeringKnowledgeIntegrityStore,
        revision_id: str,
    ) -> EngineeringKnowledgeIntegrityDecision:
        revision = store.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            return EngineeringKnowledgeIntegrityDecision(
                valid=False,
                reason_codes=("unknown_revision",),
            )

        reasons: list[str] = []
        if revision.kind_namespace != REPAIR_KIND_NAMESPACE:
            reasons.append("unsupported_integrity_kind")
        if revision.created_by != PROJECTOR_ID:
            reasons.append("unexpected_revision_producer")

        facets = store.list_engineering_knowledge_facets(revision_id)
        repair_facets = tuple(
            facet for facet in facets if facet.facet_type == REPAIR_FINDING_FACET_TYPE
        )
        if len(facets) != 1 or len(repair_facets) != 1:
            reasons.append("unexpected_facet_set")
            validated = None
        else:
            assessment = build_default_facet_registry().assess_for_decision(
                repair_facets[0]
            )
            if not assessment.eligible or assessment.validated is None:
                reasons.append("repair_facet_integrity_failure")
                validated = None
            else:
                validated = assessment.validated

        evidence = store.list_engineering_knowledge_evidence(revision_id)
        expected_evidence_types = {
            "incident",
            "repair_attempt",
            "repair_trigger_snapshot",
            "repair_policy_snapshot",
            "repair_verification",
        }
        evidence_by_type: dict[str, list[EngineeringEvidence]] = {}
        for item in evidence:
            evidence_by_type.setdefault(item.evidence_type, []).append(item)
            if item.integrity_algorithm != "sha256" or item.integrity_digest is None:
                reasons.append("evidence_missing_integrity_digest")
            if item.source_class != "authoritative_engineering_record":
                reasons.append("unexpected_repair_evidence_source")
        if set(evidence_by_type) != expected_evidence_types or any(
            len(items) != 1 for items in evidence_by_type.values()
        ):
            reasons.append("incomplete_repair_evidence_set")

        incident_id = _reference_suffix(
            evidence_by_type,
            evidence_type="incident",
            prefix="incident:",
        )
        attempt_id = _reference_suffix(
            evidence_by_type,
            evidence_type="repair_attempt",
            prefix="repair-attempt:",
        )

        if validated is not None and incident_id is not None and attempt_id is not None:
            facet = validated.facet
            expected_revision_digest = canonical_sha256(
                {
                    "projector": PROJECTOR_ID,
                    "knowledge_id": revision.knowledge_id,
                    "revision_number": revision.revision_number,
                    "kind_namespace": revision.kind_namespace,
                    "normalized_summary": revision.normalized_summary,
                    "valid_from_epoch": revision.valid_from_epoch,
                    "source_incident_id": incident_id,
                    "source_attempt_id": attempt_id,
                    "facet": {
                        "facet_type": facet.facet_type,
                        "schema_id": facet.schema_id,
                        "schema_version": facet.schema_version,
                        "schema_digest": facet.schema_digest,
                        "payload_digest": facet.payload_digest,
                    },
                }
            )
            if revision.canonical_digest != expected_revision_digest:
                reasons.append("revision_digest_mismatch")
        else:
            reasons.append("revision_digest_not_reconstructable")

        attestations = store.list_engineering_attestations(
            subject_type="knowledge_revision",
            subject_id=revision_id,
        )
        passing = tuple(
            item
            for item in attestations
            if item.predicate_type == REPAIR_VERIFICATION_PREDICATE
            and item.subject_digest == revision.canonical_digest
            and item.verdict is AttestationVerdict.PASS
        )
        if len(passing) != 1:
            reasons.append("repair_attestation_integrity_failure")

        return EngineeringKnowledgeIntegrityDecision(
            valid=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )


def _reference_suffix(
    evidence_by_type: dict[str, list[EngineeringEvidence]],
    *,
    evidence_type: str,
    prefix: str,
) -> str | None:
    items = evidence_by_type.get(evidence_type, [])
    if len(items) != 1:
        return None
    reference = items[0].canonical_reference
    if not reference.startswith(prefix):
        return None
    suffix = reference[len(prefix) :].strip()
    return suffix or None
