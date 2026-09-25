"""Deterministic projection of verified repair outcomes into EngineeringKnowledge."""

from __future__ import annotations

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
from jarvis.engineering_knowledge.repair_contracts import (
    PROJECTION_POLICY_ID,
    PROJECTOR_ID,
    REPAIR_KIND_NAMESPACE,
    REPAIR_VERIFICATION_PREDICATE,
)
from jarvis.engineering_knowledge.repair_facets import (
    REPAIR_FINDING_FACET_TYPE,
    REPAIR_FINDING_V1_SCHEMA_ID,
    REPAIR_FINDING_V1_SCHEMA_VERSION,
    RepairFindingV1Handler,
)
from jarvis.incidents.models import IncidentRecord
from jarvis.self_repair.domain import (
    RepairAttempt,
    RepairVerdict,
    RepairVerificationStatus,
)


class RepairKnowledgeProjectionError(ValueError):
    """The source repair attempt is not eligible for deterministic projection."""


class RepairKnowledgeProjectionStore(Protocol):
    def get(self, incident_id: str) -> IncidentRecord | None: ...

    def get_repair_attempt(self, attempt_id: str) -> RepairAttempt | None: ...

    def persist_engineering_knowledge_candidate(
        self,
        candidate: EngineeringKnowledgeCandidateBundle,
    ) -> EngineeringKnowledgeCandidateWriteResult: ...


@dataclass(frozen=True, slots=True)
class RepairKnowledgeProjectionResult:
    knowledge_id: str
    revision_id: str
    created: bool
    source_incident_id: str
    source_attempt_id: str


