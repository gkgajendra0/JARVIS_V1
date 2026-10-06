"""Cross-lifecycle invariants for capability-acquisition system hardening.

These checks intentionally sit above individual specialists.  They inspect the
canonical Goal/EngineeringChange/Work projection that the Global Supervisor sees and
reject impossible combinations even when each local component looks valid in
isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.ledgers import build_progress_ledger
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.workspace import (
    ObjectiveWorkspaceProjector,
    ObjectiveWorkspaceV1,
    WorkspaceChangeV1,
    WorkspaceWorkV1,
)


class CapabilitySystemInvariantCode(StrEnum):
    MULTIPLE_AUTHORITATIVE_STAGE_ATTEMPTS = "multiple_authoritative_stage_attempts"
    AUTHORITATIVE_STAGE_NOT_LATEST = "authoritative_stage_not_latest"
    INVALID_SUPERSESSION_DIRECTION = "invalid_supersession_direction"
    RETRYABLE_WORK_NOT_FAILED = "retryable_work_not_failed"
    RETRYING_WORK_NOT_IN_PROGRESS = "retrying_work_not_in_progress"
    FAILED_CHANGE_EXPOSES_FORWARD_PROGRESS = "failed_change_exposes_forward_progress"
    DEVELOPMENT_WITHOUT_ARCHITECTURE = "development_without_architecture"
    DEVELOPMENT_BOUND_TO_STALE_ARCHITECTURE = "development_bound_to_stale_architecture"
    DEVELOPMENT_WITHOUT_EXACT_APPROVAL = "development_without_exact_approval"
    DEVELOPMENT_MISSING_AUTHORITATIVE_SOURCE = (
        "development_missing_authoritative_source"
    )
    DEVELOPMENT_DEPENDS_ON_STALE_SOURCE = "development_depends_on_stale_source"
    GOVERNING_CHANGE_DRIFT = "governing_change_drift"
    GAP_LINK_IDENTITY_DRIFT = "gap_link_identity_drift"
    ACTIVATION_WITHOUT_ADMISSION = "activation_without_admission"
    EXTERNAL_ACCEPTANCE_WITHOUT_ACTIVATION = "external_acceptance_without_activation"
    EXTERNAL_ACCEPTANCE_WITHOUT_BINDING = "external_acceptance_without_binding"
    EXTERNAL_ACCEPTANCE_BINDING_MISMATCH = "external_acceptance_binding_mismatch"
    RESUMED_CONTINUATION_WITH_OPEN_GAP = "resumed_continuation_with_open_gap"


@dataclass(frozen=True, slots=True)
class CapabilitySystemInvariantFindingV1:
    code: CapabilitySystemInvariantCode
    detail: str
    change_id: str | None = None
    work_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "change_id": self.change_id,
            "work_id": self.work_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySystemInvariantReportV1:
    schema: str
    goal_id: str
    workspace_digest: str
    findings: tuple[CapabilitySystemInvariantFindingV1, ...]
    digest: str

    @property
    def passed(self) -> bool:
        return not self.findings

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "workspace_digest": self.workspace_digest,
            "findings": [item.to_payload() for item in self.findings],
        }

    def __post_init__(self) -> None:
        if self.schema != "capability_system_invariant_report.v1":
            raise ValueError("unsupported capability invariant report schema")
        if self.digest != "pending":
            expected = canonical_digest(self.canonical_payload())
            if self.digest != expected:
                raise ValueError("capability invariant report digest mismatch")


def _exact_architecture_approved(
    change_store: ChangeStore,
    *,
    change_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> bool:
    with change_store.work._lock, change_store.work._connect() as db:
        row = db.execute(
            """SELECT 1
            FROM engineering_change_gates AS gate
            JOIN engineering_change_decisions AS decision
              ON decision.gate_id=gate.gate_id
            WHERE gate.change_id=?
              AND gate.kind='architecture'
              AND gate.artifact_id=?
              AND gate.artifact_digest=?
              AND decision.approved=1
            LIMIT 1""",
            (change_id, artifact_id, artifact_digest),
        ).fetchone()
    return row is not None


def _work_by_id(workspace: ObjectiveWorkspaceV1) -> dict[str, WorkspaceWorkV1]:
    return {item.work_id: item for item in workspace.work_items}


def _artifact_by_id(change: WorkspaceChangeV1) -> dict[str, object]:
    return {item.artifact_id: item for item in change.artifacts}


def _linked_gap_ids(change: WorkspaceChangeV1) -> set[str]:
    return {
        str(item.payload.get("gap_id") or "").strip()
        for item in change.artifacts
        if item.kind == "gicc_capability_gap_link"
        and str(item.payload.get("gap_id") or "").strip()
    }


def _add(
    findings: list[CapabilitySystemInvariantFindingV1],
    code: CapabilitySystemInvariantCode,
    detail: str,
    *,
    change_id: str | None = None,
    work_id: str | None = None,
) -> None:
    findings.append(
        CapabilitySystemInvariantFindingV1(
            code=code,
            detail=" ".join(str(detail).split()),
            change_id=change_id,
            work_id=work_id,
        )
    )


def _check_stage_authority(
    *,
    change: WorkspaceChangeV1,
    work_by_id: dict[str, WorkspaceWorkV1],
    findings: list[CapabilitySystemInvariantFindingV1],
) -> None:
    by_key: dict[str, list[object]] = {}
    for stage in change.stages:
        by_key.setdefault(stage.stage_key, []).append(stage)

    for stage_key, stages in by_key.items():
        authoritative = [item for item in stages if item.authoritative]
        if len(authoritative) > 1:
            _add(
                findings,
                CapabilitySystemInvariantCode.MULTIPLE_AUTHORITATIVE_STAGE_ATTEMPTS,
                f"{stage_key} has {len(authoritative)} authoritative attempts",
                change_id=change.change_id,
            )
            continue
        if not authoritative:
            continue
        current = authoritative[0]
        latest_attempt = max(item.attempt for item in stages)
        if current.attempt != latest_attempt:
            _add(
                findings,
                CapabilitySystemInvariantCode.AUTHORITATIVE_STAGE_NOT_LATEST,
                (
                    f"{stage_key} authoritative attempt {current.attempt} "
                    f"is behind latest attempt {latest_attempt}"
                ),
                change_id=change.change_id,
                work_id=current.work_id,
            )

        for item in stages:
            if (
                item.superseded_by_attempt is not None
                and item.superseded_by_attempt <= item.attempt
            ):
                _add(
                    findings,
                    CapabilitySystemInvariantCode.INVALID_SUPERSESSION_DIRECTION,
                    (
                        f"{stage_key} attempt {item.attempt} is superseded by "
                        f"{item.superseded_by_attempt}"
                    ),
                    change_id=change.change_id,
                    work_id=item.work_id,
                )

    for stage in (item for item in change.stages if item.authoritative):
        work = work_by_id.get(stage.work_id)
        if work is None:
            continue
        if work.system_outcome.kind == "retryable" and work.state != "failed":
            _add(
                findings,
                CapabilitySystemInvariantCode.RETRYABLE_WORK_NOT_FAILED,
                (
                    "authoritative retryable work must remain failed until a "
                    "canonical retry transition occurs"
                ),
                change_id=change.change_id,
                work_id=work.work_id,
            )
        if work.state == "retrying" and work.system_outcome.kind != "in_progress":
            _add(
                findings,
                CapabilitySystemInvariantCode.RETRYING_WORK_NOT_IN_PROGRESS,
                "retrying work must project as in_progress",
                change_id=change.change_id,
                work_id=work.work_id,
            )


def _check_development_binding(
    *,
    change_store: ChangeStore,
    change: WorkspaceChangeV1,
    work_by_id: dict[str, WorkspaceWorkV1],
    findings: list[CapabilitySystemInvariantFindingV1],
) -> None:
    if change.state not in {
        "developing",
        "verifying",
        "waiting_owner_acceptance",
        "ready_for_promotion",
        "waiting_promotion_approval",
        "promoted",
        "observing",
        "closed",
    }:
        return

    development = [
        item
        for item in change.stages
        if item.stage_key == "development" and item.authoritative
    ]
    if not development:
        return
    stage = max(development, key=lambda item: item.attempt)
    work = work_by_id.get(stage.work_id)

    architectures = [item for item in change.artifacts if item.kind == "architecture"]
    if not architectures:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_WITHOUT_ARCHITECTURE,
            "authoritative development exists without architecture",
            change_id=change.change_id,
            work_id=stage.work_id,
        )
        return
    architecture = next(
        (
            item
            for item in architectures
            if item.artifact_id == change.current_architecture_artifact_id
        ),
        None,
    )
    if architecture is None:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_WITHOUT_ARCHITECTURE,
            "authoritative development cannot resolve the governing current architecture",
            change_id=change.change_id,
            work_id=stage.work_id,
        )
        return
    if stage.plan_artifact_id != architecture.artifact_id:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_BOUND_TO_STALE_ARCHITECTURE,
            (
                f"development attempt {stage.attempt} is bound to "
                f"{stage.plan_artifact_id!r}, current architecture is "
                f"{architecture.artifact_id}"
            ),
            change_id=change.change_id,
            work_id=stage.work_id,
        )
    if not _exact_architecture_approved(
        change_store,
        change_id=change.change_id,
        artifact_id=architecture.artifact_id,
        artifact_digest=architecture.digest,
    ):
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_WITHOUT_EXACT_APPROVAL,
            "authoritative development has no exact approval for current architecture",
            change_id=change.change_id,
            work_id=stage.work_id,
        )

    source = [
        item
        for item in change.stages
        if item.stage_key == "acquisition" and item.authoritative
    ]
    if not source:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_MISSING_AUTHORITATIVE_SOURCE,
            "authoritative development has no authoritative acquisition source",
            change_id=change.change_id,
            work_id=stage.work_id,
        )
        return
    source_stage = max(source, key=lambda item: item.attempt)
    if work is None:
        return
    stage_by_work = {item.work_id: item for item in change.stages}
    source_dependencies = [
        stage_by_work[dependency]
        for dependency in work.dependencies
        if dependency in stage_by_work
        and stage_by_work[dependency].stage_key == "acquisition"
    ]
    if source_stage.work_id not in work.dependencies:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_MISSING_AUTHORITATIVE_SOURCE,
            (
                "development dependencies do not include current authoritative "
                f"acquisition work {source_stage.work_id}"
            ),
            change_id=change.change_id,
            work_id=work.work_id,
        )
    stale = [
        item.work_id
        for item in source_dependencies
        if item.work_id != source_stage.work_id
    ]
    if stale:
        _add(
            findings,
            CapabilitySystemInvariantCode.DEVELOPMENT_DEPENDS_ON_STALE_SOURCE,
            "development still depends on superseded acquisition work: "
            + ", ".join(sorted(stale)),
            change_id=change.change_id,
            work_id=work.work_id,
        )


def _check_external_acceptance_binding(
    *,
    change: WorkspaceChangeV1,
    work_by_id: dict[str, WorkspaceWorkV1],
    findings: list[CapabilitySystemInvariantFindingV1],
) -> None:
    architecture = next(
        (
            item
            for item in change.artifacts
            if item.kind == "architecture"
            and item.artifact_id == change.current_architecture_artifact_id
        ),
        None,
    )
    contracts = (
        ()
        if architecture is None
        else tuple(architecture.payload.get("owner_acceptance_contract_ids") or ())
    )
    external_required = PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT in {
        str(item).strip().casefold() for item in contracts if str(item).strip()
    }
    if not external_required:
        return

    activations = [
        item
        for item in change.artifacts
        if item.kind == "capability_lifecycle_activation"
    ]
    bindings = [
        item
        for item in change.artifacts
        if item.kind == "capability_external_acceptance_binding"
    ]
    results = [
        item
        for item in change.artifacts
        if item.kind == "capability_external_acceptance"
    ]
    if not activations:
        return

    activation = max(
        activations,
        key=lambda item: (item.revision, item.artifact_id),
    )
    current_bindings = [
        item
        for item in bindings
        if item.payload.get("activation_artifact_id") == activation.artifact_id
        and item.payload.get("activation_artifact_digest") == activation.digest
    ]
    if not current_bindings:
        _add(
            findings,
            CapabilitySystemInvariantCode.EXTERNAL_ACCEPTANCE_WITHOUT_BINDING,
            "current capability activation has no canonical acceptance binding",
            change_id=change.change_id,
        )
        return

    binding = max(
        current_bindings,
        key=lambda item: (item.revision, item.artifact_id),
    )
    work_id = str(binding.payload.get("work_id") or "").strip()
    work = work_by_id.get(work_id)
    candidate = next(
        (
            item
            for item in reversed(change.artifacts)
            if item.kind == "capability_candidate"
        ),
        None,
    )
    if (
        work is None
        or work.work_type != "external_acceptance"
        or work.source_session_id != f"phase9-external:{change.change_id}"
        or work.source_turn_id != activation.artifact_id
        or (
            candidate is not None
            and (
                binding.payload.get("candidate_artifact_id") != candidate.artifact_id
                or binding.payload.get("candidate_artifact_digest") != candidate.digest
            )
        )
    ):
        _add(
            findings,
            CapabilitySystemInvariantCode.EXTERNAL_ACCEPTANCE_BINDING_MISMATCH,
            "current external acceptance binding/work identity is stale or inconsistent",
            change_id=change.change_id,
            work_id=work_id or None,
        )
        return

    current_results = [
        item
        for item in results
        if item.payload.get("binding_artifact_id") == binding.artifact_id
    ]
    if not current_results:
        return
    result = max(
        current_results,
        key=lambda item: (item.revision, item.artifact_id),
    )
    if (
        result.payload.get("binding_artifact_digest") != binding.digest
        or result.payload.get("work_id") != work_id
        or result.payload.get("activation_artifact_id") != activation.artifact_id
        or result.payload.get("activation_artifact_digest") != activation.digest
    ):
        _add(
            findings,
            CapabilitySystemInvariantCode.EXTERNAL_ACCEPTANCE_BINDING_MISMATCH,
            "external acceptance result does not match the current acceptance mission",
            change_id=change.change_id,
            work_id=work_id or None,
        )


def _check_lifecycle_order(
    *,
    change: WorkspaceChangeV1,
    findings: list[CapabilitySystemInvariantFindingV1],
) -> None:
    kinds = {item.kind for item in change.artifacts}
    if (
        "capability_lifecycle_activation" in kinds
        and "capability_package_admission" not in kinds
    ):
        _add(
            findings,
            CapabilitySystemInvariantCode.ACTIVATION_WITHOUT_ADMISSION,
            "capability activation exists before package admission",
            change_id=change.change_id,
        )
    if {
        "capability_external_acceptance",
        "capability_external_acceptance_binding",
    } & kinds and "capability_lifecycle_activation" not in kinds:
        _add(
            findings,
            CapabilitySystemInvariantCode.EXTERNAL_ACCEPTANCE_WITHOUT_ACTIVATION,
            "external acceptance exists before lifecycle activation",
            change_id=change.change_id,
        )


def inspect_capability_workspace_invariants(
    *,
    workspace: ObjectiveWorkspaceV1,
    change_store: ChangeStore,
) -> CapabilitySystemInvariantReportV1:
    """Inspect one already-projected workspace without mutating canonical state."""

    if not isinstance(workspace, ObjectiveWorkspaceV1):
        raise TypeError("workspace must be ObjectiveWorkspaceV1")
    if not isinstance(change_store, ChangeStore):
        raise TypeError("change_store must be ChangeStore")

    progress = build_progress_ledger(workspace)
    work_by_id = _work_by_id(workspace)
    findings: list[CapabilitySystemInvariantFindingV1] = []

    acquisition_changes = [
        item
        for item in workspace.changes
        if item.process_key == "owner_capability_acquisition"
    ]

    for change in acquisition_changes:
        _check_stage_authority(
            change=change,
            work_by_id=work_by_id,
            findings=findings,
        )
        _check_development_binding(
            change_store=change_store,
            change=change,
            work_by_id=work_by_id,
            findings=findings,
        )
        _check_lifecycle_order(change=change, findings=findings)
        _check_external_acceptance_binding(
            change=change,
            work_by_id=work_by_id,
            findings=findings,
        )

        gap_ids = _linked_gap_ids(change)
        for artifact in (
            item for item in change.artifacts if item.kind == "gicc_capability_gap_link"
        ):
            linked_goal = str(artifact.payload.get("motivating_goal_id") or "").strip()
            if linked_goal and linked_goal != workspace.goal.record_id:
                _add(
                    findings,
                    CapabilitySystemInvariantCode.GAP_LINK_IDENTITY_DRIFT,
                    (
                        f"gap link points to goal {linked_goal}, expected "
                        f"{workspace.goal.record_id}"
                    ),
                    change_id=change.change_id,
                )
        if (
            progress.active_change_id == change.change_id
            and change.state == "failed"
            and any(
                action
                in {
                    "CONTINUE",
                    "REQUEST_RESEARCH",
                    "REQUEST_ARCHITECTURE",
                    "RESUME_DEVELOPMENT",
                    "VERIFY_ASSUMPTION",
                }
                for action in progress.next_legal_actions
            )
        ):
            _add(
                findings,
                CapabilitySystemInvariantCode.FAILED_CHANGE_EXPOSES_FORWARD_PROGRESS,
                (
                    "failed governing change exposes forward-progress actions: "
                    + ", ".join(progress.next_legal_actions)
                ),
                change_id=change.change_id,
                work_id=progress.active_work_id,
            )

        if gap_ids:
            blocked = [
                item
                for item in workspace.continuations
                if str(item.payload.get("blocked_by_id") or "").strip() in gap_ids
                and str(item.payload.get("state") or "").strip() == "blocked"
            ]
            if blocked and progress.active_change_id != change.change_id:
                _add(
                    findings,
                    CapabilitySystemInvariantCode.GOVERNING_CHANGE_DRIFT,
                    (
                        "blocked capability continuation is not governed by its "
                        f"linked change {change.change_id}"
                    ),
                    change_id=change.change_id,
                )

    gap_state = {
        item.record_id: str(item.payload.get("state") or "").strip()
        for item in workspace.capability_gaps
    }
    for continuation in workspace.continuations:
        if str(continuation.payload.get("state") or "").strip() != "resumed":
            continue
        blocker_id = str(continuation.payload.get("blocked_by_id") or "").strip()
        if blocker_id and gap_state.get(blocker_id) == "open":
            _add(
                findings,
                CapabilitySystemInvariantCode.RESUMED_CONTINUATION_WITH_OPEN_GAP,
                (
                    f"continuation {continuation.record_id} resumed while gap "
                    f"{blocker_id} is still open"
                ),
            )

    report = CapabilitySystemInvariantReportV1(
        schema="capability_system_invariant_report.v1",
        goal_id=workspace.goal.record_id,
        workspace_digest=workspace.digest,
        findings=tuple(findings),
        digest="pending",
    )
    return replace(
        report,
        digest=canonical_digest(report.canonical_payload()),
    )


def inspect_capability_system_invariants(
    *,
    goal_store: GoalStore,
    change_store: ChangeStore,
    goal_id: str,
) -> CapabilitySystemInvariantReportV1:
    """Project canonical state, then inspect cross-lifecycle invariants read-only."""

    workspace = ObjectiveWorkspaceProjector(
        goal_store=goal_store,
        change_store=change_store,
    ).project(goal_id)
    return inspect_capability_workspace_invariants(
        workspace=workspace,
        change_store=change_store,
    )


def assert_capability_system_invariants(
    *,
    goal_store: GoalStore,
    change_store: ChangeStore,
    goal_id: str,
) -> CapabilitySystemInvariantReportV1:
    """Raise one compact assertion when any cross-lifecycle invariant is violated."""

    report = inspect_capability_system_invariants(
        goal_store=goal_store,
        change_store=change_store,
        goal_id=goal_id,
    )
    if report.findings:
        rendered = "; ".join(
            f"{item.code.value}: {item.detail}" for item in report.findings
        )
        raise AssertionError("capability system invariant violation(s): " + rendered)
    return report
