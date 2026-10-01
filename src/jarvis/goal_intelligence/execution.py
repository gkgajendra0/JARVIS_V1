"""PlanGraph dispatch through existing governed JARVIS execution systems."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.engineering_substrate.canonical import canonical_digest

from .models import (
    PlanGraphV1,
    PlanNodeState,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
)
from .store import GoalStore, GoalStoreError


class GovernedCapabilityRuntime(Protocol):
    def execute(self, request: CapabilityRequest): ...


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


class VerificationRegistry:
    """Release-owned named postcondition predicates; no model-authored execution."""

    def __init__(
        self,
        predicates: dict[
            str,
            Callable[[tuple[dict[str, object], ...]], bool],
        ]
        | None = None,
    ) -> None:
        self._predicates: dict[
            str,
            Callable[[tuple[dict[str, object], ...]], bool],
        ] = {}
        for predicate_id, predicate in (predicates or {}).items():
            self.register(predicate_id, predicate)

    def register(
        self,
        predicate_id: str,
        predicate: Callable[[tuple[dict[str, object], ...]], bool],
    ) -> None:
        key = str(predicate_id).strip()
        if not key or not callable(predicate):
            raise ValueError("verification predicate id/callback must be valid")
        if key in self._predicates:
            raise ValueError(f"duplicate verification predicate: {key}")
        self._predicates[key] = predicate

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._predicates))

    def evaluate(
        self,
        predicate_id: str,
        evidence: tuple[dict[str, object], ...],
    ) -> bool:
        predicate = self._predicates.get(str(predicate_id).strip())
        if predicate is None:
            raise GoalStoreError(f"unregistered verification predicate: {predicate_id}")
        return bool(predicate(evidence))


class GoalPlanDispatcher:
    """Dispatch one ready plan node; scheduling remains outside this class."""

    def __init__(
        self,
        *,
        store: GoalStore,
        capability_runtime: GovernedCapabilityRuntime,
        verification_registry: VerificationRegistry,
        acquire_capability: Callable[[PlanNodeV1], dict[str, object]] | None = None,
        clarify: Callable[[PlanNodeV1], dict[str, object]] | None = None,
        monitor: Callable[[PlanNodeV1], dict[str, object]] | None = None,
        subgoal: Callable[[PlanNodeV1], dict[str, object]] | None = None,
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        if not callable(getattr(capability_runtime, "execute", None)):
            raise TypeError("capability_runtime must provide execute()")
        if not isinstance(verification_registry, VerificationRegistry):
            raise TypeError("verification_registry must be VerificationRegistry")
        self._store = store
        self._runtime = capability_runtime
        self._verification = verification_registry
        self._acquire = acquire_capability
        self._clarify = clarify
        self._monitor = monitor
        self._subgoal = subgoal

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
            by_id[node_id].state is PlanNodeState.SUCCEEDED
            for node_id in updated.completion_node_ids
        ):
            candidate = updated
            for node in tuple(candidate.nodes):
                if node.state is PlanNodeState.PENDING:
                    return candidate
            final = candidate.with_node_state(
                node_id,
                PlanNodeState.SUCCEEDED,
                plan_state=PlanState.SUCCEEDED,
            )
            updated = self._store.update_plan_execution(
                final,
                expected_digest=candidate.digest,
            )
        return updated

    def dispatch(
        self,
        *,
        plan_id: str,
        node_id: str,
        session_id: str,
        state_fingerprint: str | None = None,
    ) -> PlanDispatchResult:
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise GoalStoreError(f"unknown plan_id: {plan_id}")
        node = self._node(plan, node_id)
        if node not in self.ready_nodes(plan):
            return PlanDispatchResult(
                plan=plan,
                node=node,
                disposition=PlanDispatchDisposition.BLOCKED,
                reason="plan node is not ready",
            )

        running = self._update_node(
            plan,
            node.node_id,
            PlanNodeState.RUNNING,
            plan_state=PlanState.ACTIVE,
        )
        node = self._node(running, node.node_id)

        if node.node_type in {PlanNodeType.ACTION, PlanNodeType.OBSERVE}:
            assert node.capability_key is not None
            assert node.operation is not None
            action_fingerprint = canonical_digest(
                {
                    "capability_key": node.capability_key,
                    "operation": node.operation,
                    "parameters": node.parameters,
                }
            )
            state_key = str(state_fingerprint or "").strip().casefold()
            if node.node_type is PlanNodeType.ACTION and not state_key:
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
                    reason="ACTION requires a pre-action state fingerprint",
                )
            if node.node_type is PlanNodeType.ACTION and self._store.has_no_progress(
                goal_id=running.goal_id,
                action_fingerprint=action_fingerprint,
                state_fingerprint=state_key,
            ):
                failed = self._update_node(
                    running,
                    node.node_id,
                    PlanNodeState.FAILED,
                    plan_state=PlanState.FAILED,
                )
                return PlanDispatchResult(
                    plan=failed,
                    node=self._node(failed, node.node_id),
                    disposition=PlanDispatchDisposition.BLOCKED,
                    reason="identical action/state previously made no progress",
                )

            result = self._runtime.execute(
                CapabilityRequest(
                    session_id=session_id,
                    capability_key=node.capability_key,
                    operation=node.operation,
                    parameters=dict(node.parameters),
                    origin=ActionOrigin.MODEL_SUGGESTED,
                )
            )
            evidence_ref = self._record(
                plan=running,
                node=node,
                status=result.status.value,
                payload={
                    "capability_key": result.capability_key,
                    "operation": result.operation,
                    "data": result.data,
                    "reason": result.reason,
                    "provenance": list(result.provenance),
                    "action_fingerprint": action_fingerprint,
                    "state_fingerprint": state_key,
                    "observation": node.node_type is PlanNodeType.OBSERVE,
                },
            )
            if result.status not in {
                CapabilityStatus.SUCCEEDED,
                CapabilityStatus.PARTIAL,
            }:
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
                    reason=result.reason,
                )
            succeeded = self._finalize_success(running, node.node_id)
            return PlanDispatchResult(
                plan=succeeded,
                node=self._node(succeeded, node.node_id),
                disposition=PlanDispatchDisposition.SUCCEEDED,
                evidence_ref=evidence_ref,
            )

        if node.node_type is PlanNodeType.VERIFY:
            assert node.postcondition_ref is not None
            evidence = self._store.list_plan_node_results(
                plan_id=running.plan_id,
                limit=1000,
            )
            passed = self._verification.evaluate(node.postcondition_ref, evidence)
            evidence_ref = self._record(
                plan=running,
                node=node,
                status="verified" if passed else "not_verified",
                payload={
                    "postcondition_ref": node.postcondition_ref,
                    "passed": passed,
                    "evidence_result_ids": [
                        str(item["result_id"]) for item in evidence
                    ],
                },
            )
            if not passed:
                for predecessor_id in self._predecessor_ids(running, node.node_id):
                    predecessor = self._node(running, predecessor_id)
                    if predecessor.node_type is not PlanNodeType.ACTION:
                        continue
                    results = self._store.list_plan_node_results(
                        plan_id=running.plan_id,
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
                            goal_id=running.goal_id,
                            plan_id=running.plan_id,
                            node_id=predecessor.node_id,
                            action_fingerprint=action_fp,
                            state_fingerprint=state_fp,
                            reason=(
                                "registered postcondition remained unsatisfied "
                                f"after {predecessor.operation}"
                            ),
                            created_at=datetime.now(UTC).isoformat(),
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
                    reason="registered postcondition was not satisfied",
                )
            succeeded = self._finalize_success(running, node.node_id)
            return PlanDispatchResult(
                plan=succeeded,
                node=self._node(succeeded, node.node_id),
                disposition=PlanDispatchDisposition.SUCCEEDED,
                evidence_ref=evidence_ref,
            )

        callback = {
            PlanNodeType.ACQUIRE_CAPABILITY: self._acquire,
            PlanNodeType.CLARIFY: self._clarify,
            PlanNodeType.MONITOR: self._monitor,
            PlanNodeType.SUBGOAL: self._subgoal,
        }.get(node.node_type)
        if callback is not None:
            payload = callback(node)
            evidence_ref = self._record(
                plan=running,
                node=node,
                status="waiting",
                payload=payload,
            )
            waiting = self._update_node(
                running,
                node.node_id,
                PlanNodeState.WAITING,
                plan_state=PlanState.WAITING,
            )
            return PlanDispatchResult(
                plan=waiting,
                node=self._node(waiting, node.node_id),
                disposition=PlanDispatchDisposition.WAITING,
                evidence_ref=evidence_ref,
            )

        if node.node_type is PlanNodeType.WAIT:
            evidence_ref = self._record(
                plan=running,
                node=node,
                status="waiting",
                payload={"reason": node.summary},
            )
            waiting = self._update_node(
                running,
                node.node_id,
                PlanNodeState.WAITING,
                plan_state=PlanState.WAITING,
            )
            return PlanDispatchResult(
                plan=waiting,
                node=self._node(waiting, node.node_id),
                disposition=PlanDispatchDisposition.WAITING,
                evidence_ref=evidence_ref,
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
            reason=f"no dispatcher registered for {node.node_type.value}",
        )
