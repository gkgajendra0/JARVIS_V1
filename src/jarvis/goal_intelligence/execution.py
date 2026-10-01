"""Durable PlanGraph state/evidence around the canonical GoalOrchestrator.

GoalOrchestrator owns routing to existing JARVIS subsystems.  GoalPlanDispatcher owns
only durable plan-node state, evidence persistence, replay safety and no-progress
bookkeeping.  It never becomes a second capability, Hands, Phase-9 or verification
orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from jarvis.engineering_substrate.canonical import canonical_digest

from .models import (
    PlanGraphV1,
    PlanNodeState,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
)
from .service import (
    GoalDispatchStatus,
    GoalOrchestrator,
    PlanDispatchResult as RoutedResult,
)
from .store import GoalStore, GoalStoreError


class PlanDispatchDisposition(str, Enum):
    SUCCEEDED = "succeeded"
    WAITING = "waiting"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PlanDispatchResult:
    plan: PlanGraphV1
    node: PlanNodeV1
    disposition: PlanDispatchDisposition
    evidence_ref: str | None = None
    reason: str | None = None


class GoalPlanDispatcher:
    """Persist and advance one ready plan node through GoalOrchestrator."""

    def __init__(
        self,
        *,
        store: GoalStore,
        orchestrator: GoalOrchestrator,
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        if not isinstance(orchestrator, GoalOrchestrator):
            raise TypeError("orchestrator must be GoalOrchestrator")
        self._store = store
        self._orchestrator = orchestrator

    @staticmethod
    def _node(plan: PlanGraphV1, node_id: str) -> PlanNodeV1:
        node = next((item for item in plan.nodes if item.node_id == node_id), None)
        if node is None:
            raise GoalStoreError(f"unknown plan node: {node_id}")
        return node

    @staticmethod
    def _predecessor_ids(plan: PlanGraphV1, node_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(source for source, target in plan.edges if target == node_id)
        )

    def ready_nodes(self, plan: PlanGraphV1) -> tuple[PlanNodeV1, ...]:
        by_id = {node.node_id: node for node in plan.nodes}
        ready = []
        for node in plan.nodes:
            if node.state not in {PlanNodeState.PENDING, PlanNodeState.READY}:
                continue
            predecessors = self._predecessor_ids(plan, node.node_id)
            if all(
                by_id[source].state is PlanNodeState.SUCCEEDED
                for source in predecessors
            ):
                ready.append(node)
        return tuple(sorted(ready, key=lambda item: item.node_id))

    def _update_node(
        self,
        plan: PlanGraphV1,
        node_id: str,
        state: PlanNodeState,
        *,
        plan_state: PlanState | None = None,
    ) -> PlanGraphV1:
        updated = plan.with_node_state(
            node_id,
            state,
            plan_state=plan_state,
        )
        return self._store.update_plan_execution(
            updated,
            expected_digest=plan.digest,
        )

    def _attempt(self, plan_id: str, node_id: str) -> int:
        return (
            len(
                self._store.list_plan_node_results(
                    plan_id=plan_id,
                    node_id=node_id,
                    limit=1000,
                )
            )
            + 1
        )

    def _record(
        self,
        *,
        plan: PlanGraphV1,
        node: PlanNodeV1,
        status: str,
        payload: dict[str, object],
    ) -> str:
        result = self._store.put_plan_node_result(
            plan_id=plan.plan_id,
            node_id=node.node_id,
            attempt=self._attempt(plan.plan_id, node.node_id),
            status=status,
            payload=payload,
            created_at=datetime.now(UTC).isoformat(),
        )
        return str(result["result_id"])

    def _finalize_success(
        self,
        plan: PlanGraphV1,
        node_id: str,
    ) -> PlanGraphV1:
        updated = self._update_node(
            plan,
            node_id,
            PlanNodeState.SUCCEEDED,
            plan_state=PlanState.ACTIVE,
        )
        by_id = {node.node_id: node for node in updated.nodes}
        if all(
            by_id[completion_id].state is PlanNodeState.SUCCEEDED
            for completion_id in updated.completion_node_ids
        ) and all(node.state is not PlanNodeState.PENDING for node in updated.nodes):
            final = updated.with_node_state(
                node_id,
                PlanNodeState.SUCCEEDED,
                plan_state=PlanState.SUCCEEDED,
            )
            updated = self._store.update_plan_execution(
                final,
                expected_digest=updated.digest,
            )
        return updated

    @staticmethod
    def _action_fingerprint(node: PlanNodeV1) -> str:
        return canonical_digest(
            {
                "capability_key": node.capability_key,
                "operation": node.operation,
                "parameters": node.parameters,
            }
        )

    def _verification_evidence(self, plan_id: str) -> dict[str, object]:
        return {
            "results": list(
                self._store.list_plan_node_results(
                    plan_id=plan_id,
                    limit=1000,
                )
            )
        }

    @staticmethod
    def _route_payload(
        routed: RoutedResult,
        *,
        node: PlanNodeV1,
        action_fingerprint: str | None,
        state_fingerprint: str,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "route": routed.route,
            "result_ref": routed.result_ref,
        }
        if routed.capability_result is not None:
            result = routed.capability_result
            payload.update(
                {
                    "capability_key": result.capability_key,
                    "operation": result.operation,
                    "data": result.data,
                    "reason": result.reason,
                    "provenance": list(result.provenance),
                    "postcondition_ref": node.postcondition_ref,
                    "action_fingerprint": action_fingerprint,
                    "state_fingerprint": state_fingerprint,
                    "observation": node.node_type is PlanNodeType.OBSERVE,
                }
            )
        if routed.verification is not None:
            payload.update(
                {
                    "postcondition_ref": node.postcondition_ref,
                    "verified": routed.verification.verified,
                    "reason": routed.verification.reason,
                    "evidence_refs": list(routed.verification.evidence_refs),
                }
            )
        if routed.interaction is not None:
            payload["interaction"] = routed.interaction
        if routed.phase9_admission is not None:
            payload["phase9_request_id"] = routed.phase9_admission.request.request_id
            change = routed.phase9_admission.admission.change
            if change is not None:
                payload["phase9_change_id"] = change.change_id
            work_id = routed.phase9_admission.admission.acquisition_work_id
            if work_id is not None:
                payload["phase9_work_id"] = work_id
        return payload

    def _record_no_progress_after_failed_verification(
        self,
        *,
        plan: PlanGraphV1,
        verify_node: PlanNodeV1,
    ) -> None:
        for predecessor_id in self._predecessor_ids(plan, verify_node.node_id):
            predecessor = self._node(plan, predecessor_id)
            if predecessor.node_type is not PlanNodeType.ACTION:
                continue
            results = self._store.list_plan_node_results(
                plan_id=plan.plan_id,
                node_id=predecessor.node_id,
                limit=1000,
            )
            if not results:
                continue
            payload = results[-1].get("payload")
            if not isinstance(payload, dict):
                continue
            action_fp = str(payload.get("action_fingerprint") or "")
            state_fp = str(payload.get("state_fingerprint") or "")
            if action_fp and state_fp:
                self._store.record_no_progress(
                    goal_id=plan.goal_id,
                    plan_id=plan.plan_id,
                    node_id=predecessor.node_id,
                    action_fingerprint=action_fp,
                    state_fingerprint=state_fp,
                    reason=(
                        "registered postcondition remained unsatisfied "
                        f"after {predecessor.operation}"
                    ),
                    created_at=datetime.now(UTC).isoformat(),
                )

    def dispatch(
        self,
        *,
        plan_id: str,
        node_id: str,
        session_id: str,
        state_fingerprint: str | None = None,
    ) -> PlanDispatchResult:
        del session_id
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise GoalStoreError(f"unknown plan_id: {plan_id}")
        goal = self._store.get_goal(plan.goal_id)
        if goal is None:
            raise GoalStoreError(f"unknown goal_id: {plan.goal_id}")
        node = self._node(plan, node_id)
        if node not in self.ready_nodes(plan):
            return PlanDispatchResult(
                plan=plan,
                node=node,
                disposition=PlanDispatchDisposition.BLOCKED,
                reason="plan node is not ready",
            )

        action_fingerprint: str | None = None
        state_key = str(state_fingerprint or "").strip().casefold()
        if node.node_type is PlanNodeType.ACTION:
            action_fingerprint = self._action_fingerprint(node)
            if not state_key:
                return PlanDispatchResult(
                    plan=plan,
                    node=node,
                    disposition=PlanDispatchDisposition.FAILED,
                    reason="ACTION requires a pre-action state fingerprint",
                )
            if self._store.has_no_progress(
                goal_id=plan.goal_id,
                action_fingerprint=action_fingerprint,
                state_fingerprint=state_key,
            ):
                return PlanDispatchResult(
                    plan=plan,
                    node=node,
                    disposition=PlanDispatchDisposition.BLOCKED,
                    reason="identical action/state previously made no progress",
                )

        running = self._update_node(
            plan,
            node.node_id,
            PlanNodeState.RUNNING,
            plan_state=PlanState.ACTIVE,
        )
        node = self._node(running, node.node_id)
        evidence = (
            self._verification_evidence(running.plan_id)
            if node.node_type is PlanNodeType.VERIFY
            else None
        )
        routed = self._orchestrator.dispatch_node(
            goal=goal,
            plan=running,
            node=node,
            verification_evidence=evidence,
            observed_state_digest=state_key or None,
        )
        payload = self._route_payload(
            routed,
            node=node,
            action_fingerprint=action_fingerprint,
            state_fingerprint=state_key,
        )
        evidence_ref = self._record(
            plan=running,
            node=node,
            status=routed.status.value,
            payload=payload,
        )

        if routed.status is GoalDispatchStatus.SUCCEEDED:
            succeeded = self._finalize_success(running, node.node_id)
            return PlanDispatchResult(
                plan=succeeded,
                node=self._node(succeeded, node.node_id),
                disposition=PlanDispatchDisposition.SUCCEEDED,
                evidence_ref=evidence_ref,
            )

        if routed.status in {GoalDispatchStatus.WAITING, GoalDispatchStatus.BLOCKED}:
            waiting = self._update_node(
                running,
                node.node_id,
                PlanNodeState.WAITING,
                plan_state=PlanState.WAITING,
            )
            return PlanDispatchResult(
                plan=waiting,
                node=self._node(waiting, node.node_id),
                disposition=(
                    PlanDispatchDisposition.WAITING
                    if routed.status is GoalDispatchStatus.WAITING
                    else PlanDispatchDisposition.BLOCKED
                ),
                evidence_ref=evidence_ref,
                reason=(
                    None
                    if routed.status is GoalDispatchStatus.WAITING
                    else f"{routed.route} is not currently dispatchable"
                ),
            )

        if node.node_type is PlanNodeType.VERIFY:
            self._record_no_progress_after_failed_verification(
                plan=running,
                verify_node=node,
            )
        failed = self._update_node(
            running,
            node.node_id,
            PlanNodeState.FAILED,
            plan_state=PlanState.FAILED,
        )
        return PlanDispatchResult(
            plan=failed,
            node=self._node(failed, node.node_id),
            disposition=PlanDispatchDisposition.FAILED,
            evidence_ref=evidence_ref,
            reason=(
                routed.verification.reason
                if routed.verification is not None
                else (
                    routed.capability_result.reason
                    if routed.capability_result is not None
                    else f"{routed.route} dispatch failed"
                )
            ),
        )
