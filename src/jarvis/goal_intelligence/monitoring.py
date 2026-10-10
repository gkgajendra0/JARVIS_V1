"""Durable event-first monitoring for conditional GICC goals."""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)
from jarvis.work.models import (
    DeliveryPolicy,
    WorkDeliveryKind,
    WorkPriority,
    WorkState,
    WorkType,
)

from .models import (
    GoalState,
    MonitorPredicateV1,
    PlanNodeState,
    PlanState,
)
from .store import GoalStore, GoalStoreError
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink

LOGGER = logging.getLogger("jarvis.gicc.monitoring")

GICC_MONITOR_EVENT_CONTRACT = "gicc.monitor_observation.v1"


def _monitor_owner_message(
    *,
    kind: OwnerCommunicationKind,
    event_key: str,
    summary: str,
    goal_id: str,
    work_id: str,
    terminal: bool,
    system_outcome_kind: str,
) -> str:
    message = SupervisorOwnerCommunication.compile(
        OwnerCommunicationIntentV1.create(
            kind=kind,
            event_key=event_key,
            summary=summary,
            owner_action_required=False,
            terminal=terminal,
            goal_id=goal_id,
            work_id=work_id,
            system_outcome_kind=system_outcome_kind,
        )
    )
    if message is None:
        raise RuntimeError("Supervisor suppressed required monitoring owner message")
    return message.message


@dataclass(frozen=True, slots=True)
class VerifiedMonitorObservationV1:
    predicate_id: str
    source_capability_key: str
    source_operation: str
    observation_digest: str
    condition_met: bool
    observed_at_epoch: float
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "predicate_id",
            "source_capability_key",
            "source_operation",
            "observation_digest",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value.casefold())
        if not isinstance(self.condition_met, bool):
            raise TypeError("condition_met must be bool")
        observed = float(self.observed_at_epoch)
        if not math.isfinite(observed) or observed < 0:
            raise ValueError("observed_at_epoch must be finite and non-negative")
        object.__setattr__(self, "observed_at_epoch", observed)
        refs = tuple(
            sorted(
                {str(item).strip() for item in self.evidence_refs if str(item).strip()}
            )
        )
        object.__setattr__(self, "evidence_refs", refs)


MonitorObservationSubscriber = Callable[[VerifiedMonitorObservationV1], None]


