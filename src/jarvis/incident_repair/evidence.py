"""Bounded, redacted diagnostic evidence packages for Phase-6 incident repair."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from jarvis.engineering_knowledge.security import (
    EngineeringEvidenceAdmissionGate,
    EvidenceAdmissionRequest,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incidents.models import EvidenceReference, IncidentRecord
from jarvis.observability.redaction import redact_data
from jarvis.self_repair.domain import RepairAttempt

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_BLOCKED_TEXT = "[BLOCKED_UNSAFE_EVIDENCE]"
_TRUNCATED = "...[TRUNCATED]"

_DEFAULT_ALLOWED_KINDS = (
    "crash_fingerprint",
    "deterministic_test",
    "exception",
    "health_transition",
    "owner_report",
    "process_exit",
    "provider_failure",
    "repair_budget_exhausted",
    "runtime_error",
    "self_repair",
    "structured_log",
    "test_failure",
    "traceback",
)


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _revision(value: object) -> str:
    text = _required_text(value, field="source_revision").lower()
    if _GIT_REVISION.fullmatch(text) is None:
        raise ValueError("source_revision must be an exact Git object id")
    return text


def _finite_epoch(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return normalized


def _clip(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - len(_TRUNCATED), 1)] + _TRUNCATED


@dataclass(frozen=True, slots=True)
class IncidentEvidencePolicy:
    allowed_kinds: tuple[str, ...] = _DEFAULT_ALLOWED_KINDS
    max_evidence_items: int = 32
    max_repair_attempts: int = 16
    max_knowledge_revisions: int = 8
    max_raw_item_chars: int = 8192
    max_reference_chars: int = 512
    max_summary_chars: int = 2048
    max_incident_text_chars: int = 2048

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                {
                    str(item).strip().lower()
                    for item in self.allowed_kinds
                    if str(item).strip()
                }
            )
        )
        if not normalized:
            raise ValueError("allowed_kinds must not be empty")
        for field_name in (
            "max_evidence_items",
            "max_repair_attempts",
            "max_knowledge_revisions",
            "max_raw_item_chars",
            "max_reference_chars",
            "max_summary_chars",
            "max_incident_text_chars",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        object.__setattr__(self, "allowed_kinds", normalized)


@dataclass(frozen=True, slots=True)
class PackagedEvidenceReference:
    evidence_id: str
    kind: str
    reference: str
    summary: str
    occurred_at_epoch: float
    component_id: str | None


@dataclass(frozen=True, slots=True)
class ExcludedEvidenceReference:
    evidence_id: str
    kind: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackagedRepairAttempt:
    attempt_id: str
    trigger_id: str
    policy_id: str
    policy_version: int
    action_kind: str
    risk_class: int
    component_id: str
    attempt_number: int
    started_at_epoch: float
    finished_at_epoch: float | None
    verdict: str | None
    trigger_source: str | None
    reason_code: str | None
    health_state: str | None
    verification_contract: str | None
    verification_status: str | None
    verification_summary: str | None


@dataclass(frozen=True, slots=True)
class IncidentEvidencePackage:
    package_id: str
    incident_id: str
    source_revision: str
    trigger_digest: str
    title: str
    symptom: str
    severity: str
    status: str
    affected_components: tuple[str, ...]
    evidence: tuple[PackagedEvidenceReference, ...]
    excluded_evidence: tuple[ExcludedEvidenceReference, ...]
    repair_attempts: tuple[PackagedRepairAttempt, ...]
    knowledge_revision_ids: tuple[str, ...]
    package_reason_codes: tuple[str, ...]
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        incident_id: str,
        source_revision: str,
        trigger_digest: str,
        title: str,
        symptom: str,
        severity: str,
        status: str,
        affected_components: tuple[str, ...],
        evidence: tuple[PackagedEvidenceReference, ...],
        excluded_evidence: tuple[ExcludedEvidenceReference, ...],
        repair_attempts: tuple[PackagedRepairAttempt, ...],
        knowledge_revision_ids: tuple[str, ...],
        package_reason_codes: tuple[str, ...],
        created_at_epoch: float,
    ) -> IncidentEvidencePackage:
        created = _finite_epoch(created_at_epoch, field="created_at_epoch")
        payload = {
            "incident_id": _required_text(incident_id, field="incident_id"),
            "source_revision": _revision(source_revision),
            "trigger_digest": _required_text(
                trigger_digest,
                field="trigger_digest",
            ).lower(),
            "title": _required_text(title, field="title"),
            "symptom": _required_text(symptom, field="symptom"),
            "severity": _required_text(severity, field="severity"),
            "status": _required_text(status, field="status"),
            "affected_components": list(affected_components),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "reference": item.reference,
                    "summary": item.summary,
                    "occurred_at_epoch": item.occurred_at_epoch,
                    "component_id": item.component_id,
                }
                for item in evidence
            ],
            "excluded_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "reason_codes": list(item.reason_codes),
                }
                for item in excluded_evidence
            ],
            "repair_attempts": [
                {
                    "attempt_id": item.attempt_id,
                    "trigger_id": item.trigger_id,
                    "policy_id": item.policy_id,
                    "policy_version": item.policy_version,
                    "action_kind": item.action_kind,
                    "risk_class": item.risk_class,
                    "component_id": item.component_id,
                    "attempt_number": item.attempt_number,
                    "started_at_epoch": item.started_at_epoch,
                    "finished_at_epoch": item.finished_at_epoch,
                    "verdict": item.verdict,
                    "trigger_source": item.trigger_source,
                    "reason_code": item.reason_code,
                    "health_state": item.health_state,
                    "verification_contract": item.verification_contract,
                    "verification_status": item.verification_status,
                    "verification_summary": item.verification_summary,
                }
                for item in repair_attempts
            ],
            "knowledge_revision_ids": list(knowledge_revision_ids),
            "package_reason_codes": list(package_reason_codes),
            "created_at_epoch": created,
        }
        digest = canonical_digest(payload)
        return cls(
            package_id=f"incident_evidence_{digest[:16]}",
            incident_id=str(payload["incident_id"]),
            source_revision=str(payload["source_revision"]),
            trigger_digest=str(payload["trigger_digest"]),
            title=str(payload["title"]),
            symptom=str(payload["symptom"]),
            severity=str(payload["severity"]),
            status=str(payload["status"]),
            affected_components=tuple(payload["affected_components"]),
            evidence=evidence,
            excluded_evidence=excluded_evidence,
            repair_attempts=repair_attempts,
            knowledge_revision_ids=tuple(payload["knowledge_revision_ids"]),
            package_reason_codes=tuple(payload["package_reason_codes"]),
            created_at_epoch=created,
            digest=digest,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "incident_id": self.incident_id,
            "source_revision": self.source_revision,
            "trigger_digest": self.trigger_digest,
            "title": self.title,
            "symptom": self.symptom,
            "severity": self.severity,
            "status": self.status,
            "affected_components": list(self.affected_components),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "reference": item.reference,
                    "summary": item.summary,
                    "occurred_at_epoch": item.occurred_at_epoch,
                    "component_id": item.component_id,
                }
                for item in self.evidence
            ],
            "excluded_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "reason_codes": list(item.reason_codes),
                }
                for item in self.excluded_evidence
            ],
            "repair_attempts": [
                {
                    "attempt_id": item.attempt_id,
                    "trigger_id": item.trigger_id,
                    "policy_id": item.policy_id,
                    "policy_version": item.policy_version,
                    "action_kind": item.action_kind,
                    "risk_class": item.risk_class,
                    "component_id": item.component_id,
                    "attempt_number": item.attempt_number,
                    "started_at_epoch": item.started_at_epoch,
                    "finished_at_epoch": item.finished_at_epoch,
                    "verdict": item.verdict,
                    "trigger_source": item.trigger_source,
                    "reason_code": item.reason_code,
                    "health_state": item.health_state,
                    "verification_contract": item.verification_contract,
                    "verification_status": item.verification_status,
                    "verification_summary": item.verification_summary,
                }
                for item in self.repair_attempts
            ],
            "knowledge_revision_ids": list(self.knowledge_revision_ids),
            "package_reason_codes": list(self.package_reason_codes),
            "created_at_epoch": self.created_at_epoch,
            "digest": self.digest,
        }


class IncidentEvidencePackager:
    """Build the only Phase-6 model-visible incident evidence package."""

    def __init__(
        self,
        *,
        policy: IncidentEvidencePolicy | None = None,
        admission_gate: EngineeringEvidenceAdmissionGate | None = None,
    ) -> None:
        self.policy = policy or IncidentEvidencePolicy()
        self._gate = admission_gate or EngineeringEvidenceAdmissionGate()

    def _safe_text(
        self,
        value: str,
        *,
        limit: int,
        source_class: str = "authoritative_runtime",
    ) -> tuple[str, tuple[str, ...]]:
        raw = str(value)
        if len(raw) > self.policy.max_raw_item_chars:
            return _BLOCKED_TEXT, ("oversize_evidence_text",)
        decision = self._gate.assess(
            EvidenceAdmissionRequest(
                source_class=source_class,
                content=raw,
            )
        )
        if not decision.admissible:
            return _BLOCKED_TEXT, tuple(decision.reason_codes)
        sanitized = str(redact_data(raw))
        return _clip(sanitized, limit=limit), ()

    def _package_evidence(
        self,
        evidence: EvidenceReference,
    ) -> tuple[PackagedEvidenceReference | None, ExcludedEvidenceReference | None]:
        kind = str(evidence.kind).strip().lower()
        if kind not in self.policy.allowed_kinds:
            return None, ExcludedEvidenceReference(
                evidence_id=evidence.evidence_id,
                kind=kind or "unknown",
                reason_codes=("evidence_kind_not_allowed",),
            )

        combined = f"{evidence.reference}\n{evidence.summary}"
        if len(combined) > self.policy.max_raw_item_chars:
            return None, ExcludedEvidenceReference(
                evidence_id=evidence.evidence_id,
                kind=kind,
                reason_codes=("oversize_evidence_text",),
            )
        decision = self._gate.assess(
            EvidenceAdmissionRequest(
                source_class="authoritative_runtime",
                content=combined,
            )
        )
        if not decision.admissible:
            return None, ExcludedEvidenceReference(
                evidence_id=evidence.evidence_id,
                kind=kind,
                reason_codes=tuple(decision.reason_codes),
            )

        reference = _clip(
            str(redact_data(evidence.reference)),
            limit=self.policy.max_reference_chars,
        )
        summary = _clip(
            str(redact_data(evidence.summary)),
            limit=self.policy.max_summary_chars,
        )
        return (
            PackagedEvidenceReference(
                evidence_id=evidence.evidence_id,
                kind=kind,
                reference=reference,
                summary=summary,
                occurred_at_epoch=float(evidence.occurred_at_epoch),
                component_id=evidence.component_id,
            ),
            None,
        )

    def _package_attempt(self, attempt: RepairAttempt) -> PackagedRepairAttempt:
        snapshot = attempt.trigger_snapshot
        verification = attempt.verification
        verification_summary = None
        if verification is not None:
            safe_summary, reasons = self._safe_text(
                verification.summary,
                limit=self.policy.max_summary_chars,
            )
            verification_summary = None if reasons else safe_summary
        return PackagedRepairAttempt(
            attempt_id=attempt.attempt_id,
            trigger_id=attempt.trigger_id,
            policy_id=attempt.policy_id,
            policy_version=attempt.policy_version,
            action_kind=attempt.action.kind.value,
            risk_class=int(attempt.action.risk_class),
            component_id=attempt.action.component_id,
            attempt_number=attempt.attempt_number,
            started_at_epoch=float(attempt.started_at_epoch),
            finished_at_epoch=(
                None
                if attempt.finished_at_epoch is None
                else float(attempt.finished_at_epoch)
            ),
            verdict=None if attempt.verdict is None else attempt.verdict.value,
            trigger_source=None if snapshot is None else snapshot.source,
            reason_code=None if snapshot is None else snapshot.reason_code,
            health_state=(None if snapshot is None else snapshot.health_state.value),
            verification_contract=(
                None if verification is None else verification.contract_id
            ),
            verification_status=(
                None if verification is None else verification.status.value
            ),
            verification_summary=verification_summary,
        )

    def build(
        self,
        *,
        incident: IncidentRecord,
        source_revision: str,
        trigger_digest: str,
        repair_attempts: tuple[RepairAttempt, ...] = (),
        knowledge_revision_ids: tuple[str, ...] = (),
        now_epoch: float,
    ) -> IncidentEvidencePackage:
        if not isinstance(incident, IncidentRecord):
            raise TypeError("incident must be IncidentRecord")
        created = _finite_epoch(now_epoch, field="now_epoch")

        title, title_reasons = self._safe_text(
            incident.title,
            limit=self.policy.max_incident_text_chars,
        )
        symptom, symptom_reasons = self._safe_text(
            incident.symptom,
            limit=self.policy.max_incident_text_chars,
        )

        included: list[PackagedEvidenceReference] = []
        excluded: list[ExcludedEvidenceReference] = []
        for item in incident.evidence[: self.policy.max_evidence_items]:
            packaged, rejected = self._package_evidence(item)
            if packaged is not None:
                included.append(packaged)
            if rejected is not None:
                excluded.append(rejected)
        for item in incident.evidence[self.policy.max_evidence_items :]:
            excluded.append(
                ExcludedEvidenceReference(
                    evidence_id=item.evidence_id,
                    kind=str(item.kind).strip().lower() or "unknown",
                    reason_codes=("evidence_item_limit_exceeded",),
                )
            )

        attempts = tuple(
            self._package_attempt(item)
            for item in repair_attempts[: self.policy.max_repair_attempts]
        )
        knowledge_ids = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in knowledge_revision_ids
                if str(item).strip()
            )
        )[: self.policy.max_knowledge_revisions]

        package_reasons = tuple(
            dict.fromkeys(
                (
                    *(f"title:{reason}" for reason in title_reasons),
                    *(f"symptom:{reason}" for reason in symptom_reasons),
                    *(
                        ("repair_attempt_limit_exceeded",)
                        if len(repair_attempts) > self.policy.max_repair_attempts
                        else ()
                    ),
                    *(
                        ("knowledge_revision_limit_exceeded",)
                        if len(knowledge_revision_ids)
                        > self.policy.max_knowledge_revisions
                        else ()
                    ),
                )
            )
        )

        return IncidentEvidencePackage.create(
            incident_id=incident.incident_id,
            source_revision=source_revision,
            trigger_digest=trigger_digest,
            title=title,
            symptom=symptom,
            severity=incident.severity.value,
            status=incident.status.value,
            affected_components=tuple(incident.affected_components),
            evidence=tuple(included),
            excluded_evidence=tuple(excluded),
            repair_attempts=attempts,
            knowledge_revision_ids=knowledge_ids,
            package_reason_codes=package_reasons,
            created_at_epoch=created,
        )
