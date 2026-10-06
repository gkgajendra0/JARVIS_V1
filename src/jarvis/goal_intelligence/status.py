"""Canonical read-only owner-objective status projection.

Goal Intelligence owns owner-outcome truth. Work, EngineeringChange, capability
lifecycle, and external acceptance remain canonical for their own subdomains. This
module joins those durable facts through persisted lineage IDs so conversational
surfaces never infer overall completion from one child subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
    EXTERNAL_ACCEPTANCE_RESULT_KIND,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.engineering_change.gates import GateService
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.goal_intelligence.models import (
    ContinuationBlockerType,
    ContinuationState,
    GoalState,
    InformationNeedState,
)
from jarvis.goal_intelligence.store import GoalStore


class ObjectiveOverallState(str, Enum):
    ACTIVE = "active"
    WAITING_OWNER = "waiting_owner"
    WAITING_EXTERNAL = "waiting_external"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObjectivePhase(str, Enum):
    RECEIVED = "received"
    RESOLVING = "resolving"
    WAITING_INFORMATION = "waiting_information"
    REQUIREMENTS_READY = "requirements_ready"
    ACQUIRING_CAPABILITY = "acquiring_capability"
    ARCHITECTURE_READY = "architecture_ready"
    WAITING_OWNER_APPROVAL = "waiting_owner_approval"
    READY_FOR_BUILD = "ready_for_build"
    DEVELOPING = "developing"
    ENGINEERING_VERIFYING = "engineering_verifying"
    WAITING_OWNER_ACCEPTANCE = "waiting_owner_acceptance"
    READY_FOR_PROMOTION = "ready_for_promotion"
    WAITING_PROMOTION_APPROVAL = "waiting_promotion_approval"
    PROMOTED = "promoted"
    OBSERVING = "observing"
    WAITING_ACTIVATION = "waiting_activation"
    EXTERNAL_ACCEPTANCE = "external_acceptance"
    CAPABILITY_READY = "capability_ready"
    PLANNED = "planned"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    VERIFYING_OUTCOME = "verifying_outcome"
    WAITING_DEPENDENCY = "waiting_dependency"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ObjectiveWorkStatus:
    work_id: str
    state: str
    status_detail: str | None

    def public_payload(self) -> dict[str, object]:
        return {
            "work_id": self.work_id,
            "state": self.state,
            "status_detail": self.status_detail,
        }


@dataclass(frozen=True, slots=True)
class ObjectiveChangeStatus:
    change_id: str
    state: str
    work: tuple[ObjectiveWorkStatus, ...]
    pending_gate_ids: tuple[str, ...]
    lifecycle_proposal_present: bool
    activation_present: bool
    external_acceptance_required: bool
    external_acceptance_work_id: str | None
    external_acceptance_work_state: str | None
    external_acceptance_verdict: str | None
    lineage_complete: bool
    lineage_error: str | None

    def public_payload(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "state": self.state,
            "work": [item.public_payload() for item in self.work],
            "pending_gate_ids": list(self.pending_gate_ids),
            "lifecycle_proposal_present": self.lifecycle_proposal_present,
            "activation_present": self.activation_present,
            "external_acceptance_required": self.external_acceptance_required,
            "external_acceptance_work_id": self.external_acceptance_work_id,
            "external_acceptance_work_state": self.external_acceptance_work_state,
            "external_acceptance_verdict": self.external_acceptance_verdict,
            "lineage_complete": self.lineage_complete,
            "lineage_integrity_ok": self.lineage_error is None,
        }


@dataclass(frozen=True, slots=True)
class ObjectiveBlocker:
    kind: str
    blocker_id: str
    owner_action_required: bool
    detail: str

    def public_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "blocker_id": self.blocker_id,
            "owner_action_required": self.owner_action_required,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class OwnerObjectiveStatus:
    goal_id: str
    owner_request: str
    desired_outcome: str
    goal_state: str
    overall_state: ObjectiveOverallState
    phase: ObjectivePhase
    verified_completion: bool
    plan_id: str | None
    plan_state: str | None
    blocker: ObjectiveBlocker | None
    capability_gap_ids: tuple[str, ...]
    continuation_ids: tuple[str, ...]
    work: tuple[ObjectiveWorkStatus, ...]
    engineering_changes: tuple[ObjectiveChangeStatus, ...]

    @property
    def terminal(self) -> bool:
        return self.overall_state in {
            ObjectiveOverallState.COMPLETED,
            ObjectiveOverallState.FAILED,
            ObjectiveOverallState.CANCELLED,
        }

    def public_payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "owner_request": self.owner_request,
            "desired_outcome": self.desired_outcome,
            "goal_state": self.goal_state,
            "overall_state": self.overall_state.value,
            "phase": self.phase.value,
            "terminal": self.terminal,
            "verified_completion": self.verified_completion,
            "plan_id": self.plan_id,
            "plan_state": self.plan_state,
            "blocker": None if self.blocker is None else self.blocker.public_payload(),
            "capability_gap_ids": list(self.capability_gap_ids),
            "continuation_ids": list(self.continuation_ids),
            "work": [item.public_payload() for item in self.work],
            "engineering_changes": [
                item.public_payload() for item in self.engineering_changes
            ],
            "truth_note": (
                "Overall completion is authoritative only when verified_completion is "
                "true. Child WorkItems or EngineeringChanges may finish while the owner "
                "objective remains active."
            ),
        }


_CHANGE_PHASE: dict[
    ChangeState,
    tuple[ObjectiveOverallState, ObjectivePhase],
] = {
    ChangeState.PROPOSED: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.ACQUIRING_CAPABILITY,
    ),
    ChangeState.RESEARCHING: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.ACQUIRING_CAPABILITY,
    ),
    ChangeState.ARCHITECTURE_READY: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.ARCHITECTURE_READY,
    ),
    ChangeState.WAITING_OWNER_APPROVAL: (
        ObjectiveOverallState.WAITING_OWNER,
        ObjectivePhase.WAITING_OWNER_APPROVAL,
    ),
    ChangeState.APPROVED_FOR_BUILD: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.READY_FOR_BUILD,
    ),
    ChangeState.DEVELOPING: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.DEVELOPING,
    ),
    ChangeState.VERIFYING: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.ENGINEERING_VERIFYING,
    ),
    ChangeState.WAITING_OWNER_ACCEPTANCE: (
        ObjectiveOverallState.WAITING_OWNER,
        ObjectivePhase.WAITING_OWNER_ACCEPTANCE,
    ),
    ChangeState.READY_FOR_PROMOTION: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.READY_FOR_PROMOTION,
    ),
    ChangeState.WAITING_PROMOTION_APPROVAL: (
        ObjectiveOverallState.WAITING_OWNER,
        ObjectivePhase.WAITING_PROMOTION_APPROVAL,
    ),
    ChangeState.PROMOTED: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.PROMOTED,
    ),
    ChangeState.OBSERVING: (
        ObjectiveOverallState.ACTIVE,
        ObjectivePhase.OBSERVING,
    ),
    ChangeState.BLOCKED_EXTERNAL: (
        ObjectiveOverallState.WAITING_EXTERNAL,
        ObjectivePhase.EXTERNAL_ACCEPTANCE,
    ),
    ChangeState.REJECTED: (
        ObjectiveOverallState.BLOCKED,
        ObjectivePhase.BLOCKED,
    ),
    ChangeState.FAILED: (
        ObjectiveOverallState.BLOCKED,
        ObjectivePhase.BLOCKED,
    ),
    ChangeState.SUPERSEDED: (
        ObjectiveOverallState.BLOCKED,
        ObjectivePhase.BLOCKED,
    ),
    ChangeState.ROLLED_BACK: (
        ObjectiveOverallState.BLOCKED,
        ObjectivePhase.BLOCKED,
    ),
}

_OVERALL_PRIORITY = {
    ObjectiveOverallState.BLOCKED: 50,
    ObjectiveOverallState.WAITING_OWNER: 40,
    ObjectiveOverallState.WAITING_EXTERNAL: 30,
    ObjectiveOverallState.PAUSED: 20,
    ObjectiveOverallState.ACTIVE: 10,
    ObjectiveOverallState.COMPLETED: 0,
    ObjectiveOverallState.FAILED: 0,
    ObjectiveOverallState.CANCELLED: 0,
}

_PHASE_PROGRESS = {
    ObjectivePhase.RECEIVED: 0,
    ObjectivePhase.RESOLVING: 10,
    ObjectivePhase.WAITING_INFORMATION: 15,
    ObjectivePhase.REQUIREMENTS_READY: 20,
    ObjectivePhase.ACQUIRING_CAPABILITY: 30,
    ObjectivePhase.ARCHITECTURE_READY: 40,
    ObjectivePhase.WAITING_OWNER_APPROVAL: 45,
    ObjectivePhase.READY_FOR_BUILD: 50,
    ObjectivePhase.DEVELOPING: 60,
    ObjectivePhase.ENGINEERING_VERIFYING: 70,
    ObjectivePhase.WAITING_OWNER_ACCEPTANCE: 75,
    ObjectivePhase.READY_FOR_PROMOTION: 80,
    ObjectivePhase.WAITING_PROMOTION_APPROVAL: 82,
    ObjectivePhase.PROMOTED: 85,
    ObjectivePhase.OBSERVING: 88,
    ObjectivePhase.WAITING_ACTIVATION: 90,
    ObjectivePhase.EXTERNAL_ACCEPTANCE: 95,
    ObjectivePhase.CAPABILITY_READY: 100,
    ObjectivePhase.PLANNED: 30,
    ObjectivePhase.EXECUTING: 60,
    ObjectivePhase.MONITORING: 80,
    ObjectivePhase.VERIFYING_OUTCOME: 90,
    ObjectivePhase.WAITING_DEPENDENCY: 50,
    ObjectivePhase.PAUSED: 50,
    ObjectivePhase.BLOCKED: 0,
    ObjectivePhase.COMPLETED: 100,
    ObjectivePhase.FAILED: 0,
    ObjectivePhase.CANCELLED: 0,
}


class OwnerObjectiveStatusResolver:
    """Project one owner goal across every canonical subsystem it depends on."""

    def __init__(self, *, goals: GoalStore, changes: ChangeStore) -> None:
        if not isinstance(goals, GoalStore):
            raise TypeError("goals must be GoalStore")
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        self._goals = goals
        self._changes = changes

    @property
    def goals(self) -> GoalStore:
        return self._goals

    @property
    def changes(self) -> ChangeStore:
        return self._changes

    def list_active(self, *, limit: int = 20) -> tuple[OwnerObjectiveStatus, ...]:
        return tuple(
            self.resolve(goal.goal_id)
            for goal in self._goals.list_active_goals(limit=limit)
        )

    def find_active_by_work_id(
        self,
        work_id: str,
        *,
        limit: int = 100,
    ) -> OwnerObjectiveStatus | None:
        target = str(work_id).strip()
        if not target:
            return None
        for objective in self.list_active(limit=limit):
            if any(item.work_id == target for item in objective.work):
                return objective
        return None

    def find_active_by_change_id(
        self,
        change_id: str,
        *,
        limit: int = 100,
    ) -> OwnerObjectiveStatus | None:
        target = str(change_id).strip()
        if not target:
            return None
        for objective in self.list_active(limit=limit):
            if any(
                change.change_id == target for change in objective.engineering_changes
            ):
                return objective
        return None

    def resolve(self, goal_id: str) -> OwnerObjectiveStatus:
        goal = self._goals.get_goal(str(goal_id).strip())
        if goal is None:
            raise ValueError(f"unknown owner goal: {goal_id}")

        plan = self._goals.latest_plan_for_goal(goal.goal_id)
        gaps = self._goals.list_gaps(goal_id=goal.goal_id, limit=1000)
        continuations = self._goals.list_continuations(
            goal_id=goal.goal_id,
            limit=1000,
        )
        needs = self._goals.list_information_needs(
            goal_id=goal.goal_id,
            limit=1000,
        )

        work_by_id: dict[str, ObjectiveWorkStatus] = {}
        continuation_change_ids: dict[str, str] = {}
        for continuation in continuations:
            for work_id in continuation.work_ids:
                item = self._changes.work.require(work_id)
                work_by_id[work_id] = ObjectiveWorkStatus(
                    work_id=item.work_id,
                    state=item.state.value,
                    status_detail=item.status_detail,
                )
                stage = self._changes.stage_for_work(work_id)
                if stage is not None:
                    continuation_change_ids[continuation.continuation_id] = (
                        stage.change_id
                    )

        gate_service = GateService(
            self._changes,
            verify_owner=lambda *_: False,
        )
        pending_gate_ids = gate_service.pending_gate_ids()

        change_statuses: list[ObjectiveChangeStatus] = []
        for change_id in sorted(set(continuation_change_ids.values())):
            change = self._changes.require(change_id)
            stage_work: list[ObjectiveWorkStatus] = []
            for stage in self._changes.list_stages(change_id):
                item = self._changes.work.require(stage.work_id)
                status = ObjectiveWorkStatus(
                    work_id=item.work_id,
                    state=item.state.value,
                    status_detail=item.status_detail,
                )
                work_by_id[item.work_id] = status
                stage_work.append(status)

            change_gate_ids: list[str] = []
            for gate_id in pending_gate_ids:
                gate = gate_service.get(gate_id)
                if gate is None:
                    continue
                challenge = getattr(gate, "challenge", gate)
                if challenge.change_id == change_id:
                    change_gate_ids.append(gate_id)

            lifecycle_proposal = self._changes.latest_artifact(
                change_id,
                "capability_lifecycle_proposal",
            )
            candidate = self._changes.latest_artifact(
                change_id,
                "capability_candidate",
            )
            activation = self._changes.latest_artifact(
                change_id,
                "capability_lifecycle_activation",
            )
            disabled = self._changes.latest_artifact(
                change_id,
                "capability_lifecycle_disable",
            )
            activation_present = bool(
                candidate is not None
                and activation is not None
                and activation.payload.get("effective_enabled") is True
                and activation.payload.get("candidate_artifact_id")
                == candidate.artifact_id
                and activation.payload.get("candidate_artifact_digest")
                == candidate.digest
                and not (
                    disabled is not None
                    and disabled.created_at >= activation.created_at
                    and disabled.payload.get("candidate_artifact_id")
                    == candidate.artifact_id
                    and disabled.payload.get("effective_enabled") is False
                )
            )

            architecture = (
                None
                if change.current_architecture_artifact_id is None
                else self._changes.get_artifact(change.current_architecture_artifact_id)
            )
            contracts = (
                set()
                if architecture is None
                else {
                    str(item).strip()
                    for item in architecture.payload.get(
                        "owner_acceptance_contract_ids",
                        (),
                    )
                    if str(item).strip()
                }
            )
            external_required = PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT in contracts

            binding = None
            if activation_present and activation is not None:
                bindings = [
                    artifact
                    for artifact in self._changes.list_artifacts(
                        change_id,
                        kind=EXTERNAL_ACCEPTANCE_BINDING_KIND,
                    )
                    if artifact.payload.get("activation_artifact_id")
                    == activation.artifact_id
                    and artifact.payload.get("activation_artifact_digest")
                    == activation.digest
                ]
                if bindings:
                    binding = max(
                        bindings,
                        key=lambda artifact: (
                            artifact.revision,
                            artifact.artifact_id,
                        ),
                    )
            external_work_id = (
                None
                if binding is None
                else str(binding.payload.get("work_id") or "").strip() or None
            )

            external_result = None
            if binding is not None:
                results = [
                    artifact
                    for artifact in self._changes.list_artifacts(
                        change_id,
                        kind=EXTERNAL_ACCEPTANCE_RESULT_KIND,
                    )
                    if artifact.payload.get("binding_artifact_id")
                    == binding.artifact_id
                    and artifact.payload.get("binding_artifact_digest")
                    == binding.digest
                ]
                if results:
                    external_result = max(
                        results,
                        key=lambda artifact: (
                            artifact.revision,
                            artifact.artifact_id,
                        ),
                    )
            external_verdict = (
                None
                if external_result is None
                else str(external_result.payload.get("verdict") or "").strip() or None
            )

            external_work_state = None
            if external_work_id is not None:
                external_work = self._changes.work.require(external_work_id)
                external_work_state = external_work.state.value
                work_by_id[external_work_id] = ObjectiveWorkStatus(
                    work_id=external_work.work_id,
                    state=external_work.state.value,
                    status_detail=external_work.status_detail,
                )

            linked_continuations = [
                continuation
                for continuation in continuations
                if continuation_change_ids.get(continuation.continuation_id)
                == change_id
                and continuation.blocked_by_type
                is ContinuationBlockerType.CAPABILITY_ACQUISITION
            ]
            lineage_complete = False
            lineage_error = None
            for continuation in linked_continuations:
                try:
                    lineage = verify_capability_acquisition_completion(
                        self._changes,
                        change_id=change_id,
                        motivating_goal_id=goal.goal_id,
                        gap_id=continuation.blocked_by_id,
                    )
                except CapabilityAcquisitionLineageError as exc:
                    lineage_error = type(exc).__name__
                    lineage = None
                if lineage is not None:
                    lineage_complete = True
                    lineage_error = None
                    break

            change_statuses.append(
                ObjectiveChangeStatus(
                    change_id=change_id,
                    state=change.state.value,
                    work=tuple(stage_work),
                    pending_gate_ids=tuple(sorted(change_gate_ids)),
                    lifecycle_proposal_present=lifecycle_proposal is not None,
                    activation_present=activation_present,
                    external_acceptance_required=external_required,
                    external_acceptance_work_id=external_work_id,
                    external_acceptance_work_state=external_work_state,
                    external_acceptance_verdict=external_verdict,
                    lineage_complete=lineage_complete,
                    lineage_error=lineage_error,
                )
            )

        overall, phase, blocker = self._derive_status(
            goal_state=goal.state,
            needs=needs,
            continuations=continuations,
            change_statuses=tuple(change_statuses),
        )

        return OwnerObjectiveStatus(
            goal_id=goal.goal_id,
            owner_request=goal.exact_owner_request,
            desired_outcome=goal.desired_outcome,
            goal_state=goal.state.value,
            overall_state=overall,
            phase=phase,
            verified_completion=goal.state is GoalState.COMPLETED,
            plan_id=None if plan is None else plan.plan_id,
            plan_state=None if plan is None else plan.state.value,
            blocker=blocker,
            capability_gap_ids=tuple(gap.gap_id for gap in gaps),
            continuation_ids=tuple(
                continuation.continuation_id for continuation in continuations
            ),
            work=tuple(work_by_id[key] for key in sorted(work_by_id)),
            engineering_changes=tuple(change_statuses),
        )

    def _derive_status(
        self,
        *,
        goal_state: GoalState,
        needs,
        continuations,
        change_statuses: tuple[ObjectiveChangeStatus, ...],
    ) -> tuple[ObjectiveOverallState, ObjectivePhase, ObjectiveBlocker | None]:
        if goal_state is GoalState.COMPLETED:
            return (
                ObjectiveOverallState.COMPLETED,
                ObjectivePhase.COMPLETED,
                None,
            )
        if goal_state is GoalState.FAILED:
            return ObjectiveOverallState.FAILED, ObjectivePhase.FAILED, None
        if goal_state is GoalState.CANCELLED:
            return ObjectiveOverallState.CANCELLED, ObjectivePhase.CANCELLED, None
        if goal_state is GoalState.PAUSED:
            return ObjectiveOverallState.PAUSED, ObjectivePhase.PAUSED, None

        waiting_need = next(
            (
                need
                for need in needs
                if need.state is InformationNeedState.WAITING_FOR_OWNER
            ),
            None,
        )
        if waiting_need is not None:
            return (
                ObjectiveOverallState.WAITING_OWNER,
                ObjectivePhase.WAITING_INFORMATION,
                ObjectiveBlocker(
                    kind="information_need",
                    blocker_id=waiting_need.information_need_id,
                    owner_action_required=True,
                    detail=waiting_need.required_fact,
                ),
            )

        if goal_state is GoalState.WAITING_CAPABILITY:
            candidates: list[
                tuple[
                    ObjectiveOverallState,
                    ObjectivePhase,
                    ObjectiveBlocker | None,
                ]
            ] = []
            for change in change_statuses:
                candidates.append(self._status_for_change(change))
            if candidates:
                return max(
                    candidates,
                    key=lambda item: (
                        _OVERALL_PRIORITY[item[0]],
                        -_PHASE_PROGRESS[item[1]],
                        "" if item[2] is None else item[2].blocker_id,
                    ),
                )
            return (
                ObjectiveOverallState.ACTIVE,
                ObjectivePhase.ACQUIRING_CAPABILITY,
                None,
            )

        blocked = next(
            (
                continuation
                for continuation in continuations
                if continuation.state is ContinuationState.BLOCKED
            ),
            None,
        )
        if blocked is not None:
            external = blocked.blocked_by_type in {
                ContinuationBlockerType.EXTERNAL_ACCEPTANCE,
                ContinuationBlockerType.WAIT,
            }
            return (
                (
                    ObjectiveOverallState.WAITING_EXTERNAL
                    if external
                    else ObjectiveOverallState.BLOCKED
                ),
                (
                    ObjectivePhase.EXTERNAL_ACCEPTANCE
                    if external
                    else ObjectivePhase.WAITING_DEPENDENCY
                ),
                ObjectiveBlocker(
                    kind=blocked.blocked_by_type.value,
                    blocker_id=blocked.blocked_by_id,
                    owner_action_required=False,
                    detail=(
                        "The objective is waiting for its persisted continuation "
                        "dependency to resolve."
                    ),
                ),
            )

        mapping = {
            GoalState.RECEIVED: ObjectivePhase.RECEIVED,
            GoalState.RESOLVING: ObjectivePhase.RESOLVING,
            GoalState.WAITING_INFORMATION: ObjectivePhase.WAITING_INFORMATION,
            GoalState.REQUIREMENTS_READY: ObjectivePhase.REQUIREMENTS_READY,
            GoalState.PLANNED: ObjectivePhase.PLANNED,
            GoalState.EXECUTING: ObjectivePhase.EXECUTING,
            GoalState.MONITORING: ObjectivePhase.MONITORING,
            GoalState.VERIFYING: ObjectivePhase.VERIFYING_OUTCOME,
        }
        return (
            ObjectiveOverallState.ACTIVE,
            mapping.get(goal_state, ObjectivePhase.RESOLVING),
            None,
        )

    def _status_for_change(
        self,
        change: ObjectiveChangeStatus,
    ) -> tuple[ObjectiveOverallState, ObjectivePhase, ObjectiveBlocker | None]:
        state = ChangeState(change.state)
        if change.lineage_error is not None:
            return (
                ObjectiveOverallState.BLOCKED,
                ObjectivePhase.BLOCKED,
                ObjectiveBlocker(
                    kind="lineage_integrity",
                    blocker_id=change.change_id,
                    owner_action_required=False,
                    detail=(
                        "Canonical capability lineage failed an integrity check. "
                        "The objective cannot be reported as complete or safely advanced."
                    ),
                ),
            )
        if (
            change.external_acceptance_verdict is not None
            and change.external_acceptance_verdict.casefold() != "pass"
        ):
            return (
                ObjectiveOverallState.BLOCKED,
                ObjectivePhase.BLOCKED,
                ObjectiveBlocker(
                    kind="external_acceptance_failed",
                    blocker_id=(change.external_acceptance_work_id or change.change_id),
                    owner_action_required=False,
                    detail=(
                        "Real-world capability acceptance did not produce a passing "
                        "verdict."
                    ),
                ),
            )
        if change.lineage_complete:
            return (
                ObjectiveOverallState.ACTIVE,
                ObjectivePhase.CAPABILITY_READY,
                None,
            )

        if change.lifecycle_proposal_present and not change.activation_present:
            return (
                ObjectiveOverallState.WAITING_OWNER,
                ObjectivePhase.WAITING_ACTIVATION,
                ObjectiveBlocker(
                    kind="capability_activation",
                    blocker_id=change.change_id,
                    owner_action_required=True,
                    detail=(
                        "The promoted capability package is admitted but intentionally "
                        "disabled until the owner authorizes activation."
                    ),
                ),
            )

        if change.activation_present and change.external_acceptance_required:
            return (
                ObjectiveOverallState.WAITING_EXTERNAL,
                ObjectivePhase.EXTERNAL_ACCEPTANCE,
                ObjectiveBlocker(
                    kind="external_acceptance",
                    blocker_id=(change.external_acceptance_work_id or change.change_id),
                    owner_action_required=False,
                    detail=(
                        "The capability is enabled but still requires passing "
                        "real-world external acceptance evidence."
                    ),
                ),
            )

        if state is ChangeState.CLOSED:
            if not change.activation_present:
                return (
                    ObjectiveOverallState.WAITING_OWNER,
                    ObjectivePhase.WAITING_ACTIVATION,
                    ObjectiveBlocker(
                        kind="capability_activation",
                        blocker_id=change.change_id,
                        owner_action_required=True,
                        detail=(
                            "Engineering is complete, but the acquired capability "
                            "is not effectively enabled yet."
                        ),
                    ),
                )
            return (
                ObjectiveOverallState.ACTIVE,
                ObjectivePhase.CAPABILITY_READY,
                None,
            )

        overall, phase = _CHANGE_PHASE[state]
        blocker = None
        if overall is ObjectiveOverallState.WAITING_OWNER:
            blocker_id = (
                change.pending_gate_ids[0]
                if change.pending_gate_ids
                else change.change_id
            )
            blocker = ObjectiveBlocker(
                kind="engineering_change_gate",
                blocker_id=blocker_id,
                owner_action_required=True,
                detail=f"EngineeringChange is {state.value}.",
            )
        elif overall is ObjectiveOverallState.WAITING_EXTERNAL:
            blocker = ObjectiveBlocker(
                kind="engineering_change_external",
                blocker_id=change.change_id,
                owner_action_required=False,
                detail=f"EngineeringChange is {state.value}.",
            )
        elif overall is ObjectiveOverallState.BLOCKED:
            blocker = ObjectiveBlocker(
                kind="engineering_change_terminal",
                blocker_id=change.change_id,
                owner_action_required=False,
                detail=f"EngineeringChange is {state.value}.",
            )
        return overall, phase, blocker