class RepairKnowledgeProjector:
    """Pure deterministic builder plus a narrow persistence orchestration boundary."""

    def project_attempt(
        self,
        store: RepairKnowledgeProjectionStore,
        attempt_id: str,
    ) -> RepairKnowledgeProjectionResult:
        normalized_attempt_id = str(attempt_id).strip()
        if not normalized_attempt_id:
            raise RepairKnowledgeProjectionError("attempt_id must not be empty")

        attempt = store.get_repair_attempt(normalized_attempt_id)
        if attempt is None:
            raise RepairKnowledgeProjectionError(
                f"unknown repair attempt: {normalized_attempt_id}"
            )
        incident = store.get(attempt.incident_id)
        if incident is None:
            raise RepairKnowledgeProjectionError(
                f"repair attempt references unknown incident: {attempt.incident_id}"
            )

        candidate = self.build_candidate(incident=incident, attempt=attempt)
        write = store.persist_engineering_knowledge_candidate(candidate)
        return RepairKnowledgeProjectionResult(
            knowledge_id=write.knowledge_id,
            revision_id=write.revision_id,
            created=write.created,
            source_incident_id=incident.incident_id,
            source_attempt_id=attempt.attempt_id,
        )

    def build_candidate(
        self,
        *,
        incident: IncidentRecord,
        attempt: RepairAttempt,
    ) -> EngineeringKnowledgeCandidateBundle:
        _assert_projectable(incident=incident, attempt=attempt)
        trigger = attempt.trigger_snapshot
        policy = attempt.policy_snapshot
        verification = attempt.verification
        assert trigger is not None
        assert policy is not None
        assert verification is not None
        assert attempt.finished_at_epoch is not None
        assert attempt.execution_result is not None

        knowledge_id = _stable_id(
            "knowledge",
            {
                "projector": PROJECTOR_ID,
                "source_attempt_id": attempt.attempt_id,
            },
        )
        revision_id = _stable_id(
            "revision",
            {
                "knowledge_id": knowledge_id,
                "revision_number": 1,
            },
        )
        created_at = attempt.finished_at_epoch

        repair_payload: dict[str, JSONValue] = {
            "component_id": attempt.action.component_id,
            "trigger": {
                "source": trigger.source,
                "reason_code": trigger.reason_code,
                "failure_signature": _failure_signature(attempt),
            },
            "repair": {
                "policy_id": policy.policy_id,
                "policy_version": policy.version,
                "action_kind": attempt.action.kind.value,
                "preconditions": list(policy.preconditions),
                "successful_sequence": [attempt.action.kind.value],
            },
            "verification": {
                "contract_id": verification.contract_id,
                "verdict": attempt.verdict.value,
            },
            "applicability": [
                {
                    "target_namespace": "jarvis.component",
                    "target_identity": attempt.action.component_id,
                    "matcher_type": "exact",
                    "constraint": {},
                    "required": True,
                }
            ],
            "required_resources": [],
            "revalidation": {
                "strategy": "verification_contract",
                "contract_id": verification.contract_id,
            },
        }
        handler = RepairFindingV1Handler()
        handler.validate_payload(repair_payload)
        facet_payload_bytes = canonicalize_json(repair_payload)
        facet_payload_digest = canonical_sha256(repair_payload)

        summary = (
            f"{attempt.action.component_id} {trigger.reason_code} recovered by "
            f"{attempt.action.kind.value}; verified by {verification.contract_id}"
        )
        revision_digest = canonical_sha256(
            {
                "projector": PROJECTOR_ID,
                "knowledge_id": knowledge_id,
                "revision_number": 1,
                "kind_namespace": REPAIR_KIND_NAMESPACE,
                "normalized_summary": summary,
                "valid_from_epoch": trigger.observed_at_epoch,
                "source_incident_id": incident.incident_id,
                "source_attempt_id": attempt.attempt_id,
                "facet": {
                    "facet_type": REPAIR_FINDING_FACET_TYPE,
                    "schema_id": REPAIR_FINDING_V1_SCHEMA_ID,
                    "schema_version": REPAIR_FINDING_V1_SCHEMA_VERSION,
                    "schema_digest": handler.schema_digest,
                    "payload_digest": facet_payload_digest,
                },
            }
        )

        identity = EngineeringKnowledgeIdentity(
            knowledge_id=knowledge_id,
            stable_label=(
                f"repair:{attempt.action.component_id}:{trigger.reason_code}"
            ),
            created_at_epoch=created_at,
            created_by=PROJECTOR_ID,
        )
        revision = EngineeringKnowledgeRevision(
            revision_id=revision_id,
            knowledge_id=knowledge_id,
            revision_number=1,
            kind_namespace=REPAIR_KIND_NAMESPACE,
            normalized_summary=summary,
            valid_from_epoch=trigger.observed_at_epoch,
            valid_to_epoch=None,
            system_from_epoch=created_at,
            system_to_epoch=None,
            sensitivity=KnowledgeSensitivity.STANDARD,
            freshness_state=KnowledgeFreshnessState.CURRENT,
            canonical_digest=revision_digest,
            created_at_epoch=created_at,
            created_by=PROJECTOR_ID,
        )
        facet = EngineeringKnowledgeFacet(
            facet_id=_stable_id(
                "facet",
                {
                    "revision_id": revision_id,
                    "facet_type": REPAIR_FINDING_FACET_TYPE,
                    "schema_id": REPAIR_FINDING_V1_SCHEMA_ID,
                    "schema_version": REPAIR_FINDING_V1_SCHEMA_VERSION,
                },
            ),
            revision_id=revision_id,
            facet_type=REPAIR_FINDING_FACET_TYPE,
            schema_id=REPAIR_FINDING_V1_SCHEMA_ID,
            schema_version=REPAIR_FINDING_V1_SCHEMA_VERSION,
            schema_digest=handler.schema_digest,
            producer=PROJECTOR_ID,
            payload_json=facet_payload_bytes.decode("utf-8"),
            payload_digest=facet_payload_digest,
            created_at_epoch=created_at,
        )

        applicability = EngineeringApplicability(
            applicability_id=_stable_id(
                "applicability",
                {
                    "revision_id": revision_id,
                    "target_namespace": "jarvis.component",
                    "target_identity": attempt.action.component_id,
                    "matcher_type": "exact",
                },
            ),
            revision_id=revision_id,
            target_namespace="jarvis.component",
            target_identity=attempt.action.component_id,
            matcher_type="exact",
            constraint_json="{}",
            required=True,
            created_at_epoch=created_at,
        )

        evidence = _build_evidence(
            incident=incident,
            attempt=attempt,
            revision_id=revision_id,
            created_at_epoch=created_at,
        )
        evidence_by_type = {item.evidence_type: item for item in evidence}
        links = (
            _link(
                revision_id,
                evidence_by_type["incident"],
                "derived_from",
                created_at,
            ),
            _link(
                revision_id,
                evidence_by_type["repair_attempt"],
                "derived_from",
                created_at,
            ),
            _link(
                revision_id,
                evidence_by_type["repair_trigger_snapshot"],
                "derived_from",
                created_at,
            ),
            _link(
                revision_id,
                evidence_by_type["repair_policy_snapshot"],
                "derived_from",
                created_at,
            ),
            _link(
                revision_id,
                evidence_by_type["repair_verification"],
                "verified_by",
                created_at,
            ),
        )
        evidence_ids = tuple(item.evidence_id for item in evidence)
        lifecycle = KnowledgeLifecycleEvent(
            event_id=_stable_id(
                "lifecycle-event",
                {
                    "revision_id": revision_id,
                    "to_state": KnowledgeLifecycleState.CANDIDATE.value,
                },
            ),
            revision_id=revision_id,
            from_state=None,
            to_state=KnowledgeLifecycleState.CANDIDATE,
            reason_code="verified_repair_projected",
            actor=PROJECTOR_ID,
            policy_id=PROJECTION_POLICY_ID,
            evidence_ids=evidence_ids,
            occurred_at_epoch=created_at,
        )
        attestation = EngineeringAttestation(
            attestation_id=_stable_id(
                "attestation",
                {
                    "revision_id": revision_id,
                    "predicate_type": REPAIR_VERIFICATION_PREDICATE,
                    "source_attempt_id": attempt.attempt_id,
                },
            ),
            subject_type="knowledge_revision",
            subject_id=revision_id,
            subject_digest=revision_digest,
            predicate_type=REPAIR_VERIFICATION_PREDICATE,
            producer=(f"{verification.verifier_id}:v{verification.verifier_version}"),
            expected_contract_json=canonicalize_json(
                {
                    "contract_id": verification.contract_id,
                    "required_status": RepairVerificationStatus.PASS.value,
                }
            ).decode("utf-8"),
            observed_result_json=canonicalize_json(
                {
                    "status": verification.status.value,
                    "summary": verification.summary,
                    "evidence_references": list(verification.evidence_references),
                }
            ).decode("utf-8"),
            verdict=AttestationVerdict.PASS,
            evidence_ids=(evidence_by_type["repair_verification"].evidence_id,),
            observed_at_epoch=verification.observed_at_epoch,
            created_at_epoch=created_at,
        )

        return EngineeringKnowledgeCandidateBundle(
            identity=identity,
            revision=revision,
            facets=(facet,),
            applicability=(applicability,),
            evidence=evidence,
            evidence_links=links,
            lifecycle_event=lifecycle,
            attestations=(attestation,),
        )


