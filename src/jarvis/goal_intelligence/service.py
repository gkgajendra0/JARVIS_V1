"""Goal-level coordination over existing governed JARVIS subsystems.

GoalOrchestrator never executes arbitrary code and never grants Authority.  It routes one
validated PlanNode at a time to the canonical subsystem that already owns that work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityRequest, CapabilityResult

from .information import InformationResolutionState, InformationResolver
from .models import (
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from .phase9 import Phase9GapAdmission, Phase9GoalBridge
from .planning import PlanProgressGuard
from .store import GoalStore, GoalStoreError
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink


class GoalDispatchStatus(str, Enum):
    SUCCEEDED = "succeeded"
    WAITING = "waiting"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    verified: bool
    reason: str
    evidence_refs: tuple[str, ...] = ()


class GovernedCapabilityRuntime(Protocol):
    def execute(self, request: CapabilityRequest) -> CapabilityResult: ...


class VerificationRegistry:
    """Release-owned deterministic/bounded verification callbacks."""

    def __init__(self) -> None:
        self._evaluators: dict[
            str,
            Callable[[dict[str, object]], bool | VerificationOutcome],
        ] = {}

    def register(self, predicate_ref: str, evaluator) -> None:
        key = str(predicate_ref).strip()
        if not key:
            raise ValueError("predicate_ref must not be empty")
        if not callable(evaluator):
            raise TypeError("verification evaluator must be callable")
        if key in self._evaluators:
            raise ValueError(f"duplicate verification predicate: {key}")
        self._evaluators[key] = evaluator

    def evaluate(
        self,
        predicate_ref: str,
        evidence: dict[str, object],
    ) -> VerificationOutcome:
        key = str(predicate_ref).strip()
        evaluator = self._evaluators.get(key)
        if evaluator is None:
            return VerificationOutcome(
                verified=False,
                reason="verification predicate has no registered evaluator",
            )
        result = evaluator(dict(evidence))
        if isinstance(result, VerificationOutcome):
            return result
        if isinstance(result, bool):
            return VerificationOutcome(
                verified=result,
                reason="deterministic verifier returned true"
                if result
                else "deterministic verifier returned false",
            )
        raise TypeError(
            "verification evaluator must return bool or VerificationOutcome"
        )


@dataclass(frozen=True, slots=True)
class WorkDispatchReceipt:
    work_id: str
    route: str

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("work_id must not be empty")
        if not self.route.strip():
            raise ValueError("route must not be empty")


class WaitNodeDispatcher(Protocol):
    def start_wait(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        node: PlanNodeV1,
    ) -> WorkDispatchReceipt: ...


class MonitorNodeDispatcher(Protocol):
    def start_monitor(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        node: PlanNodeV1,
        predicate: MonitorPredicateV1,
    ) -> WorkDispatchReceipt: ...


class SubgoalNodeDispatcher(Protocol):
    def start_subgoal(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        node: PlanNodeV1,
        subgoal_id: str,
    ) -> WorkDispatchReceipt: ...


@dataclass(frozen=True, slots=True)
class PlanDispatchResult:
    node_id: str
    node_type: PlanNodeType
    status: GoalDispatchStatus
    route: str
    result_ref: str | None = None
    capability_result: CapabilityResult | None = None
    phase9_admission: Phase9GapAdmission | None = None
    interaction: dict[str, object] | None = None
    verification: VerificationOutcome | None = None


class GoalOrchestrator:
    """Route validated GICC plan nodes into existing canonical subsystems."""

    def __init__(
        self,
        *,
        goal_store: GoalStore,
        capability_runtime: GovernedCapabilityRuntime,
        information_resolver: InformationResolver | None = None,
        phase9_bridge: Phase9GoalBridge | None = None,
        verification_registry: VerificationRegistry | None = None,
        wait_dispatcher: WaitNodeDispatcher | None = None,
        monitor_dispatcher: MonitorNodeDispatcher | None = None,
        subgoal_dispatcher: SubgoalNodeDispatcher | None = None,
        progress_guard: PlanProgressGuard | None = None,
        telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not callable(getattr(capability_runtime, "execute", None)):
            raise TypeError("capability_runtime must provide execute()")
        self._store = goal_store
        self._capabilities = capability_runtime
        self._information = information_resolver
        self._phase9 = phase9_bridge
        self._verification = verification_registry or VerificationRegistry()
        self._wait = wait_dispatcher
        self._monitor = monitor_dispatcher
        self._subgoal = subgoal_dispatcher
        self._progress = progress_guard
        if not callable(getattr(telemetry, "emit", None)):
            raise TypeError("telemetry must provide emit()")
        self._telemetry = telemetry

    @staticmethod
    def ready_nodes(
        plan: PlanGraphV1,
        *,
        succeeded_node_ids: tuple[str, ...] | set[str] = (),
        blocked_node_ids: tuple[str, ...] | set[str] = (),
    ) -> tuple[PlanNodeV1, ...]:
        succeeded = set(succeeded_node_ids)
        blocked = set(blocked_node_ids)
        node_ids = {node.node_id for node in plan.nodes}
        if not succeeded.issubset(node_ids) or not blocked.issubset(node_ids):
            raise ValueError("plan execution state references unknown node")
        parents: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for source, target in plan.edges:
            parents[target].add(source)
        return tuple(
            sorted(
                (
                    node
                    for node in plan.nodes
                    if node.node_id not in succeeded
                    and node.node_id not in blocked
                    and parents[node.node_id].issubset(succeeded)
                ),
                key=lambda item: item.node_id,
            )
        )

    def dispatch_node(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        node: PlanNodeV1,
        verification_evidence: dict[str, object] | None = None,
        observed_state_digest: str | None = None,
    ) -> PlanDispatchResult:
        if goal.goal_id != plan.goal_id:
            raise ValueError("plan does not belong to owner goal")
        if node.node_id not in {item.node_id for item in plan.nodes}:
            raise ValueError("node does not belong to plan")
        self._telemetry.emit(
            "gicc_plan_node_dispatched",
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            node_id=node.node_id,
            node_type=node.node_type.value,
        )

        if node.node_type in {PlanNodeType.ACTION, PlanNodeType.OBSERVE}:
            if self._progress is not None:
                if observed_state_digest is None:
                    raise ValueError(
                        "progress-guarded action requires observed_state_digest"
                    )
                self._progress.admit_action(
                    node,
                    observed_state_digest=observed_state_digest,
                )
            assert node.capability_key is not None
            assert node.operation is not None
            result = self._capabilities.execute(
                CapabilityRequest(
                    session_id=goal.source_session_id,
                    capability_key=node.capability_key,
                    operation=node.operation,
                    parameters=dict(node.parameters),
                    origin=ActionOrigin.MODEL_SUGGESTED,
                )
            )
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=(
                    GoalDispatchStatus.SUCCEEDED
                    if result.ok
                    else GoalDispatchStatus.FAILED
                ),
                route="capability_runtime",
                result_ref=f"capability_result:{node.node_id}",
                capability_result=result,
            )

        if node.node_type is PlanNodeType.ACQUIRE_CAPABILITY:
            if self._phase9 is None:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.BLOCKED,
                    route="phase9",
                )
            assert node.gap_id is not None
            gap = self._store.get_gap(node.gap_id)
            if gap is None:
                raise GoalStoreError(f"unknown capability gap: {node.gap_id}")
            admitted = self._phase9.admit_gap(gap, goal)
            admission = admitted.admission
            work_id = getattr(admission, "acquisition_work_id", None)
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=(
                    GoalDispatchStatus.WAITING
                    if work_id is not None
                    else GoalDispatchStatus.SUCCEEDED
                ),
                route="phase9",
                result_ref=work_id,
                phase9_admission=admitted,
            )

        if node.node_type is PlanNodeType.CLARIFY:
            if self._information is None:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.BLOCKED,
                    route="information_need",
                )
            assert node.information_need_id is not None
            need = self._store.get_information_need(node.information_need_id)
            if need is None:
                raise GoalStoreError(
                    f"unknown information_need_id: {node.information_need_id}"
                )
            resolution = self._information.resolve(need)
            if resolution.state is InformationResolutionState.RESOLVED:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.SUCCEEDED,
                    route="information_need",
                    result_ref=resolution.need.resolution_ref,
                )
            if resolution.state is InformationResolutionState.NEEDS_OWNER:
                interaction = resolution.interaction
                assert interaction is not None
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.WAITING,
                    route="information_need",
                    result_ref=str(interaction["interaction_id"]),
                    interaction=interaction,
                )
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=GoalDispatchStatus.BLOCKED,
                route="information_need",
            )

        if node.node_type is PlanNodeType.VERIFY:
            assert node.postcondition_ref is not None
            outcome = self._verification.evaluate(
                node.postcondition_ref,
                verification_evidence or {},
            )
            self._telemetry.emit(
                "gicc_postcondition_verified",
                goal_id=goal.goal_id,
                plan_id=plan.plan_id,
                node_id=node.node_id,
                predicate_ref=node.postcondition_ref,
                verified=outcome.verified,
                evidence_count=len(outcome.evidence_refs),
                reason_code=("verified" if outcome.verified else "verification_failed"),
            )
            if (
                outcome.verified
                and len(plan.completion_node_ids) == 1
                and node.node_id == plan.completion_node_ids[0]
            ):
                self._telemetry.emit(
                    "gicc_goal_completed",
                    goal_id=goal.goal_id,
                    plan_id=plan.plan_id,
                    plan_revision=plan.plan_revision,
                    completion_node_id=node.node_id,
                )
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=(
                    GoalDispatchStatus.SUCCEEDED
                    if outcome.verified
                    else GoalDispatchStatus.FAILED
                ),
                route="verification",
                result_ref=node.postcondition_ref,
                verification=outcome,
            )

        if node.node_type is PlanNodeType.WAIT:
            if self._wait is None:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.BLOCKED,
                    route="work_wait",
                )
            receipt = self._wait.start_wait(goal=goal, plan=plan, node=node)
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=GoalDispatchStatus.WAITING,
                route=receipt.route,
                result_ref=receipt.work_id,
            )

        if node.node_type is PlanNodeType.MONITOR:
            if self._monitor is None:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.BLOCKED,
                    route="work_monitoring",
                )
            assert node.monitor_predicate_id is not None
            predicate = self._store.get_monitor_predicate(node.monitor_predicate_id)
            if predicate is None:
                raise GoalStoreError(
                    f"unknown monitor predicate: {node.monitor_predicate_id}"
                )
            receipt = self._monitor.start_monitor(
                goal=goal,
                plan=plan,
                node=node,
                predicate=predicate,
            )
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=GoalDispatchStatus.WAITING,
                route=receipt.route,
                result_ref=receipt.work_id,
            )

        if node.node_type is PlanNodeType.SUBGOAL:
            if self._subgoal is None:
                return PlanDispatchResult(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    status=GoalDispatchStatus.BLOCKED,
                    route="subgoal",
                )
            assert node.subgoal_id is not None
            receipt = self._subgoal.start_subgoal(
                goal=goal,
                plan=plan,
                node=node,
                subgoal_id=node.subgoal_id,
            )
            return PlanDispatchResult(
                node_id=node.node_id,
                node_type=node.node_type,
                status=GoalDispatchStatus.WAITING,
                route=receipt.route,
                result_ref=receipt.work_id,
            )

        raise ValueError(f"unsupported plan node type: {node.node_type.value}")
