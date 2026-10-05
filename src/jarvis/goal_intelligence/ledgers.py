"""Stable task and live progress ledgers derived from ObjectiveWorkspaceV1."""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
)
from jarvis.engineering_substrate.canonical import canonical_digest

from .workspace import (
    ObjectiveWorkspaceV1,
    WorkspaceArtifactV1,
    WorkspaceChangeV1,
    WorkspaceWorkV1,
)


@dataclass(frozen=True, slots=True)
class LedgerFactV1:
    category: str
    statement: str
    source_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "category": self.category,
            "statement": self.statement,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class LedgerRejectionV1:
    candidate_id: str
    source_identity: str | None
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_identity": self.source_identity,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class TaskLedgerV1:
    schema: str
    goal_id: str
    goal_revision: int
    objective: str
    desired_outcome: str
    success_criteria: tuple[str, ...]
    targets: tuple[dict[str, object], ...]
    authority_boundaries: tuple[str, ...]
    current_strategy: tuple[str, ...]
    accepted_facts: tuple[LedgerFactV1, ...]
    assumptions: tuple[str, ...]
    rejected_alternatives: tuple[LedgerRejectionV1, ...]
    source_workspace_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "success_criteria": list(self.success_criteria),
            "targets": list(self.targets),
            "authority_boundaries": list(self.authority_boundaries),
            "current_strategy": list(self.current_strategy),
            "accepted_facts": [item.to_payload() for item in self.accepted_facts],
            "assumptions": list(self.assumptions),
            "rejected_alternatives": [
                item.to_payload() for item in self.rejected_alternatives
            ],
            "source_workspace_digest": self.source_workspace_digest,
        }

    def __post_init__(self) -> None:
        if self.schema != "task_ledger.v1":
            raise ValueError("unsupported TaskLedger schema")
        if (
            self.digest != "pending"
            and canonical_digest(self.canonical_payload()) != self.digest
        ):
            raise ValueError("TaskLedger digest mismatch")


@dataclass(frozen=True, slots=True)
class ProgressLedgerV1:
    schema: str
    goal_id: str
    phase: str
    active_specialist: str | None
    current_assignment_id: str | None
    current_assignment: str | None
    latest_progress: str | None
    making_progress: bool
    blocker_kind: str | None
    blocker_reason: str | None
    owner_action_required: bool
    current_plan_valid: bool
    next_legal_actions: tuple[str, ...]
    active_change_id: str | None
    active_work_id: str | None
    source_workspace_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "phase": self.phase,
            "active_specialist": self.active_specialist,
            "current_assignment_id": self.current_assignment_id,
            "current_assignment": self.current_assignment,
            "latest_progress": self.latest_progress,
            "making_progress": self.making_progress,
            "blocker_kind": self.blocker_kind,
            "blocker_reason": self.blocker_reason,
            "owner_action_required": self.owner_action_required,
            "current_plan_valid": self.current_plan_valid,
            "next_legal_actions": list(self.next_legal_actions),
            "active_change_id": self.active_change_id,
            "active_work_id": self.active_work_id,
            "source_workspace_digest": self.source_workspace_digest,
        }

    def __post_init__(self) -> None:
        if self.schema != "progress_ledger.v1":
            raise ValueError("unsupported ProgressLedger schema")
        if (
            self.digest != "pending"
            and canonical_digest(self.canonical_payload()) != self.digest
        ):
            raise ValueError("ProgressLedger digest mismatch")


_AUTHORITY_BOUNDARIES = (
    "architecture approvals remain artifact-bound",
    "promotion approvals remain artifact-bound",
    "owner-only gates cannot be self-authorized by specialists",
    "authority and policy checks cannot be bypassed by supervisor reasoning",
)


