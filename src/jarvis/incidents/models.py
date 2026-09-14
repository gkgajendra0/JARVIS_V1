"""Incident and engineering-memory records for JARVIS operations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    kind: str
    reference: str
    summary: str
    occurred_at_epoch: float
    component_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        reference: str,
        summary: str,
        component_id: str | None = None,
        occurred_at_epoch: float | None = None,
    ) -> EvidenceReference:
        return cls(
            evidence_id=str(uuid.uuid4()),
            kind=str(kind).strip().lower(),
            reference=str(reference).strip(),
            summary=str(summary).strip(),
            occurred_at_epoch=(
                time.time() if occurred_at_epoch is None else occurred_at_epoch
            ),
            component_id=(
                str(component_id).strip().lower() if component_id is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    incident_id: str
    title: str
    symptom: str
    severity: IncidentSeverity
    status: IncidentStatus
    created_at_epoch: float
    updated_at_epoch: float
    affected_components: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...] = ()
    root_cause: str | None = None
    accepted_fix: str | None = None
    regression_tests: tuple[str, ...] = ()
    commit_sha: str | None = None
    pr_number: int | None = None
    deployment_result: str | None = None
    rollback_status: str | None = None
    lessons: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        title: str,
        symptom: str,
        affected_components: tuple[str, ...] | list[str] = (),
        severity: IncidentSeverity = IncidentSeverity.WARNING,
        now_epoch: float | None = None,
    ) -> IncidentRecord:
        now = time.time() if now_epoch is None else now_epoch
        return cls(
            incident_id=str(uuid.uuid4()),
            title=str(title).strip(),
            symptom=str(symptom).strip(),
            severity=severity,
            status=IncidentStatus.OPEN,
            created_at_epoch=now,
            updated_at_epoch=now,
            affected_components=tuple(
                sorted(
                    {
                        str(item).strip().lower()
                        for item in affected_components
                        if str(item).strip()
                    }
                )
            ),
        )

    def add_evidence(
        self,
        evidence: EvidenceReference,
        *,
        now_epoch: float | None = None,
    ) -> IncidentRecord:
        return replace(
            self,
            evidence=(*self.evidence, evidence),
            updated_at_epoch=(time.time() if now_epoch is None else now_epoch),
        )

    def resolve(
        self,
        *,
        root_cause: str,
        accepted_fix: str,
        regression_tests: tuple[str, ...] | list[str] = (),
        commit_sha: str | None = None,
        pr_number: int | None = None,
        deployment_result: str | None = None,
        rollback_status: str | None = None,
        lessons: tuple[str, ...] | list[str] = (),
        now_epoch: float | None = None,
    ) -> IncidentRecord:
        return replace(
            self,
            status=IncidentStatus.RESOLVED,
            root_cause=str(root_cause).strip(),
            accepted_fix=str(accepted_fix).strip(),
            regression_tests=tuple(str(item).strip() for item in regression_tests),
            commit_sha=(str(commit_sha).strip() if commit_sha else None),
            pr_number=pr_number,
            deployment_result=(
                str(deployment_result).strip() if deployment_result else None
            ),
            rollback_status=(str(rollback_status).strip() if rollback_status else None),
            lessons=tuple(str(item).strip() for item in lessons),
            updated_at_epoch=(time.time() if now_epoch is None else now_epoch),
        )
