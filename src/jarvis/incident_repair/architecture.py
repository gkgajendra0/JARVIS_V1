"""Deterministic Phase-6 diagnosis -> repair-architecture handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.engineering_change.models import (
    ChangeArtifact,
    ChangeConflict,
    ChangeState,
    ChangeStage,
    EngineeringChange,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.models import WorkItem, WorkState

from .process import UNKNOWN_INCIDENT_REPAIR_PROCESS


class IncidentRepairArchitectureError(ChangeConflict):
    """Diagnosis/architecture provenance is missing, stale, or non-buildable."""


@dataclass(frozen=True, slots=True)
class IncidentRepairArchitecturePlan:
    incident_id: str
    diagnosis_artifact_id: str
    diagnosis_artifact_digest: str
    diagnosis_id: str
    diagnosis_digest: str
    source_revision: str
    repair_scope: str
    allowed_paths: tuple[str, ...]
    allowed_components: tuple[str, ...]
    verification_targets: tuple[str, ...]
    knowledge_revision_ids: tuple[str, ...]
    build_permitted: bool = True
    protected_surface_review_required: bool = True
    rollback_strategy: str = "revert_candidate_commit_before_promotion"
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "incident_id",
            "diagnosis_artifact_id",
            "diagnosis_artifact_digest",
            "diagnosis_id",
            "diagnosis_digest",
            "source_revision",
            "repair_scope",
            "rollback_strategy",
        ):
            if not str(getattr(self, field_name)).strip():
                raise IncidentRepairArchitectureError(
                    f"{field_name} must not be empty"
                )
        if not self.verification_targets:
            raise IncidentRepairArchitectureError(
                "repair architecture requires verification targets"
            )
        if not self.allowed_paths and not self.allowed_components:
            raise IncidentRepairArchitectureError(
                "repair architecture requires bounded path or component scope"
            )
        if not self.build_permitted:
            raise IncidentRepairArchitectureError(
                "buildable repair architecture must explicitly permit build"
            )
        if self.schema_version != 1:
            raise IncidentRepairArchitectureError(
                "unsupported repair architecture schema version"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": "incident_repair_architecture.v1",
            "schema_version": self.schema_version,
            "process_key": UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
            "process_version": UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
            "incident_id": self.incident_id,
            "diagnosis_artifact_id": self.diagnosis_artifact_id,
            "diagnosis_artifact_digest": self.diagnosis_artifact_digest,
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "source_revision": self.source_revision,
            "repair_scope": self.repair_scope,
            "allowed_paths": list(self.allowed_paths),
            "allowed_components": list(self.allowed_components),
            "verification_targets": list(self.verification_targets),
            "knowledge_revision_ids": list(self.knowledge_revision_ids),
            "build_permitted": self.build_permitted,
            "protected_surface_review_required": self.protected_surface_review_required,
            "rollback_strategy": self.rollback_strategy,
        }


def _normalized_unique(values: object) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return ()
    return tuple(
        dict.fromkeys(
            str(item).strip()
            for item in values
            if str(item).strip()
        )
    )


def _diagnosis_payload(artifact: ChangeArtifact) -> dict[str, Any]:
    raw = artifact.payload.get("diagnosis")
    if not isinstance(raw, dict):
        raise IncidentRepairArchitectureError(
            "diagnosis artifact lacks structured diagnosis"
        )
    return dict(raw)


def _validate_completed_diagnosis(
    store: ChangeStore,
    *,
    change: EngineeringChange,
    stage: ChangeStage,
    work: WorkItem,
) -> tuple[ChangeArtifact, dict[str, Any]]:
    if work.state is not WorkState.COMPLETED:
        raise IncidentRepairArchitectureError(
            "repair architecture requires completed diagnostics"
        )
    if stage.work_id != work.work_id or stage.change_id != change.change_id:
        raise IncidentRepairArchitectureError(
            "diagnostic work identity does not match change stage"
        )
    latest = store.latest_artifact(change.change_id, "diagnosis")
    if latest is None:
        raise IncidentRepairArchitectureError(
            "completed diagnostics produced no diagnosis artifact"
        )
    diagnosis = _diagnosis_payload(latest)

    if str(diagnosis.get("change_id") or "") != change.change_id:
        raise IncidentRepairArchitectureError(
            "diagnosis belongs to a different EngineeringChange"
        )
    if str(diagnosis.get("work_id") or "") != work.work_id:
        raise IncidentRepairArchitectureError(
            "diagnosis belongs to a different diagnostic WorkItem"
        )

    result = work.result
    if (
        result.get("diagnosis_artifact_id") != latest.artifact_id
        or result.get("diagnosis_artifact_digest") != latest.digest
        or result.get("diagnosis") != diagnosis
    ):
        raise IncidentRepairArchitectureError(
            "diagnosis artifact does not match canonical WorkItem result"
        )

    trigger = store.latest_artifact(change.change_id, "incident_repair_trigger")
    if trigger is None:
        raise IncidentRepairArchitectureError(
            "incident repair trigger artifact is missing"
        )
    source_revision = str(diagnosis.get("source_revision") or "").strip().lower()
    if source_revision != str(
        trigger.payload.get("source_revision") or ""
    ).strip().lower():
        raise IncidentRepairArchitectureError(
            "diagnosis source revision differs from admitted incident revision"
        )
    return latest, diagnosis


def derive_incident_repair_architecture(
    store: ChangeStore,
    *,
    change: EngineeringChange,
    stage: ChangeStage,
    work: WorkItem,
) -> ChangeArtifact | None:
    """Persist one deterministic architecture for a supported diagnosis.

    An inconclusive diagnosis is truthful terminal evidence and intentionally
    produces no build architecture.
    """

    if (
        change.process_key != UNKNOWN_INCIDENT_REPAIR_PROCESS.key
        or change.process_version != UNKNOWN_INCIDENT_REPAIR_PROCESS.version
    ):
        raise IncidentRepairArchitectureError(
            "incident-repair architecture handler received wrong process"
        )

    diagnosis_artifact, diagnosis = _validate_completed_diagnosis(
        store,
        change=change,
        stage=stage,
        work=work,
    )
    disposition = str(diagnosis.get("disposition") or "").strip()
    if disposition == "inconclusive":
        return None
    if disposition != "supported_repair":
        raise IncidentRepairArchitectureError(
            "diagnosis disposition cannot produce a repair architecture"
        )

    selected_hypothesis_id = str(
        diagnosis.get("selected_hypothesis_id") or ""
    ).strip()
    hypotheses = diagnosis.get("hypotheses")
    selected = None
    if isinstance(hypotheses, list):
        selected = next(
            (
                item
                for item in hypotheses
                if isinstance(item, dict)
                and str(item.get("hypothesis_id") or "").strip()
                == selected_hypothesis_id
            ),
            None,
        )
    if (
        not selected_hypothesis_id
        or not isinstance(selected, dict)
        or selected.get("status") != "supported"
    ):
        raise IncidentRepairArchitectureError(
            "repair architecture requires selected supported hypothesis"
        )

    plan = IncidentRepairArchitecturePlan(
        incident_id=str(diagnosis.get("incident_id") or "").strip(),
        diagnosis_artifact_id=diagnosis_artifact.artifact_id,
        diagnosis_artifact_digest=diagnosis_artifact.digest,
        diagnosis_id=str(diagnosis.get("diagnosis_id") or "").strip(),
        diagnosis_digest=str(diagnosis.get("digest") or "").strip(),
        source_revision=str(diagnosis.get("source_revision") or "").strip().lower(),
        repair_scope=str(diagnosis.get("proposed_repair_scope") or "").strip(),
        allowed_paths=_normalized_unique(diagnosis.get("affected_paths")),
        allowed_components=_normalized_unique(
            diagnosis.get("affected_components")
        ),
        verification_targets=_normalized_unique(
            diagnosis.get("verification_targets")
        ),
        knowledge_revision_ids=_normalized_unique(
            diagnosis.get("knowledge_revision_ids")
        ),
    )
    payload = plan.to_payload()

    current = store.latest_artifact(change.change_id, "architecture")
    if current is not None and current.payload == payload:
        return current
    return store.add_artifact(
        change.change_id,
        kind="architecture",
        payload=payload,
    )


def ensure_incident_repair_architecture_current(
    store: ChangeStore,
    change_id: str,
    *,
    artifact_id: str | None = None,
) -> ChangeArtifact:
    """Validate exact diagnosis/work/trigger provenance before owner review/build."""

    change = store.require(change_id)
    if (
        change.process_key != UNKNOWN_INCIDENT_REPAIR_PROCESS.key
        or change.process_version != UNKNOWN_INCIDENT_REPAIR_PROCESS.version
    ):
        raise IncidentRepairArchitectureError(
            "change is not an incident-repair process"
        )

    architecture = store.latest_artifact(change_id, "architecture")
    if architecture is None:
        raise IncidentRepairArchitectureError(
            "incident-repair architecture is missing"
        )
    if artifact_id is not None and architecture.artifact_id != artifact_id:
        raise IncidentRepairArchitectureError(
            "incident-repair architecture was superseded"
        )

    payload = architecture.payload
    if (
        payload.get("schema") != "incident_repair_architecture.v1"
        or payload.get("schema_version") != 1
        or payload.get("process_key") != UNKNOWN_INCIDENT_REPAIR_PROCESS.key
        or payload.get("process_version")
        != UNKNOWN_INCIDENT_REPAIR_PROCESS.version
        or payload.get("build_permitted") is not True
        or payload.get("protected_surface_review_required") is not True
    ):
        raise IncidentRepairArchitectureError(
            "incident-repair architecture contract is invalid"
        )

    diagnosis_artifact = store.latest_artifact(change_id, "diagnosis")
    if diagnosis_artifact is None:
        raise IncidentRepairArchitectureError(
            "current diagnosis artifact is missing"
        )
    if (
        payload.get("diagnosis_artifact_id") != diagnosis_artifact.artifact_id
        or payload.get("diagnosis_artifact_digest") != diagnosis_artifact.digest
    ):
        raise IncidentRepairArchitectureError(
            "architecture is not bound to current diagnosis"
        )

    diagnosis = _diagnosis_payload(diagnosis_artifact)
    if (
        diagnosis.get("disposition") != "supported_repair"
        or payload.get("diagnosis_id") != diagnosis.get("diagnosis_id")
        or payload.get("diagnosis_digest") != diagnosis.get("digest")
        or payload.get("source_revision") != diagnosis.get("source_revision")
        or payload.get("repair_scope") != diagnosis.get("proposed_repair_scope")
        or payload.get("allowed_paths") != diagnosis.get("affected_paths")
        or payload.get("allowed_components")
        != diagnosis.get("affected_components")
        or payload.get("verification_targets")
        != diagnosis.get("verification_targets")
        or payload.get("knowledge_revision_ids")
        != diagnosis.get("knowledge_revision_ids")
    ):
        raise IncidentRepairArchitectureError(
            "architecture content drifted from current diagnosis"
        )

    stage = next(
        (
            item
            for item in store.list_stages(change_id)
            if item.stage_key
            == UNKNOWN_INCIDENT_REPAIR_PROCESS.architecture_source_stage.stage_key
        ),
        None,
    )
    if stage is None:
        raise IncidentRepairArchitectureError(
            "diagnostic stage is missing"
        )
    work = store.work.require(stage.work_id)
    _validate_completed_diagnosis(
        store,
        change=change,
        stage=stage,
        work=work,
    )
    return architecture


class IncidentRepairDevelopmentRevisionResolver:
    """Resolve the exact approved source revision for Phase-6 DEVELOPMENT work."""

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    def revision_for(self, work_id: str) -> str | None:
        stage = self._store.stage_for_work(str(work_id).strip())
        if stage is None:
            return None
        change = self._store.require(stage.change_id)
        if (
            change.process_key != UNKNOWN_INCIDENT_REPAIR_PROCESS.key
            or change.process_version != UNKNOWN_INCIDENT_REPAIR_PROCESS.version
            or stage.stage_key
            != UNKNOWN_INCIDENT_REPAIR_PROCESS.development_stage.stage_key
        ):
            return None
        architecture = ensure_incident_repair_architecture_current(
            self._store,
            change.change_id,
            artifact_id=stage.plan_artifact_id,
        )
        revision = str(architecture.payload.get("source_revision") or "").strip().lower()
        if not revision:
            raise IncidentRepairArchitectureError(
                "approved architecture has no source revision"
            )
        return revision


class IncidentRepairSourceCompletionHandler:
    """Registered source-stage finalizer for unknown_incident_repair.v1."""

    process_key = UNKNOWN_INCIDENT_REPAIR_PROCESS.key
    process_version = UNKNOWN_INCIDENT_REPAIR_PROCESS.version

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage: ChangeStage,
        work: WorkItem,
    ) -> ChangeState | None:
        artifact = derive_incident_repair_architecture(
            self._store,
            change=change,
            stage=stage,
            work=work,
        )
        if artifact is None:
            return ChangeState.FAILED
        ensure_incident_repair_architecture_current(
            self._store,
            change.change_id,
            artifact_id=artifact.artifact_id,
        )
        return None