_CHANGE_PHASE = {
    "proposed": "intake",
    "researching": "research",
    "architecture_ready": "architecture",
    "waiting_owner_approval": "owner_approval",
    "approved_for_build": "development",
    "developing": "development",
    "verifying": "verification",
    "waiting_owner_acceptance": "owner_acceptance",
    "ready_for_promotion": "promotion",
    "waiting_promotion_approval": "promotion_approval",
    "promoted": "activation",
    "observing": "observation",
    "closed": "completed",
    "blocked_external": "external_blocker",
    "rejected": "terminal",
    "failed": "terminal",
    "superseded": "superseded",
    "rolled_back": "terminal",
}


_GOAL_PHASE = {
    "received": "intake",
    "resolving": "resolution",
    "waiting_information": "information",
    "requirements_ready": "requirements",
    "waiting_capability": "capability_acquisition",
    "planned": "planning",
    "executing": "execution",
    "monitoring": "monitoring",
    "verifying": "verification",
    "completed": "completed",
    "paused": "paused",
    "failed": "terminal",
    "cancelled": "terminal",
}


def _artifact_by_id(
    workspace: ObjectiveWorkspaceV1,
    artifact_id: str,
) -> WorkspaceArtifactV1 | None:
    for change in workspace.changes:
        for artifact in change.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
    return None


def _current_architecture(
    workspace: ObjectiveWorkspaceV1,
) -> WorkspaceArtifactV1 | None:
    governing = _active_change(workspace)
    if governing is not None and governing.current_architecture_artifact_id is not None:
        return next(
            (
                artifact
                for artifact in governing.artifacts
                if artifact.artifact_id == governing.current_architecture_artifact_id
                and artifact.kind == "architecture"
            ),
            None,
        )

    candidates = [
        item
        for artifact_id in workspace.current_architecture_refs
        if (item := _artifact_by_id(workspace, artifact_id)) is not None
    ]
    if not candidates:
        return None
    change_by_architecture = {
        change.current_architecture_artifact_id: change
        for change in workspace.changes
        if change.current_architecture_artifact_id is not None
    }
    return max(
        candidates,
        key=lambda item: (
            change_by_architecture[item.artifact_id].updated_at,
            item.artifact_id,
        ),
    )


def _strategy(architecture: WorkspaceArtifactV1 | None) -> tuple[str, ...]:
    if architecture is None:
        return ()
    values: list[str] = []
    for key in (
        "strategy",
        "transport",
        "target_vendor",
        "target_platform",
        "proposed_capability_id",
        "proposed_package_id",
    ):
        value = " ".join(str(architecture.payload.get(key) or "").split()).strip()
        if value:
            values.append(f"{key}:{value}")
    return tuple(values)


def _accepted_facts(
    workspace: ObjectiveWorkspaceV1,
    architecture: WorkspaceArtifactV1 | None,
) -> tuple[LedgerFactV1, ...]:
    facts: list[LedgerFactV1] = []
    for target in workspace.targets:
        name = target.canonical_name or target.entity_id or target.entity_type
        facts.append(
            LedgerFactV1(
                category="target",
                statement=f"{target.entity_type}:{name}",
                source_refs=target.source_refs,
            )
        )
    for need in workspace.information_needs:
        payload = need.payload
        if payload.get("state") != "resolved":
            continue
        resolution = str(payload.get("resolution_ref") or "").strip()
        if resolution:
            facts.append(
                LedgerFactV1(
                    category="resolved_information",
                    statement=resolution,
                    source_refs=tuple(payload.get("evidence_refs") or ()),
                )
            )
    if architecture is not None:
        facts.append(
            LedgerFactV1(
                category="current_architecture",
                statement=architecture.artifact_id,
                source_refs=(f"artifact:{architecture.artifact_id}",),
            )
        )
    return tuple(facts)


def _assumptions(workspace: ObjectiveWorkspaceV1) -> tuple[str, ...]:
    output: set[str] = set(workspace.open_questions)
    architecture = _current_architecture(workspace)
    if architecture is not None:
        raw = architecture.payload.get("assumptions", ())
        values = (raw,) if isinstance(raw, str) else raw
        if isinstance(values, (list, tuple)):
            output.update(
                " ".join(str(item).split()).strip()
                for item in values
                if str(item).strip()
            )
    return tuple(sorted(output))


