"""Role-bounded specialist context projections over ObjectiveWorkspaceV1.

These projections are read-only. They do not create specialist-owned memory or new
authority. Every context is digest-bound to one ObjectiveWorkspace and its Task/Progress
Ledgers so stale context can be rejected deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.engineering_substrate.canonical import canonical_digest

from .ledgers import (
    LedgerFactV1,
    LedgerRejectionV1,
    ProgressLedgerV1,
    TaskLedgerV1,
    build_progress_ledger,
    build_task_ledger,
)
from .workspace import (
    ObjectiveWorkspaceV1,
    WorkspaceArtifactV1,
    WorkspaceChangeV1,
    WorkspaceWorkV1,
)


@dataclass(frozen=True, slots=True)
class SpecialistArtifactRefV1:
    artifact_id: str
    kind: str
    revision: int
    digest: str
    payload: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "revision": self.revision,
            "digest": self.digest,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class SpecialistWorkRefV1:
    work_id: str
    work_type: str
    state: str
    dependencies: tuple[str, ...]
    status_detail: str | None
    system_outcome_kind: str
    terminal: bool
    owner_action_required: bool
    latest_step_kind: str | None
    latest_step_summary: str | None
    evidence_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "work_id": self.work_id,
            "work_type": self.work_type,
            "state": self.state,
            "dependencies": list(self.dependencies),
            "status_detail": self.status_detail,
            "system_outcome_kind": self.system_outcome_kind,
            "terminal": self.terminal,
            "owner_action_required": self.owner_action_required,
            "latest_step_kind": self.latest_step_kind,
            "latest_step_summary": self.latest_step_summary,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class ResearchContextV1:
    schema: str
    goal_id: str
    objective: str
    desired_outcome: str
    targets: tuple[dict[str, object], ...]
    bounded_questions: tuple[str, ...]
    accepted_facts: tuple[LedgerFactV1, ...]
    assumptions: tuple[str, ...]
    rejected_alternatives: tuple[LedgerRejectionV1, ...]
    current_architecture: SpecialistArtifactRefV1 | None
    current_assignment: SpecialistWorkRefV1 | None
    superseded_work_ids: tuple[str, ...]
    source_workspace_digest: str
    task_ledger_digest: str
    progress_ledger_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "targets": list(self.targets),
            "bounded_questions": list(self.bounded_questions),
            "accepted_facts": [item.to_payload() for item in self.accepted_facts],
            "assumptions": list(self.assumptions),
            "rejected_alternatives": [
                item.to_payload() for item in self.rejected_alternatives
            ],
            "current_architecture": (
                None
                if self.current_architecture is None
                else self.current_architecture.to_payload()
            ),
            "current_assignment": (
                None
                if self.current_assignment is None
                else self.current_assignment.to_payload()
            ),
            "superseded_work_ids": list(self.superseded_work_ids),
            "source_workspace_digest": self.source_workspace_digest,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
        }

    def __post_init__(self) -> None:
        _validate_context_digest(
            schema=self.schema,
            expected_schema="research_context.v1",
            payload=self.canonical_payload(),
            digest=self.digest,
        )


@dataclass(frozen=True, slots=True)
class ArchitectureContextV1:
    schema: str
    goal_id: str
    objective: str
    desired_outcome: str
    success_criteria: tuple[str, ...]
    targets: tuple[dict[str, object], ...]
    accepted_facts: tuple[LedgerFactV1, ...]
    assumptions: tuple[str, ...]
    rejected_alternatives: tuple[LedgerRejectionV1, ...]
    research_assignment: SpecialistWorkRefV1 | None
    research_evidence_refs: tuple[str, ...]
    current_architecture: SpecialistArtifactRefV1 | None
    superseded_work_ids: tuple[str, ...]
    source_workspace_digest: str
    task_ledger_digest: str
    progress_ledger_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "success_criteria": list(self.success_criteria),
            "targets": list(self.targets),
            "accepted_facts": [item.to_payload() for item in self.accepted_facts],
            "assumptions": list(self.assumptions),
            "rejected_alternatives": [
                item.to_payload() for item in self.rejected_alternatives
            ],
            "research_assignment": (
                None
                if self.research_assignment is None
                else self.research_assignment.to_payload()
            ),
            "research_evidence_refs": list(self.research_evidence_refs),
            "current_architecture": (
                None
                if self.current_architecture is None
                else self.current_architecture.to_payload()
            ),
            "superseded_work_ids": list(self.superseded_work_ids),
            "source_workspace_digest": self.source_workspace_digest,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
        }

    def __post_init__(self) -> None:
        _validate_context_digest(
            schema=self.schema,
            expected_schema="architecture_context.v1",
            payload=self.canonical_payload(),
            digest=self.digest,
        )


@dataclass(frozen=True, slots=True)
class DevelopmentContextV1:
    schema: str
    goal_id: str
    objective: str
    desired_outcome: str
    success_criteria: tuple[str, ...]
    targets: tuple[dict[str, object], ...]
    accepted_facts: tuple[LedgerFactV1, ...]
    approved_architecture: SpecialistArtifactRefV1 | None
    current_assignment: SpecialistWorkRefV1 | None
    authoritative_dependency_ids: tuple[str, ...]
    research_evidence_refs: tuple[str, ...]
    rejected_alternatives: tuple[LedgerRejectionV1, ...]
    superseded_work_ids: tuple[str, ...]
    source_workspace_digest: str
    task_ledger_digest: str
    progress_ledger_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "success_criteria": list(self.success_criteria),
            "targets": list(self.targets),
            "accepted_facts": [item.to_payload() for item in self.accepted_facts],
            "approved_architecture": (
                None
                if self.approved_architecture is None
                else self.approved_architecture.to_payload()
            ),
            "current_assignment": (
                None
                if self.current_assignment is None
                else self.current_assignment.to_payload()
            ),
            "authoritative_dependency_ids": list(self.authoritative_dependency_ids),
            "research_evidence_refs": list(self.research_evidence_refs),
            "rejected_alternatives": [
                item.to_payload() for item in self.rejected_alternatives
            ],
            "superseded_work_ids": list(self.superseded_work_ids),
            "source_workspace_digest": self.source_workspace_digest,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
        }

    def __post_init__(self) -> None:
        _validate_context_digest(
            schema=self.schema,
            expected_schema="development_context.v1",
            payload=self.canonical_payload(),
            digest=self.digest,
        )


@dataclass(frozen=True, slots=True)
class VerificationContextV1:
    schema: str
    goal_id: str
    objective: str
    desired_outcome: str
    success_criteria: tuple[str, ...]
    targets: tuple[dict[str, object], ...]
    accepted_facts: tuple[LedgerFactV1, ...]
    approved_architecture: SpecialistArtifactRefV1 | None
    development_assignment: SpecialistWorkRefV1 | None
    development_result: dict[str, object]
    verification_evidence_refs: tuple[str, ...]
    superseded_work_ids: tuple[str, ...]
    source_workspace_digest: str
    task_ledger_digest: str
    progress_ledger_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "success_criteria": list(self.success_criteria),
            "targets": list(self.targets),
            "accepted_facts": [item.to_payload() for item in self.accepted_facts],
            "approved_architecture": (
                None
                if self.approved_architecture is None
                else self.approved_architecture.to_payload()
            ),
            "development_assignment": (
                None
                if self.development_assignment is None
                else self.development_assignment.to_payload()
            ),
            "development_result": self.development_result,
            "verification_evidence_refs": list(self.verification_evidence_refs),
            "superseded_work_ids": list(self.superseded_work_ids),
            "source_workspace_digest": self.source_workspace_digest,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
        }

    def __post_init__(self) -> None:
        _validate_context_digest(
            schema=self.schema,
            expected_schema="verification_context.v1",
            payload=self.canonical_payload(),
            digest=self.digest,
        )


def _validate_context_digest(
    *,
    schema: str,
    expected_schema: str,
    payload: dict[str, object],
    digest: str,
) -> None:
    if schema != expected_schema:
        raise ValueError(f"unsupported specialist context schema: {schema}")
    if digest != "pending" and canonical_digest(payload) != digest:
        raise ValueError("specialist context digest mismatch")


def _current_change(workspace: ObjectiveWorkspaceV1) -> WorkspaceChangeV1 | None:
    active = [
        change
        for change in workspace.changes
        if change.state
        not in {
            "closed",
            "rejected",
            "failed",
            "superseded",
            "rolled_back",
        }
    ]
    if not active:
        return None
    return max(active, key=lambda item: (item.updated_at, item.change_id))


def _work_by_type(
    workspace: ObjectiveWorkspaceV1,
    *,
    work_type: str,
) -> WorkspaceWorkV1 | None:
    change = _current_change(workspace)
    if change is None:
        return None
    by_id = {item.work_id: item for item in workspace.work_items}
    candidates = [
        (stage.attempt, stage.stage_key, by_id.get(stage.work_id))
        for stage in change.stages
        if stage.authoritative
        and by_id.get(stage.work_id) is not None
        and by_id[stage.work_id].work_type == work_type
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _specialist_work_ref(work: WorkspaceWorkV1 | None) -> SpecialistWorkRefV1 | None:
    if work is None:
        return None
    latest = None
    if work.steps:
        latest = max(
            work.steps,
            key=lambda item: (
                item.completed_at or item.started_at or item.created_at,
                item.step_id,
            ),
        )
    return SpecialistWorkRefV1(
        work_id=work.work_id,
        work_type=work.work_type,
        state=work.state,
        dependencies=work.dependencies,
        status_detail=work.status_detail,
        system_outcome_kind=work.system_outcome.kind,
        terminal=work.system_outcome.terminal,
        owner_action_required=work.system_outcome.owner_action_required,
        latest_step_kind=None if latest is None else latest.kind,
        latest_step_summary=None if latest is None else latest.summary,
        evidence_refs=work.system_outcome.evidence_refs,
    )


def _current_architecture(
    workspace: ObjectiveWorkspaceV1,
) -> SpecialistArtifactRefV1 | None:
    refs = set(workspace.current_architecture_refs)
    candidates: list[WorkspaceArtifactV1] = []
    for change in workspace.changes:
        candidates.extend(
            artifact
            for artifact in change.artifacts
            if artifact.artifact_id in refs and artifact.kind == "architecture"
        )
    if not candidates:
        return None
    artifact = max(candidates, key=lambda item: (item.revision, item.artifact_id))
    return SpecialistArtifactRefV1(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        revision=artifact.revision,
        digest=artifact.digest,
        payload=dict(artifact.payload),
    )


_ARCHITECTURE_APPROVED_STATES = frozenset(
    {
        "approved_for_build",
        "developing",
        "verifying",
        "waiting_owner_acceptance",
        "ready_for_promotion",
        "waiting_promotion_approval",
        "promoted",
        "observing",
        "closed",
    }
)


def _approved_architecture(
    workspace: ObjectiveWorkspaceV1,
) -> SpecialistArtifactRefV1 | None:
    change = _current_change(workspace)
    if change is None or change.state not in _ARCHITECTURE_APPROVED_STATES:
        return None
    return _current_architecture(workspace)


def _superseded_work_ids(workspace: ObjectiveWorkspaceV1) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                stage.work_id
                for change in workspace.changes
                for stage in change.stages
                if not stage.authoritative
            }
        )
    )


def _evidence_refs(work: WorkspaceWorkV1 | None) -> tuple[str, ...]:
    if work is None:
        return ()
    refs = set(work.system_outcome.evidence_refs)
    for step in work.steps:
        if step.state == "completed":
            refs.add(f"work_step:{step.step_id}")
    return tuple(sorted(refs))


def _task_progress(
    workspace: ObjectiveWorkspaceV1,
) -> tuple[TaskLedgerV1, ProgressLedgerV1]:
    if not isinstance(workspace, ObjectiveWorkspaceV1):
        raise TypeError("workspace must be ObjectiveWorkspaceV1")
    return build_task_ledger(workspace), build_progress_ledger(workspace)


def _finish(context):
    return replace(context, digest=canonical_digest(context.canonical_payload()))


def build_research_context(workspace: ObjectiveWorkspaceV1) -> ResearchContextV1:
    task, progress = _task_progress(workspace)
    work = _work_by_type(workspace, work_type="research")
    questions = set(workspace.open_questions)
    if (
        progress.blocker_kind in {"evidence_insufficient", "needs_research"}
        and progress.blocker_reason
    ):
        questions.add(progress.blocker_reason)
    context = ResearchContextV1(
        schema="research_context.v1",
        goal_id=task.goal_id,
        objective=task.objective,
        desired_outcome=task.desired_outcome,
        targets=task.targets,
        bounded_questions=tuple(sorted(questions)),
        accepted_facts=task.accepted_facts,
        assumptions=task.assumptions,
        rejected_alternatives=task.rejected_alternatives,
        current_architecture=_current_architecture(workspace),
        current_assignment=_specialist_work_ref(work),
        superseded_work_ids=_superseded_work_ids(workspace),
        source_workspace_digest=workspace.digest,
        task_ledger_digest=task.digest,
        progress_ledger_digest=progress.digest,
        digest="pending",
    )
    return _finish(context)


def build_architecture_context(
    workspace: ObjectiveWorkspaceV1,
) -> ArchitectureContextV1:
    task, progress = _task_progress(workspace)
    research = _work_by_type(workspace, work_type="research")
    context = ArchitectureContextV1(
        schema="architecture_context.v1",
        goal_id=task.goal_id,
        objective=task.objective,
        desired_outcome=task.desired_outcome,
        success_criteria=task.success_criteria,
        targets=task.targets,
        accepted_facts=task.accepted_facts,
        assumptions=task.assumptions,
        rejected_alternatives=task.rejected_alternatives,
        research_assignment=_specialist_work_ref(research),
        research_evidence_refs=_evidence_refs(research),
        current_architecture=_current_architecture(workspace),
        superseded_work_ids=_superseded_work_ids(workspace),
        source_workspace_digest=workspace.digest,
        task_ledger_digest=task.digest,
        progress_ledger_digest=progress.digest,
        digest="pending",
    )
    return _finish(context)


def build_development_context(
    workspace: ObjectiveWorkspaceV1,
) -> DevelopmentContextV1:
    task, progress = _task_progress(workspace)
    research = _work_by_type(workspace, work_type="research")
    development = _work_by_type(workspace, work_type="development")
    development_ref = _specialist_work_ref(development)
    context = DevelopmentContextV1(
        schema="development_context.v1",
        goal_id=task.goal_id,
        objective=task.objective,
        desired_outcome=task.desired_outcome,
        success_criteria=task.success_criteria,
        targets=task.targets,
        accepted_facts=task.accepted_facts,
        approved_architecture=_approved_architecture(workspace),
        current_assignment=development_ref,
        authoritative_dependency_ids=(
            () if development_ref is None else development_ref.dependencies
        ),
        research_evidence_refs=_evidence_refs(research),
        rejected_alternatives=task.rejected_alternatives,
        superseded_work_ids=_superseded_work_ids(workspace),
        source_workspace_digest=workspace.digest,
        task_ledger_digest=task.digest,
        progress_ledger_digest=progress.digest,
        digest="pending",
    )
    return _finish(context)


def build_verification_context(
    workspace: ObjectiveWorkspaceV1,
) -> VerificationContextV1:
    task, progress = _task_progress(workspace)
    development = _work_by_type(workspace, work_type="development")
    context = VerificationContextV1(
        schema="verification_context.v1",
        goal_id=task.goal_id,
        objective=task.objective,
        desired_outcome=task.desired_outcome,
        success_criteria=task.success_criteria,
        targets=task.targets,
        accepted_facts=task.accepted_facts,
        approved_architecture=_current_architecture(workspace),
        development_assignment=_specialist_work_ref(development),
        development_result={} if development is None else dict(development.result),
        verification_evidence_refs=_evidence_refs(development),
        superseded_work_ids=_superseded_work_ids(workspace),
        source_workspace_digest=workspace.digest,
        task_ledger_digest=task.digest,
        progress_ledger_digest=progress.digest,
        digest="pending",
    )
    return _finish(context)