def _assert_projectable(
    *,
    incident: IncidentRecord,
    attempt: RepairAttempt,
) -> None:
    if not isinstance(incident, IncidentRecord):
        raise TypeError("incident must be an IncidentRecord")
    if not isinstance(attempt, RepairAttempt):
        raise TypeError("attempt must be a RepairAttempt")
    if attempt.incident_id != incident.incident_id:
        raise RepairKnowledgeProjectionError(
            "repair attempt incident identity does not match source incident"
        )
    if attempt.finished_at_epoch is None:
        raise RepairKnowledgeProjectionError("repair attempt is not completed")
    if attempt.verdict is not RepairVerdict.RECOVERED:
        raise RepairKnowledgeProjectionError(
            "only RECOVERED repair attempts may become candidates"
        )
    if attempt.verification is None:
        raise RepairKnowledgeProjectionError(
            "recovered repair attempt has no typed verification proof"
        )
    if attempt.verification.status is not RepairVerificationStatus.PASS:
        raise RepairKnowledgeProjectionError("repair verification status must be PASS")
    if attempt.trigger_snapshot is None:
        raise RepairKnowledgeProjectionError(
            "repair attempt has no immutable trigger snapshot"
        )
    if attempt.policy_snapshot is None:
        raise RepairKnowledgeProjectionError(
            "repair attempt has no immutable policy snapshot"
        )
    if attempt.execution_result is None or not attempt.execution_result.strip():
        raise RepairKnowledgeProjectionError("repair attempt has no execution result")
    if (
        attempt.verification.contract_id
        != attempt.policy_snapshot.verification_contract
    ):
        raise RepairKnowledgeProjectionError(
            "verification contract does not match immutable policy snapshot"
        )


def _failure_signature(attempt: RepairAttempt) -> str:
    trigger = attempt.trigger_snapshot
    assert trigger is not None
    return "trigger_sha256:" + canonical_sha256(trigger.to_payload())