def _rejections(workspace: ObjectiveWorkspaceV1) -> tuple[LedgerRejectionV1, ...]:
    output: dict[tuple[str, tuple[str, ...]], LedgerRejectionV1] = {}
    for change in workspace.changes:
        for artifact in change.artifacts:
            if artifact.kind != "acquisition_resolution":
                continue
            candidates = {
                str(item.get("candidate_id") or ""): item
                for item in artifact.payload.get("candidates", ())
                if isinstance(item, dict)
            }
            for evaluation in artifact.payload.get("evaluations", ()):
                if not isinstance(evaluation, dict):
                    continue
                if evaluation.get("disposition") != "blocked":
                    continue
                candidate_id = str(evaluation.get("candidate_id") or "").strip()
                if not candidate_id:
                    continue
                reason_codes = tuple(
                    sorted(str(item) for item in evaluation.get("reason_codes", ()))
                )
                candidate = candidates.get(candidate_id, {})
                source_identity = str(candidate.get("source_identity") or "").strip()
                item = LedgerRejectionV1(
                    candidate_id=candidate_id,
                    source_identity=source_identity or None,
                    reason_codes=reason_codes,
                )
                output[(candidate_id, reason_codes)] = item
    return tuple(
        output[key] for key in sorted(output, key=lambda item: (item[0], item[1]))
    )


def build_task_ledger(workspace: ObjectiveWorkspaceV1) -> TaskLedgerV1:
    if not isinstance(workspace, ObjectiveWorkspaceV1):
        raise TypeError("workspace must be ObjectiveWorkspaceV1")
    payload = workspace.goal.payload
    architecture = _current_architecture(workspace)
    ledger = TaskLedgerV1(
        schema="task_ledger.v1",
        goal_id=workspace.goal.record_id,
        goal_revision=int(payload.get("goal_revision") or 1),
        objective=str(payload.get("exact_owner_request") or "").strip(),
        desired_outcome=str(payload.get("desired_outcome") or "").strip(),
        success_criteria=tuple(payload.get("completion_predicates") or ()),
        targets=tuple(item.to_payload() for item in workspace.targets),
        authority_boundaries=_AUTHORITY_BOUNDARIES,
        current_strategy=_strategy(architecture),
        accepted_facts=_accepted_facts(workspace, architecture),
        assumptions=_assumptions(workspace),
        rejected_alternatives=_rejections(workspace),
        source_workspace_digest=workspace.digest,
        digest="pending",
    )
    return replace(ledger, digest=canonical_digest(ledger.canonical_payload()))


def _active_change(workspace: ObjectiveWorkspaceV1) -> WorkspaceChangeV1 | None:
    nonterminal = {
        "proposed",
        "researching",
        "architecture_ready",
        "waiting_owner_approval",
        "approved_for_build",
        "developing",
        "verifying",
        "waiting_owner_acceptance",
        "ready_for_promotion",
        "waiting_promotion_approval",
        "promoted",
        "observing",
        "blocked_external",
    }

    # A blocked continuation is the strongest operational authority signal. It binds
    # the unresolved owner objective to one exact capability gap and, through the
    # persisted GICC link, to one exact EngineeringChange. Preserve that governing
    # relationship even when the child change is FAILED/CLOSED/SUPERSEDED: terminal
    # child execution state is evidence for recovery/replan, not permission to forget
    # which engineering lifecycle owns the still-blocked objective.
    current_plan_id = None if workspace.plan is None else workspace.plan.record_id
    blocked_gap_ids = {
        str(item.payload.get("blocked_by_id") or "").strip()
        for item in workspace.continuations
        if str(item.payload.get("state") or "").strip() == "blocked"
        and str(item.payload.get("blocked_by_type") or "").strip()
        == "capability_acquisition"
        and (
            current_plan_id is None
            or str(item.payload.get("plan_id") or "").strip() == current_plan_id
        )
        and str(item.payload.get("blocked_by_id") or "").strip()
    }
    if blocked_gap_ids:
        continuation_bound = [
            change
            for change in workspace.changes
            if any(
                artifact.kind == "gicc_capability_gap_link"
                and str(artifact.payload.get("motivating_goal_id") or "").strip()
                == workspace.goal.record_id
                and str(artifact.payload.get("gap_id") or "").strip() in blocked_gap_ids
                and str(artifact.payload.get("engineering_change_id") or "").strip()
                == change.change_id
                for artifact in change.artifacts
            )
        ]
        if continuation_bound:
            return max(
                continuation_bound,
                key=lambda item: (item.updated_at, item.change_id),
            )

    candidates = [item for item in workspace.changes if item.state in nonterminal]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.updated_at, item.change_id))