class MonitorObservationBus:
    """Process-local transport for verified capability observations.

    Publishers provide only typed verdict/evidence references. Raw frames, prompts,
    secrets and owner-facing notification text are deliberately outside this contract.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, MonitorObservationSubscriber] = {}

    def subscribe(self, callback: MonitorObservationSubscriber) -> str:
        if not callable(callback):
            raise TypeError("monitor observation subscriber must be callable")
        subscription_id = f"monitor_sub_{uuid.uuid4().hex}"
        with self._lock:
            self._subscribers[subscription_id] = callback
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> None:
        key = str(subscription_id).strip()
        if not key:
            return
        with self._lock:
            self._subscribers.pop(key, None)

    def publish(self, observation: VerifiedMonitorObservationV1) -> None:
        if not isinstance(observation, VerifiedMonitorObservationV1):
            raise TypeError("observation must be VerifiedMonitorObservationV1")
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for callback in subscribers:
            try:
                callback(observation)
            except Exception:
                LOGGER.exception("GICC monitor observation subscriber failed")


DEFAULT_MONITOR_OBSERVATION_BUS = MonitorObservationBus()


def publish_verified_monitor_observation(
    observation: VerifiedMonitorObservationV1,
) -> None:
    DEFAULT_MONITOR_OBSERVATION_BUS.publish(observation)


class MonitoringStrategy(str, Enum):
    NATIVE_EVENT = "native_event"
    STATE_SUBSCRIPTION = "state_subscription"
    LOCAL_DETECTOR = "local_detector"
    BOUNDED_POLLING = "bounded_polling"
    EXPENSIVE_PERCEPTION = "expensive_perception"


_STRATEGY_ORDER = (
    MonitoringStrategy.NATIVE_EVENT,
    MonitoringStrategy.STATE_SUBSCRIPTION,
    MonitoringStrategy.LOCAL_DETECTOR,
    MonitoringStrategy.BOUNDED_POLLING,
    MonitoringStrategy.EXPENSIVE_PERCEPTION,
)


class WorkStarter(Protocol):
    def start(
        self,
        *,
        request: str,
        work_type: WorkType,
        source_session_id: str,
        source_turn_id: str,
        priority: WorkPriority = WorkPriority.NORMAL,
        delivery_policy: DeliveryPolicy = DeliveryPolicy.WHEN_IDLE,
        dependencies: tuple[str, ...] = (),
    ): ...


class MonitorWorkStore(Protocol):
    def require(self, work_id: str): ...

    def save(self, work, *, expected_version: int): ...

    def enqueue_delivery(
        self,
        *,
        work,
        kind: WorkDeliveryKind,
        message: str,
        event_key: str,
    ): ...


@dataclass(frozen=True, slots=True)
class MonitorStartResult:
    predicate_id: str
    work_id: str
    strategy: MonitoringStrategy
    runtime_state: dict[str, object]


class MonitorObservationDisposition(str, Enum):
    CANCELLED = "cancelled"
    DUPLICATE = "duplicate"
    FALSE = "false"
    STABILIZING = "stabilizing"
    COOLDOWN = "cooldown"
    TRIGGERED = "triggered"
    ALREADY_NOTIFIED = "already_notified"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class MonitorObservationResult:
    disposition: MonitorObservationDisposition
    predicate_id: str
    observation_digest: str
    notification_event_key: str | None
    runtime_state: dict[str, object]


class MonitoringPlanner:
    """Select the cheapest trustworthy verified observation strategy."""

    def choose(
        self,
        predicate: MonitorPredicateV1,
        *,
        available_strategies: tuple[MonitoringStrategy, ...] | list[MonitoringStrategy],
    ) -> MonitoringStrategy:
        if not isinstance(predicate, MonitorPredicateV1):
            raise TypeError("predicate must be MonitorPredicateV1")
        available = set(available_strategies)
        if not available:
            raise ValueError("no verified monitoring strategy is available")
        for strategy in _STRATEGY_ORDER:
            if strategy in available:
                return strategy
        raise ValueError("no supported monitoring strategy is available")


class MonitoringWorkCoordinator:
    """Create/link a durable WorkType.MONITORING item and GICC runtime state."""

    def __init__(
        self,
        *,
        goal_store: GoalStore,
        work_starter: WorkStarter,
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not callable(getattr(work_starter, "start", None)):
            raise TypeError("work_starter must provide start()")
        self._goals = goal_store
        self._work = work_starter

    def start(
        self,
        predicate: MonitorPredicateV1,
        *,
        strategy: MonitoringStrategy,
        continuation_id: str | None = None,
        plan_id: str | None = None,
        node_id: str | None = None,
        delivery_policy: DeliveryPolicy = DeliveryPolicy.WHEN_IDLE,
        now_epoch: float,
    ) -> MonitorStartResult:
        if not isinstance(predicate, MonitorPredicateV1):
            raise TypeError("predicate must be MonitorPredicateV1")
        if not isinstance(strategy, MonitoringStrategy):
            raise TypeError("strategy must be MonitoringStrategy")
        timestamp = float(now_epoch)
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("now_epoch must be finite and non-negative")
        predicate = self._goals.put_monitor_predicate(predicate)
        submission = self._work.start(
            request=f"Monitor GICC predicate {predicate.predicate_id}",
            work_type=WorkType.MONITORING,
            source_session_id=f"gicc-monitor:{predicate.goal_id}",
            source_turn_id=f"predicate:{predicate.predicate_id}",
            delivery_policy=delivery_policy,
        )
        work_id = str(submission.work.work_id)
        existing = self._goals.get_monitor_runtime_state(predicate.predicate_id)
        if existing is None:
            existing = self._goals.create_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                goal_id=predicate.goal_id,
                work_id=work_id,
                payload={
                    "strategy": strategy.value,
                    "continuation_id": continuation_id,
                    "plan_id": None if plan_id is None else str(plan_id).strip(),
                    "node_id": None if node_id is None else str(node_id).strip(),
                    "source_entity_ids": list(predicate.source_entity_ids),
                    "started_at_epoch": timestamp,
                    "last_observation_digest": None,
                    "stable_since_epoch": None,
                    "last_trigger_epoch": None,
                    "notification_event_key": None,
                    "notified": False,
                },
                updated_at=datetime.now(UTC).isoformat(),
            )
        else:
            payload = existing.get("payload")
            if not isinstance(payload, dict):
                raise GoalStoreError("monitor runtime payload is invalid")
            if (
                existing["work_id"] != work_id
                or payload.get("strategy") != strategy.value
                or payload.get("continuation_id") != continuation_id
                or payload.get("plan_id")
                != (None if plan_id is None else str(plan_id).strip())
                or payload.get("node_id")
                != (None if node_id is None else str(node_id).strip())
            ):
                raise GoalStoreError(
                    "existing monitor runtime binding differs from requested monitor"
                )
        return MonitorStartResult(
            predicate_id=predicate.predicate_id,
            work_id=work_id,
            strategy=strategy,
            runtime_state=existing,
        )


class MonitorEventProcessor:
    """Persist debounce/cooldown/notification state before the next event."""

    def __init__(
        self,
        *,
        goal_store: GoalStore,
        work_store: MonitorWorkStore,
        telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if (
            not callable(getattr(work_store, "require", None))
            or not callable(getattr(work_store, "save", None))
            or not callable(getattr(work_store, "enqueue_delivery", None))
        ):
            raise TypeError("work_store must provide require/save/enqueue_delivery")
        self._goals = goal_store
        self._work = work_store
        if not callable(getattr(telemetry, "emit", None)):
            raise TypeError("telemetry must provide emit()")
        self._telemetry = telemetry

    def _advance_bound_plan(
        self,
        *,
        predicate: MonitorPredicateV1,
        runtime_payload: dict[str, object],
        succeeded: bool,
    ) -> None:
        plan_id = str(runtime_payload.get("plan_id") or "").strip()
        node_id = str(runtime_payload.get("node_id") or "").strip()
        if not plan_id or not node_id:
            return
        plan = self._goals.get_plan(plan_id)
        if plan is None:
            raise GoalStoreError(f"monitor plan is missing: {plan_id}")
        node = next((item for item in plan.nodes if item.node_id == node_id), None)
        if node is None:
            raise GoalStoreError(f"monitor node is missing from plan: {node_id}")

        if succeeded:
            tentative = plan.with_node_state(
                node_id,
                PlanNodeState.SUCCEEDED,
                plan_state=PlanState.ACTIVE,
            )
            by_id = {item.node_id: item for item in tentative.nodes}
            complete = all(
                by_id[completion_id].state is PlanNodeState.SUCCEEDED
                for completion_id in tentative.completion_node_ids
            )
            updated = (
                tentative.with_node_state(
                    node_id,
                    PlanNodeState.SUCCEEDED,
                    plan_state=PlanState.SUCCEEDED,
                )
                if complete
                else tentative
            )
        else:
            updated = plan.with_node_state(
                node_id,
                PlanNodeState.FAILED,
                plan_state=PlanState.FAILED,
            )
        saved = self._goals.update_plan_execution(
            updated,
            expected_digest=plan.digest,
        )

        goal = self._goals.get_goal(predicate.goal_id)
        if goal is None:
            raise GoalStoreError(f"monitor goal is missing: {predicate.goal_id}")
        next_state = (
            GoalState.COMPLETED
            if saved.state is PlanState.SUCCEEDED
            else (GoalState.PLANNED if succeeded else GoalState.FAILED)
        )
        if goal.state is not next_state:
            self._goals.update_goal_state(
                goal.goal_id,
                next_state,
                expected_revision=goal.goal_revision,
            )

    def _finish_work(
        self,
        *,
        work_id: str,
        state: WorkState,
        status_detail: str,
        result: dict[str, object],
    ):
        work = self._work.require(work_id)
        if work.state.terminal:
            return work
        if state is WorkState.COMPLETED and work.state is not WorkState.RUNNING:
            running = work.transition(
                WorkState.RUNNING,
                status_detail="monitor condition is being finalized",
                current_step_id=work.current_step_id,
            )
            work = self._work.save(running, expected_version=work.version)
        updated = work.transition(
            state,
            status_detail=status_detail,
            result=result,
        )
        return self._work.save(updated, expected_version=work.version)

    def process(
        self,
        *,
        predicate: MonitorPredicateV1,
        observation_digest: str,
        condition_met: bool,
        observed_at_epoch: float,
        notification_message: str,
        evidence_refs: tuple[str, ...] | list[str] = (),
    ) -> MonitorObservationResult:
        if not isinstance(predicate, MonitorPredicateV1):
            raise TypeError("predicate must be MonitorPredicateV1")
        digest = str(observation_digest).strip().casefold()
        if not digest:
            raise ValueError("observation_digest must not be empty")
        if not isinstance(condition_met, bool):
            raise TypeError("condition_met must be bool")
        observed = float(observed_at_epoch)
        if not math.isfinite(observed) or observed < 0:
            raise ValueError("observed_at_epoch must be finite and non-negative")
        evidence = tuple(
            sorted({str(item).strip() for item in evidence_refs if str(item).strip()})
        )
        state = self._goals.get_monitor_runtime_state(predicate.predicate_id)
        if state is None:
            raise GoalStoreError(
                f"monitor runtime has not started: {predicate.predicate_id}"
            )
        payload = state.get("payload")
        if not isinstance(payload, dict):
            raise GoalStoreError("monitor runtime payload is invalid")

        owner_goal = self._goals.get_goal(predicate.goal_id)
        if owner_goal is None:
            raise GoalStoreError("monitor owner goal is missing")
        if owner_goal.state is GoalState.CANCELLED:
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.CANCELLED,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=None,
                runtime_state=state,
            )

        if payload.get("last_observation_digest") == digest:
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.DUPLICATE,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=(
                    str(payload["notification_event_key"])
                    if payload.get("notification_event_key")
                    else None
                ),
                runtime_state=state,
            )

        started = float(payload.get("started_at_epoch") or 0.0)
        if predicate.timeout is not None and observed - started >= predicate.timeout:
            updated_payload = {
                **payload,
                "last_observation_digest": digest,
                "last_evidence_refs": list(evidence),
            }
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload=updated_payload,
                updated_at=datetime.now(UTC).isoformat(),
            )
            work = self._finish_work(
                work_id=str(state["work_id"]),
                state=WorkState.FAILED,
                status_detail="monitor timed out before condition verification",
                result={
                    "predicate_id": predicate.predicate_id,
                    "outcome": "timed_out",
                    "observation_digest": digest,
                },
            )
            timeout_event_key = f"gicc-monitor:{predicate.predicate_id}:timeout"
            self._work.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.FAILURE,
                message=_monitor_owner_message(
                    kind=OwnerCommunicationKind.FAILURE,
                    event_key=timeout_event_key,
                    summary=(
                        "Monitoring stopped because the condition was not verified "
                        "in time."
                    ),
                    goal_id=predicate.goal_id,
                    work_id=work.work_id,
                    terminal=True,
                    system_outcome_kind="terminal",
                ),
                event_key=timeout_event_key,
            )
            self._advance_bound_plan(
                predicate=predicate,
                runtime_payload=updated_payload,
                succeeded=False,
            )
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.TIMED_OUT,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=None,
                runtime_state=updated,
            )

        if not condition_met:
            updated_payload = {
                **payload,
                "last_observation_digest": digest,
                "last_evidence_refs": list(evidence),
                "stable_since_epoch": None,
            }
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload=updated_payload,
                updated_at=datetime.now(UTC).isoformat(),
            )
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.FALSE,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=None,
                runtime_state=updated,
            )

        stable_since = payload.get("stable_since_epoch")
        stable_value = observed if stable_since is None else float(stable_since)
        if observed - stable_value < predicate.stability_window:
            updated_payload = {
                **payload,
                "last_observation_digest": digest,
                "last_evidence_refs": list(evidence),
                "stable_since_epoch": stable_value,
            }
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload=updated_payload,
                updated_at=datetime.now(UTC).isoformat(),
            )
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.STABILIZING,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=None,
                runtime_state=updated,
            )

        if predicate.completion_policy == "complete_once" and bool(
            payload.get("notified")
        ):
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload={
                    **payload,
                    "last_observation_digest": digest,
                    "last_evidence_refs": list(evidence),
                    "stable_since_epoch": stable_value,
                },
                updated_at=datetime.now(UTC).isoformat(),
            )
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.ALREADY_NOTIFIED,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=(
                    str(payload["notification_event_key"])
                    if payload.get("notification_event_key")
                    else None
                ),
                runtime_state=updated,
            )

        last_trigger = payload.get("last_trigger_epoch")
        if (
            last_trigger is not None
            and observed - float(last_trigger) < predicate.cooldown
        ):
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload={
                    **payload,
                    "last_observation_digest": digest,
                    "last_evidence_refs": list(evidence),
                    "stable_since_epoch": stable_value,
                },
                updated_at=datetime.now(UTC).isoformat(),
            )
            return MonitorObservationResult(
                disposition=MonitorObservationDisposition.COOLDOWN,
                predicate_id=predicate.predicate_id,
                observation_digest=digest,
                notification_event_key=None,
                runtime_state=updated,
            )

        event_key = (
            f"gicc-monitor:{predicate.predicate_id}:complete"
            if predicate.completion_policy == "complete_once"
            else f"gicc-monitor:{predicate.predicate_id}:{digest}"
        )
        work = self._work.require(str(state["work_id"]))
        if predicate.notification_policy != "none":
            completes_goal = predicate.completion_policy == "complete_once"
            self._work.enqueue_delivery(
                work=work,
                kind=(
                    WorkDeliveryKind.COMPLETION
                    if completes_goal
                    else WorkDeliveryKind.PROGRESS
                ),
                message=_monitor_owner_message(
                    kind=(
                        OwnerCommunicationKind.COMPLETION
                        if completes_goal
                        else OwnerCommunicationKind.PROGRESS
                    ),
                    event_key=event_key,
                    summary=str(notification_message).strip(),
                    goal_id=predicate.goal_id,
                    work_id=work.work_id,
                    terminal=completes_goal,
                    system_outcome_kind=(
                        "completed" if completes_goal else "in_progress"
                    ),
                ),
                event_key=event_key,
            )
        updated = self._goals.update_monitor_runtime_state(
            predicate_id=predicate.predicate_id,
            expected_revision=int(state["revision"]),
            runtime_payload={
                **payload,
                "last_observation_digest": digest,
                "last_evidence_refs": list(evidence),
                "stable_since_epoch": stable_value,
                "last_trigger_epoch": observed,
                "notification_event_key": event_key,
                "notified": True,
            },
            updated_at=datetime.now(UTC).isoformat(),
        )
        if predicate.completion_policy == "complete_once":
            self._finish_work(
                work_id=str(state["work_id"]),
                state=WorkState.COMPLETED,
                status_detail="monitor condition verified",
                result={
                    "predicate_id": predicate.predicate_id,
                    "outcome": "triggered",
                    "observation_digest": digest,
                    "notification_event_key": event_key,
                    "evidence_refs": list(evidence),
                },
            )
            self._advance_bound_plan(
                predicate=predicate,
                runtime_payload=updated["payload"],
                succeeded=True,
            )
        self._telemetry.emit(
            "gicc_monitor_triggered",
            goal_id=predicate.goal_id,
            predicate_id=predicate.predicate_id,
            work_id=str(state["work_id"]),
            observation_digest=digest,
            notification_event_key=event_key,
            strategy=str(payload.get("strategy") or "unknown"),
        )
        return MonitorObservationResult(
            disposition=MonitorObservationDisposition.TRIGGERED,
            predicate_id=predicate.predicate_id,
            observation_digest=digest,
            notification_event_key=event_key,
            runtime_state=updated,
        )


@dataclass(frozen=True, slots=True)
class MonitoringDispatchReceipt:
    work_id: str
    route: str = "work_monitoring"


class GoalMonitoringDispatcher:
    """Adapter from a validated MONITOR plan node to durable monitoring Work."""

    def __init__(
        self,
        *,
        coordinator: MonitoringWorkCoordinator,
        available_strategies: tuple[MonitoringStrategy, ...] | list[MonitoringStrategy],
        planner: MonitoringPlanner | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(coordinator, MonitoringWorkCoordinator):
            raise TypeError("coordinator must be MonitoringWorkCoordinator")
        if not callable(now_epoch):
            raise TypeError("now_epoch must be callable")
        self._coordinator = coordinator
        self._available = tuple(available_strategies)
        self._planner = planner or MonitoringPlanner()
        self._now_epoch = now_epoch

    def start_monitor(
        self,
        *,
        goal,
        plan,
        node,
        predicate: MonitorPredicateV1,
    ) -> MonitoringDispatchReceipt:
        if predicate.goal_id != goal.goal_id or plan.goal_id != goal.goal_id:
            raise ValueError("monitor predicate/plan must belong to owner goal")
        if node.monitor_predicate_id != predicate.predicate_id:
            raise ValueError("MONITOR node does not bind the supplied predicate")
        if node.node_id not in {item.node_id for item in plan.nodes}:
            raise ValueError("MONITOR node does not belong to supplied plan")
        strategy = self._planner.choose(
            predicate,
            available_strategies=self._available,
        )
        started = self._coordinator.start(
            predicate,
            strategy=strategy,
            plan_id=plan.plan_id,
            node_id=node.node_id,
            now_epoch=float(self._now_epoch()),
        )
        return MonitoringDispatchReceipt(work_id=started.work_id)
