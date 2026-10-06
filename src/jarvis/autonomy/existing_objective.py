"""Fail-closed resume of an existing owner objective.

This layer exists for S13 acceptance and operational recovery. It never creates a
Goal, CapabilityGap, EngineeringChange, WorkItem or approval. It proves that the
requested identifiers already belong to one canonical ObjectiveWorkspace before the
Global Supervisor is allowed to coordinate that lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.engineering_change.gates import GateService
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.ledgers import build_progress_ledger, build_task_ledger
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceProjector

from .supervisor_cutover import (
    SupervisorCutoverController,
    SupervisorCutoverResultV1,
)


class ExistingObjectiveLineageError(RuntimeError):
    """Requested resume identifiers do not match canonical existing lineage."""


class ExistingObjectiveResumeDisposition(StrEnum):
    ACTIVE_CURRENT = "active_current"
    STARTUP_RECOVERY_REQUIRED = "startup_recovery_required"
    CAPABILITY_COMPLETE = "capability_complete"
    FAILED_GOVERNING_CHANGE = "failed_governing_change"
    INACTIVE_LINKED_CHANGE = "inactive_linked_change"
    LINEAGE_CONFLICT = "lineage_conflict"


@dataclass(frozen=True, slots=True)
class ExistingObjectiveLineageV1:
    goal_id: str
    gap_id: str
    change_id: str
    historical_architecture_artifact_id: str | None = None
    historical_gate_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("goal_id", "gap_id", "change_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        for name in (
            "historical_architecture_artifact_id",
            "historical_gate_id",
        ):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class ExistingObjectiveResumeSnapshotV1:
    schema: str
    goal_id: str
    gap_id: str
    change_id: str
    owner_request: str
    desired_outcome: str
    target_names: tuple[str, ...]
    capability_families: tuple[str, ...]
    goal_state: str
    gap_state: str
    change_state: str
    progress_active_change_id: str | None
    requested_change_is_progress_active: bool
    resume_disposition: ExistingObjectiveResumeDisposition
    startup_recovery_kinds: tuple[str, ...]
    capability_completion_ready: bool
    capability_completion_error: str | None
    continuation_refs: tuple[str, ...]
    current_architecture_artifact_id: str | None
    current_architecture_digest: str | None
    current_gate_ids: tuple[str, ...]
    current_phase: str
    next_legal_actions: tuple[str, ...]
    active_work_id: str | None
    task_ledger_digest: str
    progress_ledger_digest: str
    workspace_digest: str
    lineage_link_artifact_id: str
    historical_architecture_verified: bool
    historical_gate_verified: bool
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "gap_id": self.gap_id,
            "change_id": self.change_id,
            "owner_request": self.owner_request,
            "desired_outcome": self.desired_outcome,
            "target_names": list(self.target_names),
            "capability_families": list(self.capability_families),
            "goal_state": self.goal_state,
            "gap_state": self.gap_state,
            "change_state": self.change_state,
            "progress_active_change_id": self.progress_active_change_id,
            "requested_change_is_progress_active": self.requested_change_is_progress_active,
            "resume_disposition": self.resume_disposition.value,
            "startup_recovery_kinds": list(self.startup_recovery_kinds),
            "capability_completion_ready": self.capability_completion_ready,
            "capability_completion_error": self.capability_completion_error,
            "continuation_refs": list(self.continuation_refs),
            "current_architecture_artifact_id": self.current_architecture_artifact_id,
            "current_architecture_digest": self.current_architecture_digest,
            "current_gate_ids": list(self.current_gate_ids),
            "current_phase": self.current_phase,
            "next_legal_actions": list(self.next_legal_actions),
            "active_work_id": self.active_work_id,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
            "workspace_digest": self.workspace_digest,
            "lineage_link_artifact_id": self.lineage_link_artifact_id,
            "historical_architecture_verified": self.historical_architecture_verified,
            "historical_gate_verified": self.historical_gate_verified,
        }

    def __post_init__(self) -> None:
        if self.schema != "existing_objective_resume_snapshot.v1":
            raise ValueError("unsupported existing-objective resume snapshot schema")
        if not isinstance(self.resume_disposition, ExistingObjectiveResumeDisposition):
            raise TypeError(
                "resume_disposition must be ExistingObjectiveResumeDisposition"
            )
        if (
            self.digest != "pending"
            and canonical_digest(self.canonical_payload()) != self.digest
        ):
            raise ValueError("existing-objective resume snapshot digest mismatch")


class ExistingObjectiveResumeController:
    """Prove exact lineage, then delegate one step to controlled Supervisor cutover."""

    def __init__(
        self,
        *,
        projector: ObjectiveWorkspaceProjector,
        change_store: ChangeStore,
        cutover: SupervisorCutoverController,
    ) -> None:
        if not isinstance(projector, ObjectiveWorkspaceProjector):
            raise TypeError("projector must be ObjectiveWorkspaceProjector")
        if not isinstance(change_store, ChangeStore):
            raise TypeError("change_store must be ChangeStore")
        if not isinstance(cutover, SupervisorCutoverController):
            raise TypeError("cutover must be SupervisorCutoverController")
        self._projector = projector
        self._changes = change_store
        self._cutover = cutover

    def inspect(
        self,
        lineage: ExistingObjectiveLineageV1,
    ) -> ExistingObjectiveResumeSnapshotV1:
        if not isinstance(lineage, ExistingObjectiveLineageV1):
            raise TypeError("lineage must be ExistingObjectiveLineageV1")

        workspace = self._projector.project(lineage.goal_id)
        if workspace.goal.record_id != lineage.goal_id:
            raise ExistingObjectiveLineageError(
                "goal identity changed during projection"
            )

        gap = next(
            (
                item
                for item in workspace.capability_gaps
                if item.record_id == lineage.gap_id
            ),
            None,
        )
        if gap is None:
            raise ExistingObjectiveLineageError(
                "requested capability gap does not belong to existing goal"
            )

        change = next(
            (item for item in workspace.changes if item.change_id == lineage.change_id),
            None,
        )
        if change is None:
            raise ExistingObjectiveLineageError(
                "requested EngineeringChange does not belong to existing goal"
            )

        link = next(
            (
                artifact
                for artifact in change.artifacts
                if artifact.kind == "gicc_capability_gap_link"
                and str(artifact.payload.get("motivating_goal_id") or "").strip()
                == lineage.goal_id
                and str(artifact.payload.get("gap_id") or "").strip() == lineage.gap_id
                and str(artifact.payload.get("engineering_change_id") or "").strip()
                == lineage.change_id
            ),
            None,
        )
        if link is None:
            raise ExistingObjectiveLineageError(
                "goal/gap/change canonical lineage link is missing or mismatched"
            )

        historical_architecture_verified = (
            lineage.historical_architecture_artifact_id is None
        )
        if lineage.historical_architecture_artifact_id is not None:
            historical_architecture_verified = any(
                artifact.kind == "architecture"
                and artifact.artifact_id == lineage.historical_architecture_artifact_id
                for artifact in change.artifacts
            )
            if not historical_architecture_verified:
                raise ExistingObjectiveLineageError(
                    "historical architecture anchor is not part of this change"
                )

        historical_gate_verified = lineage.historical_gate_id is None
        if lineage.historical_gate_id is not None:
            gate = GateService(
                self._changes,
                verify_owner=lambda *_: False,
            ).get(lineage.historical_gate_id)
            challenge = None if gate is None else getattr(gate, "challenge", gate)
            historical_gate_verified = bool(
                challenge is not None and challenge.change_id == lineage.change_id
            )
            if not historical_gate_verified:
                raise ExistingObjectiveLineageError(
                    "historical approval gate anchor is not part of this change"
                )

        task = build_task_ledger(workspace)
        progress = build_progress_ledger(workspace)

        startup_recovery_kinds: list[str] = []
        if (
            lineage.change_id
            in self._changes.reopen_recoverable_architecture_revision_failures(
                recovery_generation="phase9-research-provider-sdk-v1",
                dry_run=True,
            )
        ):
            startup_recovery_kinds.append("phase9-research-provider-sdk-v1")
        if (
            lineage.change_id
            in self._changes.reopen_recoverable_provisional_candidate_resolution_failures(
                recovery_generation="phase9-provisional-candidate-resolution-v1",
                dry_run=True,
            )
        ):
            startup_recovery_kinds.append(
                "phase9-provisional-candidate-resolution-v1"
            )
        if (
            lineage.change_id
            in self._changes.reopen_recoverable_development_engine_failures(
                recovery_generation="codex-contract-repair-v1",
                dry_run=True,
            )
        ):
            startup_recovery_kinds.append("codex-contract-repair-v1")
        if (
            lineage.change_id
            in self._changes.reopen_recoverable_superseded_dependency_failures(
                recovery_generation="phase9-authoritative-source-dependency-v1",
                dry_run=True,
            )
        ):
            startup_recovery_kinds.append("phase9-authoritative-source-dependency-v1")

        capability_completion_ready = False
        capability_completion_error: str | None = None
        try:
            capability_completion_ready = (
                verify_capability_acquisition_completion(
                    self._changes,
                    change_id=lineage.change_id,
                    motivating_goal_id=lineage.goal_id,
                    gap_id=lineage.gap_id,
                )
                is not None
            )
        except CapabilityAcquisitionLineageError as exc:
            capability_completion_error = str(exc)

        requested_is_active = progress.active_change_id == lineage.change_id
        if capability_completion_error is not None:
            resume_disposition = ExistingObjectiveResumeDisposition.LINEAGE_CONFLICT
        elif capability_completion_ready:
            resume_disposition = ExistingObjectiveResumeDisposition.CAPABILITY_COMPLETE
        elif startup_recovery_kinds:
            resume_disposition = (
                ExistingObjectiveResumeDisposition.STARTUP_RECOVERY_REQUIRED
            )
        elif requested_is_active and change.state == "failed":
            resume_disposition = (
                ExistingObjectiveResumeDisposition.FAILED_GOVERNING_CHANGE
            )
        elif requested_is_active:
            resume_disposition = ExistingObjectiveResumeDisposition.ACTIVE_CURRENT
        else:
            resume_disposition = (
                ExistingObjectiveResumeDisposition.INACTIVE_LINKED_CHANGE
            )

        current_plan_id = None if workspace.plan is None else workspace.plan.record_id
        continuation_refs = tuple(
            sorted(
                (
                    f"{item.record_id}|"
                    f"{item.payload.get('state')}|"
                    f"{item.payload.get('blocked_by_type')}|"
                    f"{item.payload.get('blocked_by_id')}|"
                    f"{item.payload.get('plan_id')}"
                )
                for item in workspace.continuations
                if current_plan_id is None
                or str(item.payload.get("plan_id") or "").strip() == current_plan_id
            )
        )

        architecture = next(
            (
                artifact
                for artifact in change.artifacts
                if artifact.artifact_id == change.current_architecture_artifact_id
                and artifact.kind == "architecture"
            ),
            None,
        )
        pending_gates = GateService(
            self._changes,
            verify_owner=lambda *_: False,
        )
        current_gate_ids = tuple(
            gate_id
            for gate_id in pending_gates.pending_gate_ids()
            if (
                (gate := pending_gates.get(gate_id)) is not None
                and getattr(gate, "challenge", gate).change_id == lineage.change_id
            )
        )

        payload = workspace.goal.payload
        snapshot = ExistingObjectiveResumeSnapshotV1(
            schema="existing_objective_resume_snapshot.v1",
            goal_id=lineage.goal_id,
            gap_id=lineage.gap_id,
            change_id=lineage.change_id,
            owner_request=str(payload.get("exact_owner_request") or "").strip(),
            desired_outcome=str(payload.get("desired_outcome") or "").strip(),
            target_names=tuple(
                sorted(
                    {
                        str(
                            target.canonical_name
                            or target.entity_id
                            or target.target_key
                        ).strip()
                        for target in workspace.targets
                    }
                )
            ),
            capability_families=tuple(
                sorted(
                    {
                        str(
                            item.payload.get("reusable_capability_family") or ""
                        ).strip()
                        for item in workspace.capability_gaps
                        if str(
                            item.payload.get("reusable_capability_family") or ""
                        ).strip()
                    }
                )
            ),
            goal_state=str(payload.get("state") or "").strip(),
            gap_state=str(gap.payload.get("state") or "").strip(),
            change_state=change.state,
            progress_active_change_id=progress.active_change_id,
            requested_change_is_progress_active=requested_is_active,
            resume_disposition=resume_disposition,
            startup_recovery_kinds=tuple(startup_recovery_kinds),
            capability_completion_ready=capability_completion_ready,
            capability_completion_error=capability_completion_error,
            continuation_refs=continuation_refs,
            current_architecture_artifact_id=(
                None if architecture is None else architecture.artifact_id
            ),
            current_architecture_digest=(
                None if architecture is None else architecture.digest
            ),
            current_gate_ids=current_gate_ids,
            current_phase=progress.phase,
            next_legal_actions=progress.next_legal_actions,
            active_work_id=progress.active_work_id,
            task_ledger_digest=task.digest,
            progress_ledger_digest=progress.digest,
            workspace_digest=workspace.digest,
            lineage_link_artifact_id=link.artifact_id,
            historical_architecture_verified=historical_architecture_verified,
            historical_gate_verified=historical_gate_verified,
            digest="pending",
        )
        return replace(
            snapshot,
            digest=canonical_digest(snapshot.canonical_payload()),
        )

    def coordinate_once(
        self,
        lineage: ExistingObjectiveLineageV1,
    ) -> tuple[ExistingObjectiveResumeSnapshotV1, SupervisorCutoverResultV1]:
        before = self.inspect(lineage)
        if before.resume_disposition in {
            ExistingObjectiveResumeDisposition.INACTIVE_LINKED_CHANGE,
            ExistingObjectiveResumeDisposition.LINEAGE_CONFLICT,
        }:
            raise ExistingObjectiveLineageError(
                "existing objective lineage is valid but not safe for Supervisor cutover: "
                + before.resume_disposition.value
            )
        result = self._cutover.coordinate(lineage.goal_id)
        # Re-run the exact lineage proof after coordination. Any accidental creation,
        # retargeting or active-change drift fails closed immediately.
        self.inspect(lineage)
        return before, result
