from pathlib import Path
from types import SimpleNamespace

from jarvis.goal_intelligence.models import (
    GoalKind,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.monitoring import (
    GoalMonitoringDispatcher,
    MonitorEventProcessor,
    MonitoringPlanner,
    MonitoringStrategy,
    MonitoringWorkCoordinator,
    MonitorObservationDisposition,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeWorkStarter:
    def __init__(self) -> None:
        self.by_source = {}
        self.calls = []

    def start(
        self,
        *,
        request,
        work_type,
        source_session_id,
        source_turn_id,
        priority=None,
        delivery_policy=None,
        dependencies=(),
    ):
        key = (source_session_id, source_turn_id, work_type)
        self.calls.append(
            {
                "request": request,
                "work_type": work_type,
                "source_session_id": source_session_id,
                "source_turn_id": source_turn_id,
            }
        )
        work = self.by_source.setdefault(
            key,
            SimpleNamespace(work_id=f"work-{len(self.by_source) + 1}"),
        )
        return SimpleNamespace(work=work, execution_id=work.work_id)


class FakeMonitorWorkStore:
    def __init__(self) -> None:
        self.works = {}
        self.deliveries = []

    def add(self, work_id: str) -> None:
        self.works[work_id] = WorkItem(
            work_id=work_id,
            request="Monitor synthetic predicate.",
            work_type=WorkType.MONITORING,
            source_session_id="monitor-session",
            source_turn_id="monitor-turn",
            state=WorkState.WAITING_RESOURCE,
        )

    def require(self, work_id: str):
        return self.works[work_id]

    def save(self, work, *, expected_version: int):
        current = self.works[work.work_id]
        assert current.version == expected_version
        self.works[work.work_id] = work
        return work

    def enqueue_delivery(self, *, work, kind, message, event_key):
        self.deliveries.append(
            {
                "work_id": work.work_id,
                "kind": kind,
                "message": message,
                "event_key": event_key,
            }
        )


def _store(tmp_path: Path) -> tuple[GoalStore, OwnerGoalV2]:
    store = GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"m" * 32),
        )
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="monitor-session",
            source_turn_id="monitor-turn",
            exact_owner_request="Tell me when a delivery agent is at the main gate.",
            goal_kind=GoalKind.MONITORING,
            desired_outcome="Notify me when a delivery agent is verified at the gate.",
            created_at="2026-10-01T16:00:00+00:00",
        )
    )
    return store, goal


def _predicate(goal: OwnerGoalV2, *, stability_window: float = 0.0):
    return MonitorPredicateV1.create(
        goal_id=goal.goal_id,
        source_entity_ids=("main_gate_camera",),
        observation_capabilities=("camera.observe", "vision.perceive"),
        semantic_condition="delivery agent with package is present at main gate",
        candidate_trigger_strategy="motion_event",
        stability_window=stability_window,
        cooldown=30.0,
        timeout=3600.0,
        completion_policy="complete_once",
        notification_policy="owner",
        verification_requirement="person_and_package_verified",
    )


def test_monitoring_planner_prefers_cheapest_available_verified_strategy(
    tmp_path: Path,
) -> None:
    _, goal = _store(tmp_path)
    predicate = _predicate(goal)

    selected = MonitoringPlanner().choose(
        predicate,
        available_strategies=(
            MonitoringStrategy.EXPENSIVE_PERCEPTION,
            MonitoringStrategy.LOCAL_DETECTOR,
            MonitoringStrategy.NATIVE_EVENT,
        ),
    )

    assert selected is MonitoringStrategy.NATIVE_EVENT


def test_monitor_runtime_survives_restart_with_exact_binding(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    predicate = _predicate(goal)
    work = FakeWorkStarter()
    first = MonitoringWorkCoordinator(goal_store=store, work_starter=work).start(
        predicate,
        strategy=MonitoringStrategy.NATIVE_EVENT,
        now_epoch=100.0,
    )
    second = MonitoringWorkCoordinator(goal_store=store, work_starter=work).start(
        predicate,
        strategy=MonitoringStrategy.NATIVE_EVENT,
        now_epoch=150.0,
    )

    assert first.work_id == second.work_id
    state = store.get_monitor_runtime_state(predicate.predicate_id)
    assert state is not None
    payload = state["payload"]
    assert isinstance(payload, dict)
    assert payload["strategy"] == MonitoringStrategy.NATIVE_EVENT.value
    assert payload["source_entity_ids"] == ["main_gate_camera"]


def test_duplicate_events_and_notifications_are_idempotent(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    predicate = _predicate(goal)
    work_starter = FakeWorkStarter()
    started = MonitoringWorkCoordinator(
        goal_store=store,
        work_starter=work_starter,
    ).start(
        predicate,
        strategy=MonitoringStrategy.LOCAL_DETECTOR,
        now_epoch=100.0,
    )
    work_store = FakeMonitorWorkStore()
    work_store.add(started.work_id)
    processor = MonitorEventProcessor(goal_store=store, work_store=work_store)

    first = processor.process(
        predicate=predicate,
        observation_digest="frame-a",
        condition_met=True,
        observed_at_epoch=101.0,
        notification_message="Delivery agent verified at the main gate.",
    )
    duplicate = processor.process(
        predicate=predicate,
        observation_digest="frame-a",
        condition_met=True,
        observed_at_epoch=102.0,
        notification_message="Delivery agent verified at the main gate.",
    )
    later = processor.process(
        predicate=predicate,
        observation_digest="frame-b",
        condition_met=True,
        observed_at_epoch=140.0,
        notification_message="Delivery agent verified at the main gate.",
    )

    assert first.disposition is MonitorObservationDisposition.TRIGGERED
    assert duplicate.disposition is MonitorObservationDisposition.DUPLICATE
    assert later.disposition is MonitorObservationDisposition.ALREADY_NOTIFIED
    assert len(work_store.deliveries) == 1
    assert (
        work_store.deliveries[0]["event_key"]
        == f"gicc-monitor:{predicate.predicate_id}:complete"
    )


def test_monitor_dispatcher_links_validated_monitor_node_to_work(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    predicate = store.put_monitor_predicate(_predicate(goal))
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.MONITOR,
        summary="Monitor the main gate predicate.",
        monitor_predicate_id=predicate.predicate_id,
    )
    plan = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(node,),
        edges=(),
        root_node_ids=(node.node_id,),
        completion_node_ids=(node.node_id,),
        created_at="2026-10-01T16:01:00+00:00",
    )
    work = FakeWorkStarter()
    dispatcher = GoalMonitoringDispatcher(
        coordinator=MonitoringWorkCoordinator(
            goal_store=store,
            work_starter=work,
        ),
        available_strategies=(
            MonitoringStrategy.EXPENSIVE_PERCEPTION,
            MonitoringStrategy.NATIVE_EVENT,
        ),
        now_epoch=lambda: 200.0,
    )

    receipt = dispatcher.start_monitor(
        goal=goal,
        plan=plan,
        node=node,
        predicate=predicate,
    )

    assert receipt.route == "work_monitoring"
    assert receipt.work_id == "work-1"
    state = store.get_monitor_runtime_state(predicate.predicate_id)
    assert state is not None
    payload = state["payload"]
    assert isinstance(payload, dict)
    assert payload["strategy"] == MonitoringStrategy.NATIVE_EVENT.value
