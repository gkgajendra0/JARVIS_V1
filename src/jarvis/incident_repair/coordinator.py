"""Idempotent unknown-incident admission into the Phase-6 EngineeringChange process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_change import ChangeArtifact, ChangeState, EngineeringChange
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.incidents import IncidentService
from jarvis.incidents.models import IncidentStatus
from jarvis.self_repair.domain import RepairPolicy, RepairTrigger
from jarvis.self_repair.registry import RepairRegistry

from .evidence import IncidentEvidencePackage, IncidentEvidencePackager
from .models import IncidentRepairTrigger
from .process import UNKNOWN_INCIDENT_REPAIR_PROCESS


class IncidentRepairAdmissionError(RuntimeError):
    """Incident cannot safely enter the unknown-repair process."""


class IncidentRepairAdmissionBlocked(IncidentRepairAdmissionError):
    """A higher-priority accepted deterministic repair path owns the trigger."""


class IncidentKnowledgeLookup(Protocol):
    def retrieve_revision_ids(
        self,
        package: IncidentEvidencePackage,
        *,
        now_epoch: float,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class IncidentRepairAdmission:
    trigger: IncidentRepairTrigger
    package: IncidentEvidencePackage
    change: EngineeringChange
    trigger_artifact_id: str
    evidence_artifact_id: str
    diagnostics_work_id: str


class IncidentRepairCoordinator:
    """Bind one unknown incident/revision to one durable diagnostic change."""

    def __init__(
        self,
        *,
        incidents: IncidentService,
        changes: ChangeCoordinator,
        packager: IncidentEvidencePackager | None = None,
        knowledge: IncidentKnowledgeLookup | None = None,
        repair_registry: RepairRegistry | None = None,
    ) -> None:
        if not isinstance(incidents, IncidentService):
            raise TypeError("incidents must be IncidentService")
        if not isinstance(changes, ChangeCoordinator):
            raise TypeError("changes must be ChangeCoordinator")
        if repair_registry is not None and not isinstance(
            repair_registry, RepairRegistry
        ):
            raise TypeError("repair_registry must be RepairRegistry")
        self._incidents = incidents
        self._changes = changes
        self._packager = packager or IncidentEvidencePackager()
        self._knowledge = knowledge
        self._repair_registry = repair_registry

    @staticmethod
    def _trigger_payload(trigger: IncidentRepairTrigger) -> dict[str, object]:
        return {
            "trigger_id": trigger.trigger_id,
            **trigger.canonical_payload(),
            "digest": trigger.digest,
        }

    @staticmethod
    def _persist_if_changed(
        change: EngineeringChange,
        *,
        kind: str,
        payload: dict[str, object],
        coordinator: ChangeCoordinator,
    ) -> ChangeArtifact:
        latest = coordinator.store.latest_artifact(change.change_id, kind)
        if latest is not None and latest.payload == payload:
            return latest
        return coordinator.store.add_artifact(
            change.change_id,
            kind=kind,
            payload=payload,
        )

    def _deterministic_policy(
        self,
        repair_trigger: RepairTrigger | None,
    ) -> RepairPolicy | None:
        if self._repair_registry is None or repair_trigger is None:
            return None
        policy = self._repair_registry.match(repair_trigger)
        if policy is None:
            return None
        if policy.automatic and policy.reversible:
            return policy
        return None

    def _validate_binding(
        self,
        trigger: IncidentRepairTrigger,
        repair_trigger: RepairTrigger | None,
    ) -> None:
        incident = self._incidents.get(trigger.incident_id)
        if incident is None:
            raise IncidentRepairAdmissionError("unknown incident")
        if incident.status in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            raise IncidentRepairAdmissionError(
                "resolved or closed incident cannot enter Phase 6"
            )

        evidence_ids = {item.evidence_id for item in incident.evidence}
        missing_evidence = tuple(
            item for item in trigger.evidence_ids if item not in evidence_ids
        )
        if missing_evidence:
            raise IncidentRepairAdmissionError(
                "trigger references evidence outside canonical incident"
            )

        affected = set(incident.affected_components)
        if any(component not in affected for component in trigger.component_ids):
            raise IncidentRepairAdmissionError(
                "trigger component is outside canonical incident"
            )

        if repair_trigger is not None:
            if repair_trigger.reason_code != trigger.reason_code:
                raise IncidentRepairAdmissionError(
                    "repair trigger reason does not match incident-repair trigger"
                )
            if repair_trigger.component_id not in trigger.component_ids:
                raise IncidentRepairAdmissionError(
                    "repair trigger component is outside incident-repair trigger"
                )

    def admit(
        self,
        trigger: IncidentRepairTrigger,
        *,
        repair_trigger: RepairTrigger | None = None,
    ) -> IncidentRepairAdmission:
        if not isinstance(trigger, IncidentRepairTrigger):
            raise TypeError("trigger must be IncidentRepairTrigger")
        if repair_trigger is not None and not isinstance(repair_trigger, RepairTrigger):
            raise TypeError("repair_trigger must be RepairTrigger")

        self._validate_binding(trigger, repair_trigger)
        deterministic = self._deterministic_policy(repair_trigger)
        if deterministic is not None:
            raise IncidentRepairAdmissionBlocked(
                "registered deterministic automatic repair has priority: "
                f"{deterministic.policy_id}/{deterministic.version}"
            )

        incident = self._incidents.mark_investigating(
            trigger.incident_id,
            now_epoch=trigger.created_at_epoch,
        )
        attempts = self._incidents.list_repair_attempts(
            trigger.incident_id,
            limit=self._packager.policy.max_repair_attempts + 1,
        )

        base_package = self._packager.build(
            incident=incident,
            source_revision=trigger.source_revision,
            trigger_digest=trigger.digest,
            repair_attempts=attempts,
            knowledge_revision_ids=(),
            now_epoch=trigger.created_at_epoch,
        )
        knowledge_revision_ids: tuple[str, ...] = ()
        if self._knowledge is not None:
            knowledge_revision_ids = self._knowledge.retrieve_revision_ids(
                base_package,
                now_epoch=trigger.created_at_epoch,
            )
        package = self._packager.build(
            incident=incident,
            source_revision=trigger.source_revision,
            trigger_digest=trigger.digest,
            repair_attempts=attempts,
            knowledge_revision_ids=knowledge_revision_ids,
            now_epoch=trigger.created_at_epoch,
        )

        source_session_id = f"incident:{trigger.incident_id}"
        source_turn_id = f"revision:{trigger.source_revision}"
        request = (
            f"Investigate incident {trigger.incident_id} at exact source revision "
            f"{trigger.source_revision}"
        )
        store = self._changes.store
        existing = store.find_by_source(
            source_session_id,
            source_turn_id,
            UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        )
        if existing is not None and existing.state in {
            ChangeState.CLOSED,
            ChangeState.REJECTED,
            ChangeState.FAILED,
            ChangeState.SUPERSEDED,
            ChangeState.ROLLED_BACK,
        }:
            raise IncidentRepairAdmissionError(
                "terminal incident-repair change already owns incident/revision"
            )

        change = store.create(
            request=request,
            process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
            process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
        )
        trigger_artifact = self._persist_if_changed(
            change,
            kind="incident_repair_trigger",
            payload=self._trigger_payload(trigger),
            coordinator=self._changes,
        )
        evidence_artifact = self._persist_if_changed(
            change,
            kind="incident_evidence",
            payload=package.to_payload(),
            coordinator=self._changes,
        )

        change = self._changes.reconcile(change.change_id)
        diagnostics = next(
            (
                stage
                for stage in store.list_stages(change.change_id)
                if stage.stage_key
                == UNKNOWN_INCIDENT_REPAIR_PROCESS.architecture_source_stage.stage_key
            ),
            None,
        )
        if diagnostics is None:
            raise IncidentRepairAdmissionError(
                "incident repair admission created no diagnostics WorkItem"
            )

        return IncidentRepairAdmission(
            trigger=trigger,
            package=package,
            change=change,
            trigger_artifact_id=trigger_artifact.artifact_id,
            evidence_artifact_id=evidence_artifact.artifact_id,
            diagnostics_work_id=diagnostics.work_id,
        )
