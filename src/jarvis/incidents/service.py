"""Deterministic incident grouping and engineering-memory lifecycle."""

from __future__ import annotations

from jarvis.incidents.models import (
    EvidenceReference,
    IncidentRecord,
    IncidentSeverity,
    IncidentStatus,
)
from jarvis.incidents.store import SqliteIncidentStore
from jarvis.self_model.health import HealthSnapshot, HealthState
from jarvis.self_repair.domain import RepairAttempt


class IncidentService:
    def __init__(
        self,
        store: SqliteIncidentStore,
        *,
        grouping_window_seconds: float = 15 * 60,
    ) -> None:
        if grouping_window_seconds <= 0:
            raise ValueError("grouping_window_seconds must be positive")
        self._store = store
        self._grouping_window_seconds = grouping_window_seconds

    def create_manual(
        self,
        *,
        symptom: str,
        affected_components: tuple[str, ...] | list[str] = (),
        title: str = "Owner-reported JARVIS issue",
        severity: IncidentSeverity = IncidentSeverity.WARNING,
        now_epoch: float | None = None,
    ) -> IncidentRecord:
        incident = IncidentRecord.create(
            title=title,
            symptom=symptom,
            affected_components=affected_components,
            severity=severity,
            now_epoch=now_epoch,
        )
        self._store.upsert(incident)
        return incident

    def record_health_transition(
        self,
        previous: HealthSnapshot,
        current: HealthSnapshot,
    ) -> IncidentRecord | None:
        if previous.state == current.state:
            return None
        if current.state not in {HealthState.DEGRADED, HealthState.FAILED}:
            return None
        now = current.evaluated_at_epoch
        existing = self._recent_open_for_component(
            current.component_id,
            now_epoch=now,
        )
        incident = existing or IncidentRecord.create(
            title=f"{current.component_id} became {current.state.value}",
            symptom="; ".join(current.summaries) or ", ".join(current.reason_codes),
            affected_components=(current.component_id,),
            severity=(
                IncidentSeverity.ERROR
                if current.state is HealthState.FAILED
                else IncidentSeverity.WARNING
            ),
            now_epoch=now,
        )
        evidence = EvidenceReference.create(
            kind="health_transition",
            reference=f"health:{current.component_id}:{int(now)}",
            summary=(
                f"{previous.state.value} -> {current.state.value}; "
                f"reasons={','.join(current.reason_codes)}"
            ),
            component_id=current.component_id,
            occurred_at_epoch=now,
        )
        incident = incident.add_evidence(evidence, now_epoch=now)
        self._store.upsert(incident)
        return incident

    def add_evidence(
        self,
        incident_id: str,
        evidence: EvidenceReference,
        *,
        now_epoch: float | None = None,
    ) -> IncidentRecord:
        incident = self._require(incident_id)
        updated = incident.add_evidence(evidence, now_epoch=now_epoch)
        self._store.upsert(updated)
        return updated

    def resolve(
        self,
        incident_id: str,
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
        incident = self._require(incident_id)
        resolved = incident.resolve(
            root_cause=root_cause,
            accepted_fix=accepted_fix,
            regression_tests=regression_tests,
            commit_sha=commit_sha,
            pr_number=pr_number,
            deployment_result=deployment_result,
            rollback_status=rollback_status,
            lessons=lessons,
            now_epoch=now_epoch,
        )
        self._store.upsert(resolved)
        return resolved

    def record_repair_attempt(self, attempt: RepairAttempt) -> RepairAttempt:
        """Persist a repair attempt under its canonical incident."""

        self._require(attempt.incident_id)
        self._store.upsert_repair_attempt(attempt)
        return attempt

    def get_repair_attempt(self, attempt_id: str) -> RepairAttempt | None:
        return self._store.get_repair_attempt(attempt_id)

    def list_repair_attempts(
        self,
        incident_id: str,
        *,
        limit: int = 100,
    ) -> tuple[RepairAttempt, ...]:
        self._require(incident_id)
        return self._store.list_repair_attempts(incident_id, limit=limit)

    def similar_resolved(
        self,
        component_id: str,
        *,
        limit: int = 10,
    ) -> tuple[IncidentRecord, ...]:
        normalized = str(component_id).strip().lower()
        return tuple(
            incident
            for incident in self._store.list_recent(
                limit=max(limit * 5, limit),
                status=IncidentStatus.RESOLVED,
            )
            if normalized in incident.affected_components
        )[:limit]

    def list_recent(
        self,
        *,
        limit: int = 50,
        status: IncidentStatus | None = None,
    ) -> tuple[IncidentRecord, ...]:
        """Return bounded recent engineering incidents through the service API."""

        return self._store.list_recent(limit=limit, status=status)

    def _recent_open_for_component(
        self,
        component_id: str,
        *,
        now_epoch: float,
    ) -> IncidentRecord | None:
        for incident in self._store.list_recent(limit=50):
            if incident.status not in {
                IncidentStatus.OPEN,
                IncidentStatus.INVESTIGATING,
                IncidentStatus.MITIGATED,
            }:
                continue
            if component_id not in incident.affected_components:
                continue
            if now_epoch - incident.updated_at_epoch <= self._grouping_window_seconds:
                return incident
        return None

    def _require(self, incident_id: str) -> IncidentRecord:
        incident = self._store.get(incident_id)
        if incident is None:
            raise KeyError(f"unknown incident: {incident_id}")
        return incident