def _build_evidence(
    *,
    incident: IncidentRecord,
    attempt: RepairAttempt,
    revision_id: str,
    created_at_epoch: float,
) -> tuple[EngineeringEvidence, ...]:
    trigger = attempt.trigger_snapshot
    policy = attempt.policy_snapshot
    verification = attempt.verification
    assert trigger is not None
    assert policy is not None
    assert verification is not None
    assert attempt.finished_at_epoch is not None
    assert attempt.execution_result is not None

    incident_payload: dict[str, JSONValue] = {
        "incident_id": incident.incident_id,
        "source_attempt_id": attempt.attempt_id,
    }
    attempt_payload: dict[str, JSONValue] = {
        "attempt_id": attempt.attempt_id,
        "incident_id": attempt.incident_id,
        "trigger_id": attempt.trigger_id,
        "policy_id": attempt.policy_id,
        "policy_version": attempt.policy_version,
        "action": {
            "action_id": attempt.action.action_id,
            "kind": attempt.action.kind.value,
            "risk_class": int(attempt.action.risk_class),
            "component_id": attempt.action.component_id,
            "created_at_epoch": attempt.action.created_at_epoch,
        },
        "attempt_number": attempt.attempt_number,
        "started_at_epoch": attempt.started_at_epoch,
        "finished_at_epoch": attempt.finished_at_epoch,
        "execution_result": attempt.execution_result,
        "pre_repair_evidence": list(attempt.pre_repair_evidence),
        "post_repair_evidence": list(attempt.post_repair_evidence),
        "verdict": attempt.verdict.value if attempt.verdict is not None else None,
    }
    trigger_payload = trigger.to_payload()
    policy_payload = policy.to_payload()
    verification_payload = verification.to_payload()

    return (
        _evidence(
            revision_id=revision_id,
            role="incident",
            canonical_reference=f"incident:{incident.incident_id}",
            summary=(
                f"Canonical incident {incident.incident_id} contains repair "
                f"attempt {attempt.attempt_id}"
            ),
            payload=incident_payload,
            occurred_at_epoch=attempt.started_at_epoch,
            observed_at_epoch=created_at_epoch,
            created_at_epoch=created_at_epoch,
            producer="jarvis.incidents",
        ),
        _evidence(
            revision_id=revision_id,
            role="repair_attempt",
            canonical_reference=f"repair-attempt:{attempt.attempt_id}",
            summary=attempt.execution_result,
            payload=attempt_payload,
            occurred_at_epoch=attempt.started_at_epoch,
            observed_at_epoch=attempt.finished_at_epoch,
            created_at_epoch=created_at_epoch,
            producer="jarvis.self_repair",
        ),
        _evidence(
            revision_id=revision_id,
            role="repair_trigger_snapshot",
            canonical_reference=f"repair-trigger:{trigger.trigger_id}",
            summary=(
                f"{trigger.component_id} {trigger.source} "
                f"{trigger.reason_code} ({trigger.health_state.value})"
            ),
            payload=trigger_payload,
            occurred_at_epoch=trigger.observed_at_epoch,
            observed_at_epoch=trigger.observed_at_epoch,
            created_at_epoch=created_at_epoch,
            producer="jarvis.self_repair",
        ),
        _evidence(
            revision_id=revision_id,
            role="repair_policy_snapshot",
            canonical_reference=(f"repair-policy:{policy.policy_id}:v{policy.version}"),
            summary=(
                f"{policy.action_kind.value} under {policy.verification_contract}"
            ),
            payload=policy_payload,
            occurred_at_epoch=attempt.started_at_epoch,
            observed_at_epoch=attempt.started_at_epoch,
            created_at_epoch=created_at_epoch,
            producer="jarvis.self_repair",
        ),
        _evidence(
            revision_id=revision_id,
            role="repair_verification",
            canonical_reference=f"repair-verification:{attempt.attempt_id}",
            summary=verification.summary,
            payload=verification_payload,
            occurred_at_epoch=verification.observed_at_epoch,
            observed_at_epoch=verification.observed_at_epoch,
            created_at_epoch=created_at_epoch,
            producer=(f"{verification.verifier_id}:v{verification.verifier_version}"),
        ),
    )


def _evidence(
    *,
    revision_id: str,
    role: str,
    canonical_reference: str,
    summary: str,
    payload: dict[str, JSONValue],
    occurred_at_epoch: float,
    observed_at_epoch: float,
    created_at_epoch: float,
    producer: str,
) -> EngineeringEvidence:
    return EngineeringEvidence(
        evidence_id=_stable_id(
            "evidence",
            {
                "revision_id": revision_id,
                "role": role,
                "canonical_reference": canonical_reference,
            },
        ),
        evidence_type=role,
        source_class="authoritative_engineering_record",
        canonical_reference=canonical_reference,
        summary=summary,
        occurred_at_epoch=occurred_at_epoch,
        observed_at_epoch=observed_at_epoch,
        sensitivity=KnowledgeSensitivity.STANDARD,
        producer=producer,
        integrity_algorithm="sha256",
        integrity_digest=canonical_sha256(payload),
        created_at_epoch=created_at_epoch,
    )


def _link(
    revision_id: str,
    evidence: EngineeringEvidence,
    relation_type: str,
    created_at_epoch: float,
) -> KnowledgeEvidenceLink:
    return KnowledgeEvidenceLink(
        revision_id=revision_id,
        evidence_id=evidence.evidence_id,
        relation_type=relation_type,
        created_at_epoch=created_at_epoch,
    )


def _stable_id(prefix: str, payload: dict[str, JSONValue]) -> str:
    return f"{prefix}:{canonical_sha256(payload)}"