def _authoritative_work(
    workspace: ObjectiveWorkspaceV1,
    change: WorkspaceChangeV1 | None,
) -> WorkspaceWorkV1 | None:
    if change is None:
        return None
    work_by_id = {item.work_id: item for item in workspace.work_items}

    # Post-activation external acceptance is durable Work owned by the capability
    # lifecycle, not an EngineeringChange stage. The exact binding artifact makes it
    # authoritative for progress while the owner objective is still blocked on this
    # capability lineage.
    external_bindings = [
        artifact
        for artifact in change.artifacts
        if artifact.kind == EXTERNAL_ACCEPTANCE_BINDING_KIND
    ]
    if external_bindings:
        binding = max(
            external_bindings,
            key=lambda artifact: (artifact.revision, artifact.artifact_id),
        )
        external_work_id = str(binding.payload.get("work_id") or "").strip()
        external_work = work_by_id.get(external_work_id)
        if external_work is not None:
            return external_work

    candidates = [
        (stage, work_by_id.get(stage.work_id))
        for stage in change.stages
        if stage.authoritative
    ]
    candidates = [(stage, work) for stage, work in candidates if work is not None]
    if not candidates:
        return None

    if change.state == "researching":
        research = [
            pair
            for pair in candidates
            if pair[1].work_type in {"research", "diagnostics"}
        ]
        if research:
            candidates = research
    elif change.state in {
        "approved_for_build",
        "developing",
        "verifying",
        "waiting_owner_acceptance",
        "ready_for_promotion",
        "waiting_promotion_approval",
        "promoted",
        "observing",
    }:
        development = [
            pair for pair in candidates if pair[1].work_type == "development"
        ]
        if development:
            candidates = development

    _, work = max(
        candidates,
        key=lambda pair: (pair[0].attempt, pair[0].stage_key),
    )
    return work


def _specialist(
    phase: str,
    work: WorkspaceWorkV1 | None,
) -> str | None:
    if work is not None:
        if work.work_type == "research":
            return "Research"
        if work.work_type == "development":
            return "DevelopmentEngine"
        if work.work_type == "diagnostics":
            return "Research"
        if work.work_type == "external_acceptance":
            return "Verification"
    return {
        "architecture": "Architecture",
        "verification": "Verification",
        "promotion": "Verification",
        "activation": "Verification",
    }.get(phase)


def _latest_progress(work: WorkspaceWorkV1 | None) -> str | None:
    if work is None:
        return None
    if work.steps:
        latest = max(
            work.steps,
            key=lambda item: (
                item.completed_at or item.started_at or item.created_at,
                item.step_id,
            ),
        )
        if latest.error:
            return latest.error
        return latest.summary
    return work.status_detail


def _blocker(
    workspace: ObjectiveWorkspaceV1,
    work: WorkspaceWorkV1 | None,
) -> tuple[str | None, str | None, bool]:
    if work is not None:
        outcome = work.system_outcome
        if outcome.kind not in {"in_progress", "completed", "superseded"}:
            return (
                outcome.kind,
                outcome.reason or work.status_detail,
                outcome.owner_action_required,
            )
    if workspace.observed_blockers:
        return "workspace_blocker", workspace.observed_blockers[0], False
    return None, None, False


