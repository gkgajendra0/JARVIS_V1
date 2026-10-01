"""Durable event-first monitoring for conditional GICC goals."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from jarvis.work.models import (
    DeliveryPolicy,
    WorkDeliveryKind,
    WorkPriority,
    WorkType,
)

from .models import MonitorPredicateV1
from .store import GoalStore, GoalStoreError


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
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not callable(getattr(work_store, "require", None)) or not callable(
            getattr(work_store, "enqueue_delivery", None)
        ):
            raise TypeError("work_store must provide require/enqueue_delivery")
        self._goals = goal_store
        self._work = work_store

    def process(
        self,
        *,
        predicate: MonitorPredicateV1,
        observation_digest: str,
        condition_met: bool,
        observed_at_epoch: float,
        notification_message: str,
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
        state = self._goals.get_monitor_runtime_state(predicate.predicate_id)
        if state is None:
            raise GoalStoreError(
                f"monitor runtime has not started: {predicate.predicate_id}"
            )
        payload = state.get("payload")
        if not isinstance(payload, dict):
            raise GoalStoreError("monitor runtime payload is invalid")

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
            }
            updated = self._goals.update_monitor_runtime_state(
                predicate_id=predicate.predicate_id,
                expected_revision=int(state["revision"]),
                runtime_payload=updated_payload,
                updated_at=datetime.now(UTC).isoformat(),
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
            self._work.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.COMPLETION,
                message=str(notification_message).strip(),
                event_key=event_key,
            )
        updated = self._goals.update_monitor_runtime_state(
            predicate_id=predicate.predicate_id,
            expected_revision=int(state["revision"]),
            runtime_payload={
                **payload,
                "last_observation_digest": digest,
                "stable_since_epoch": stable_value,
                "last_trigger_epoch": observed,
                "notification_event_key": event_key,
                "notified": True,
            },
            updated_at=datetime.now(UTC).isoformat(),
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
            now_epoch=float(self._now_epoch()),
        )
        return MonitoringDispatchReceipt(work_id=started.work_id)
