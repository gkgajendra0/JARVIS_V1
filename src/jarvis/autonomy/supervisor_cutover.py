"""Controlled S12 cutover from shadow reasoning to governed coordination.

The Supervisor never mutates canonical stores directly. In ASSISTED mode it may ask
the existing EngineeringChange coordinator to reconcile one digest-bound current
change. Gates, policy, Work/DBOS, verification and promotion remain authoritative.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import (
    reconcile_owner_acceptance_gates,
    reconcile_owner_change_gates,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.workspace import (
    ObjectiveWorkspaceProjector,
    ObjectiveWorkspaceV1,
)

from .mode import AutonomyMode
from .supervisor import (
    GlobalSupervisor,
    SupervisorAction,
    SupervisorDecisionV1,
    supervisor_context_from_workspace,
)


class SupervisorCutoverDisposition(StrEnum):
    SHADOW_ONLY = "shadow_only"
    REJECTED = "rejected"
    AWAIT_RUNTIME = "await_runtime"
    AWAIT_OWNER = "await_owner"
    RECONCILED_CHANGE = "reconciled_change"
    RETRIED_WORK = "retried_work"
    TERMINAL_OBSERVED = "terminal_observed"
    GOAL_RUNTIME_REQUIRED = "goal_runtime_required"


@dataclass(frozen=True, slots=True)
class SupervisorCutoverResultV1:
    schema: str
    mode: AutonomyMode
    goal_id: str
    action: SupervisorAction | None
    disposition: SupervisorCutoverDisposition
    accepted: bool
    reason_codes: tuple[str, ...]
    decision_digest: str | None
    before_workspace_digest: str
    after_workspace_digest: str
    change_id: str | None
    change_state_before: str | None
    change_state_after: str | None
    surfaced_gate_ids: tuple[str, ...]
    mutation_performed: bool
    deterministic_authority_preserved: bool
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "mode": self.mode.value,
            "goal_id": self.goal_id,
            "action": None if self.action is None else self.action.value,
            "disposition": self.disposition.value,
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "decision_digest": self.decision_digest,
            "before_workspace_digest": self.before_workspace_digest,
            "after_workspace_digest": self.after_workspace_digest,
            "change_id": self.change_id,
            "change_state_before": self.change_state_before,
            "change_state_after": self.change_state_after,
            "surfaced_gate_ids": list(self.surfaced_gate_ids),
            "mutation_performed": self.mutation_performed,
            "deterministic_authority_preserved": self.deterministic_authority_preserved,
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_cutover_result.v1":
            raise ValueError("unsupported Supervisor cutover result schema")
        if not isinstance(self.mode, AutonomyMode):
            raise TypeError("mode must be AutonomyMode")
        if self.mode is not AutonomyMode.ASSISTED and self.mutation_performed:
            raise ValueError("non-assisted Supervisor cutover may not mutate state")
        if not self.deterministic_authority_preserved:
            raise ValueError("Supervisor cutover cannot bypass deterministic authority")
        if (
            self.digest != "pending"
            and canonical_digest(self.canonical_payload()) != self.digest
        ):
            raise ValueError("Supervisor cutover result digest mismatch")


_RECONCILE_ACTIONS = frozenset(
    {
        SupervisorAction.CONTINUE,
        SupervisorAction.REQUEST_RESEARCH,
        SupervisorAction.REQUEST_ARCHITECTURE,
        SupervisorAction.RESUME_DEVELOPMENT,
        SupervisorAction.VERIFY_ASSUMPTION,
        SupervisorAction.SUPERSEDE_ATTEMPT,
    }
)


class SupervisorCutoverController:
    """Bridge accepted Supervisor decisions back into existing governed coordinators."""

    def __init__(
        self,
        *,
        projector: ObjectiveWorkspaceProjector,
        change_coordinator: ChangeCoordinator,
        supervisor: GlobalSupervisor | None = None,
        mode: AutonomyMode = AutonomyMode.SHADOW,
        retry_failed_work: Callable[[str], object] | None = None,
        invariant_guard: Callable[[ObjectiveWorkspaceV1], tuple[str, ...]]
        | None = None,
    ) -> None:
        if not isinstance(projector, ObjectiveWorkspaceProjector):
            raise TypeError("projector must be ObjectiveWorkspaceProjector")
        if not isinstance(change_coordinator, ChangeCoordinator):
            raise TypeError("change_coordinator must be ChangeCoordinator")
        if not isinstance(mode, AutonomyMode):
            raise TypeError("mode must be AutonomyMode")
        if mode is AutonomyMode.ACTIVE_BOUNDED:
            raise ValueError(
                "Global Supervisor ACTIVE_BOUNDED requires a later explicit policy"
            )
        self._projector = projector
        self._changes = change_coordinator
        if retry_failed_work is not None and not callable(retry_failed_work):
            raise TypeError("retry_failed_work must be callable when provided")
        if invariant_guard is not None and not callable(invariant_guard):
            raise TypeError("invariant_guard must be callable when provided")
        self._supervisor = supervisor or GlobalSupervisor()
        self._mode = mode
        self._retry_failed_work = retry_failed_work
        self._invariant_guard = invariant_guard

    @staticmethod
    def _change_state(
        workspace: ObjectiveWorkspaceV1,
        change_id: str | None,
    ) -> str | None:
        if change_id is None:
            return None
        return next(
            (
                change.state
                for change in workspace.changes
                if change.change_id == change_id
            ),
            None,
        )

    def coordinate(
        self,
        goal_id: str,
        *,
        decision: SupervisorDecisionV1 | None = None,
    ) -> SupervisorCutoverResultV1:
        before = self._projector.project(goal_id)
        context = supervisor_context_from_workspace(before)
        change_id = context.progress_ledger.active_change_id
        before_state = self._change_state(before, change_id)

        if self._mode is AutonomyMode.ASSISTED and self._invariant_guard is not None:
            invariant_codes = tuple(
                dict.fromkeys(
                    normalized
                    for item in self._invariant_guard(before)
                    if (normalized := " ".join(str(item).split()).strip())
                )
            )
            if invariant_codes:
                return self._result(
                    before=before,
                    after=before,
                    action=None,
                    disposition=SupervisorCutoverDisposition.REJECTED,
                    accepted=False,
                    reason_codes=tuple(
                        f"system_invariant:{code}" for code in invariant_codes
                    ),
                    decision_digest=None,
                    change_id=change_id,
                    change_state_before=before_state,
                    surfaced_gate_ids=(),
                )

        selected = decision or self._supervisor.evaluate(before)
        if not isinstance(selected, SupervisorDecisionV1):
            raise TypeError("decision must be SupervisorDecisionV1")

        revalidated = GlobalSupervisor.validate(context, selected.proposal)
        action = revalidated.proposal.action

        if not revalidated.accepted:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.REJECTED,
                accepted=False,
                reason_codes=revalidated.rejection_codes,
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        change_bound_actions = _RECONCILE_ACTIONS | {
            SupervisorAction.ASK_OWNER,
            SupervisorAction.RETRY,
        }
        if (
            action in change_bound_actions
            and change_id is not None
            and revalidated.proposal.target_change_id != change_id
        ):
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.REJECTED,
                accepted=False,
                reason_codes=("change_binding_required",),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if self._mode is not AutonomyMode.ASSISTED:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.SHADOW_ONLY,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if action is SupervisorAction.WAIT_RESOURCE:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.AWAIT_RUNTIME,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if action is SupervisorAction.RETRY:
            work_id = context.progress_ledger.active_work_id
            if self._retry_failed_work is None or work_id is None:
                return self._result(
                    before=before,
                    after=before,
                    action=action,
                    disposition=SupervisorCutoverDisposition.AWAIT_RUNTIME,
                    accepted=True,
                    reason_codes=("retry_runtime_not_attached",),
                    decision_digest=revalidated.digest,
                    change_id=change_id,
                    change_state_before=before_state,
                    surfaced_gate_ids=(),
                )
            self._retry_failed_work(work_id)
            after = self._projector.project(goal_id)
            return self._result(
                before=before,
                after=after,
                action=action,
                disposition=SupervisorCutoverDisposition.RETRIED_WORK,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if action is SupervisorAction.ASK_OWNER:
            surfaced = (
                ()
                if change_id is None
                else reconcile_owner_change_gates(
                    self._changes,
                    change_ids=(change_id,),
                )
            )
            after = self._projector.project(goal_id)
            return self._result(
                before=before,
                after=after,
                action=action,
                disposition=SupervisorCutoverDisposition.AWAIT_OWNER,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=surfaced,
            )

        if action is SupervisorAction.VERIFY_ASSUMPTION:
            surfaced = reconcile_owner_acceptance_gates(
                self._changes,
                change_ids=(change_id,),
            )
            after = self._projector.project(goal_id)
            return self._result(
                before=before,
                after=after,
                action=action,
                disposition=SupervisorCutoverDisposition.RECONCILED_CHANGE,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=surfaced,
            )

        if action is SupervisorAction.TERMINAL:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.TERMINAL_OBSERVED,
                accepted=True,
                reason_codes=(),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if action is SupervisorAction.REPLAN or change_id is None:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.GOAL_RUNTIME_REQUIRED,
                accepted=True,
                reason_codes=("goal_runtime_coordination_not_cut_over",),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        if action not in _RECONCILE_ACTIONS:
            return self._result(
                before=before,
                after=before,
                action=action,
                disposition=SupervisorCutoverDisposition.REJECTED,
                accepted=False,
                reason_codes=("unsupported_cutover_action",),
                decision_digest=revalidated.digest,
                change_id=change_id,
                change_state_before=before_state,
                surfaced_gate_ids=(),
            )

        self._changes.reconcile(change_id)
        surfaced = reconcile_owner_change_gates(
            self._changes,
            change_ids=(change_id,),
        )
        after = self._projector.project(goal_id)
        return self._result(
            before=before,
            after=after,
            action=action,
            disposition=SupervisorCutoverDisposition.RECONCILED_CHANGE,
            accepted=True,
            reason_codes=(),
            decision_digest=revalidated.digest,
            change_id=change_id,
            change_state_before=before_state,
            surfaced_gate_ids=surfaced,
        )

    def _result(
        self,
        *,
        before: ObjectiveWorkspaceV1,
        after: ObjectiveWorkspaceV1,
        action: SupervisorAction | None,
        disposition: SupervisorCutoverDisposition,
        accepted: bool,
        reason_codes: tuple[str, ...],
        decision_digest: str | None,
        change_id: str | None,
        change_state_before: str | None,
        surfaced_gate_ids: tuple[str, ...],
    ) -> SupervisorCutoverResultV1:
        result = SupervisorCutoverResultV1(
            schema="supervisor_cutover_result.v1",
            mode=self._mode,
            goal_id=before.goal.record_id,
            action=action,
            disposition=disposition,
            accepted=accepted,
            reason_codes=tuple(reason_codes),
            decision_digest=decision_digest,
            before_workspace_digest=before.digest,
            after_workspace_digest=after.digest,
            change_id=change_id,
            change_state_before=change_state_before,
            change_state_after=self._change_state(after, change_id),
            surfaced_gate_ids=tuple(surfaced_gate_ids),
            mutation_performed=before.digest != after.digest,
            deterministic_authority_preserved=True,
            digest="pending",
        )
        return replace(result, digest=canonical_digest(result.canonical_payload()))