def _legal_actions(
    *,
    phase: str,
    blocker_kind: str | None,
    owner_action_required: bool,
) -> tuple[str, ...]:
    if owner_action_required:
        return ("ASK_OWNER",)
    by_blocker = {
        "temporary_resource": ("WAIT_RESOURCE", "RETRY"),
        "retryable": ("RETRY",),
        "evidence_insufficient": ("REQUEST_RESEARCH",),
        "needs_research": ("REQUEST_RESEARCH",),
        "needs_architecture_revision": ("REQUEST_ARCHITECTURE",),
        "needs_dependency": ("RESUME_DEVELOPMENT",),
        "terminal": ("REPLAN", "TERMINAL"),
    }
    if blocker_kind in by_blocker:
        return by_blocker[blocker_kind]
    by_phase = {
        "intake": ("CONTINUE",),
        "resolution": ("CONTINUE",),
        "information": ("CONTINUE", "ASK_OWNER"),
        "requirements": ("CONTINUE",),
        "capability_acquisition": ("CONTINUE",),
        "research": ("CONTINUE", "REQUEST_RESEARCH"),
        "architecture": ("CONTINUE", "ASK_OWNER"),
        "owner_approval": ("ASK_OWNER",),
        "development": ("RESUME_DEVELOPMENT",),
        "verification": ("VERIFY_ASSUMPTION",),
        "owner_acceptance": ("ASK_OWNER",),
        "promotion": ("CONTINUE",),
        "promotion_approval": ("ASK_OWNER",),
        "activation": ("CONTINUE",),
        "observation": ("CONTINUE",),
        "external_blocker": ("WAIT_RESOURCE",),
        "superseded": ("CONTINUE",),
        "terminal": ("REPLAN", "TERMINAL"),
        "completed": ("CONTINUE",),
    }
    return by_phase.get(phase, ("CONTINUE",))


def build_progress_ledger(workspace: ObjectiveWorkspaceV1) -> ProgressLedgerV1:
    if not isinstance(workspace, ObjectiveWorkspaceV1):
        raise TypeError("workspace must be ObjectiveWorkspaceV1")
    goal_payload = workspace.goal.payload
    change = _active_change(workspace)
    phase = (
        _CHANGE_PHASE.get(change.state, change.state)
        if change is not None
        else _GOAL_PHASE.get(
            str(goal_payload.get("state") or ""),
            str(goal_payload.get("state") or "unknown"),
        )
    )
    work = _authoritative_work(workspace, change)
    blocker_kind, blocker_reason, outcome_owner_action = _blocker(workspace, work)
    owner_gate = bool(
        change is not None
        and change.state
        in {
            "waiting_owner_approval",
            "waiting_owner_acceptance",
            "waiting_promotion_approval",
        }
    )
    owner_action_required = outcome_owner_action or owner_gate
    terminal_work = bool(work is not None and work.system_outcome.terminal)
    terminal_change = bool(
        change is not None and change.state in {"failed", "rejected", "rolled_back"}
    )
    making_progress = bool(
        work is not None
        and work.state in {"running", "retrying", "completed"}
        and blocker_kind is None
    )
    ledger = ProgressLedgerV1(
        schema="progress_ledger.v1",
        goal_id=workspace.goal.record_id,
        phase=phase,
        active_specialist=_specialist(phase, work),
        current_assignment_id=None if work is None else work.work_id,
        current_assignment=(
            None
            if work is None
            else work.status_detail
            or next(
                (step.summary for step in reversed(work.steps) if step.summary.strip()),
                None,
            )
        ),
        latest_progress=_latest_progress(work),
        making_progress=making_progress,
        blocker_kind=blocker_kind,
        blocker_reason=blocker_reason,
        owner_action_required=owner_action_required,
        current_plan_valid=not (terminal_work or terminal_change),
        next_legal_actions=_legal_actions(
            phase=phase,
            blocker_kind=blocker_kind,
            owner_action_required=owner_action_required,
        ),
        active_change_id=None if change is None else change.change_id,
        active_work_id=None if work is None else work.work_id,
        source_workspace_digest=workspace.digest,
        digest="pending",
    )
    return replace(ledger, digest=canonical_digest(ledger.canonical_payload()))
