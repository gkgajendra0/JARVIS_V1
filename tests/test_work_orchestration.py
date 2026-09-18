from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.work.brain import (
    BrainAction,
    BrainCoordinator,
    BrainDecision,
    BrainPreempted,
    BrainRequest,
    InteractiveBrainGate,
)
from jarvis.work.engine import (
    WorkActionRegistry,
    WorkEngine,
    WorkOwnerInputRequired,
)
from jarvis.work.models import (
    DeliveryPolicy,
    WorkDeliveryKind,
    WorkItem,
    WorkPriority,
    WorkState,
    WorkStep,
    WorkType,
)
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore, WorkStoreError


class ScriptedReasoner:
    def __init__(self) -> None:
        self.decisions: dict[str, list[BrainDecision]] = {}
        self.active = 0
        self.max_active = 0

    async def decide(self, request: BrainRequest) -> BrainDecision:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return self.decisions[request.work.work_id].pop(0)
        finally:
            self.active -= 1


class ConcurrentExecutor:
    descriptor = BrainAction(
        name="do_step",
        description="Execute one test step",
        parameter_schema={"type": "object"},
    )
    work_types = frozenset({WorkType.GENERIC})

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
        del parameters
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.04)
            return {"work_id": work.work_id, "verified": True}
        finally:
            self.active -= 1


class FakeBackend:
    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: list[str] = []
        self.paused: list[str] = []
        self.resumed: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id

    def cancel(self, execution_id: str) -> None:
        self.cancelled.append(execution_id)

    def pause(self, execution_id: str) -> None:
        self.paused.append(execution_id)

    def resume(self, execution_id: str) -> None:
        self.resumed.append(execution_id)


def create_item(store: SQLiteWorkStore, *, request: str = "Do work") -> WorkItem:
    item = WorkItem(
        request=request,
        work_type=WorkType.GENERIC,
        source_session_id="session-1",
        source_turn_id="turn-1",
    )
    store.create(item)
    return item


def test_work_state_rejects_invalid_terminal_transition() -> None:
    item = WorkItem(
        request="Research X",
        work_type=WorkType.RESEARCH,
        source_session_id="session-1",
        source_turn_id="turn-1",
    )
    running = item.transition(WorkState.RUNNING)
    completed = running.transition(WorkState.COMPLETED, result={"ok": True})
    with pytest.raises(ValueError, match="invalid work transition"):
        completed.transition(WorkState.RUNNING)


def test_sqlite_store_survives_reopen_and_rejects_stale_update(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite"
    store = SQLiteWorkStore(path)
    item = create_item(store)
    running = item.transition(WorkState.RUNNING, status_detail="started")
    store.save(running, expected_version=item.version)

    reopened = SQLiteWorkStore(path)
    recovered = reopened.require(item.work_id)
    assert recovered.state is WorkState.RUNNING
    assert recovered.status_detail == "started"
    assert recovered.version == 2

    with pytest.raises(WorkStoreError, match="stale work update rejected"):
        reopened.save(
            recovered.with_progress(status_detail="stale write"),
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_single_brain_can_control_multiple_concurrent_work_items(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()
    brain = BrainCoordinator(reasoner)
    executor = ConcurrentExecutor()
    engine = WorkEngine(
        store=store,
        brain=brain,
        actions=WorkActionRegistry((executor,)),
    )
    first = create_item(store, request="Task A")
    second = WorkItem(
        request="Task B",
        work_type=WorkType.GENERIC,
        source_session_id="session-1",
        source_turn_id="turn-2",
    )
    store.create(second)

    for item in (first, second):
        reasoner.decisions[item.work_id] = [
            BrainDecision(action="do_step", summary="Execute bounded step"),
            BrainDecision(action=None, summary="Ready", goal_complete=True),
        ]

    await asyncio.gather(engine.advance(first.work_id), engine.advance(second.work_id))

    assert reasoner.max_active == 1
    assert executor.max_active == 2
    assert store.require(first.work_id).state is WorkState.RUNNING
    assert store.require(second.work_id).state is WorkState.RUNNING

    await asyncio.gather(engine.advance(first.work_id), engine.advance(second.work_id))
    assert store.require(first.work_id).state is WorkState.COMPLETED
    assert store.require(second.work_id).state is WorkState.COMPLETED


@pytest.mark.asyncio
async def test_waiting_for_owner_does_not_fabricate_progress(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )
    item = create_item(store)
    reasoner.decisions[item.work_id] = [
        BrainDecision(
            action=None,
            summary="Need owner choice",
            needs_owner=True,
            owner_question="Use the existing records?",
        ),
        BrainDecision(action=None, summary="Ready", goal_complete=True),
    ]

    result = await engine.advance(item.work_id)
    assert result.state is WorkState.WAITING_FOR_OWNER
    assert result.owner_question == "Use the existing records?"

    waiting = await engine.advance(item.work_id)
    assert waiting.progressed is False
    assert store.list_steps(item.work_id) == ()

    resumed = engine.apply_owner_input(item.work_id, "Yes, preserve them")
    assert resumed.state is WorkState.RUNNING
    owner_steps = store.list_steps(item.work_id)
    assert owner_steps[-1].observation["response"] == "Yes, preserve them"

    await engine.advance(item.work_id)
    assert store.require(item.work_id).state is WorkState.COMPLETED


def test_orchestrator_accepts_pause_resume_cancel_without_session_ownership(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)
    submission = orchestrator.start(
        request="Implement persistent memory",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="voice-session",
        source_turn_id="turn-10",
        priority=WorkPriority.HIGH,
        delivery_policy=DeliveryPolicy.WHEN_IDLE,
    )
    work_id = submission.work.work_id
    assert backend.submitted == [work_id]

    paused = orchestrator.pause(work_id)
    assert paused.state is WorkState.PAUSED
    assert backend.paused == [work_id]
    assert backend.cancelled == []

    resumed = orchestrator.resume(work_id)
    assert resumed.state is WorkState.QUEUED
    assert backend.resumed == [work_id]

    cancelled = orchestrator.cancel(work_id)
    assert cancelled.state is WorkState.CANCELLED
    assert backend.cancelled == [work_id]


@pytest.mark.asyncio
async def test_resource_leases_bound_execution_and_surface_waiting_state(
    tmp_path: Path,
) -> None:
    class CpuExecutor(ConcurrentExecutor):
        def resource_keys(self, work: WorkItem, parameters: dict) -> tuple[str, ...]:
            del work, parameters
            return ("cpu",)

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()
    executor = CpuExecutor()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((executor,)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )
    first = create_item(store, request="CPU task A")
    second = WorkItem(
        request="CPU task B",
        work_type=WorkType.GENERIC,
        source_session_id="session-1",
        source_turn_id="turn-cpu-2",
    )
    store.create(second)
    for item in (first, second):
        reasoner.decisions[item.work_id] = [
            BrainDecision(action="do_step", summary="Use CPU")
        ]

    first_task = asyncio.create_task(engine.advance(first.work_id))
    await asyncio.sleep(0.02)
    second_task = asyncio.create_task(engine.advance(second.work_id))
    await asyncio.sleep(0.02)

    assert store.require(second.work_id).state is WorkState.WAITING_RESOURCE

    await asyncio.gather(first_task, second_task)
    assert executor.max_active == 1
    assert store.require(first.work_id).state is WorkState.RUNNING
    assert store.require(second.work_id).state is WorkState.RUNNING


@pytest.mark.asyncio
async def test_development_completion_requires_passing_tests(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()

    class DevelopmentNoopExecutor:
        descriptor = BrainAction(
            name="dev_status",
            description="Read development status",
            parameter_schema={"type": "object"},
        )
        work_types = frozenset({WorkType.DEVELOPMENT})

        async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
            del work, parameters
            return {"prepared": True}

    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((DevelopmentNoopExecutor(),)),
    )
    item = WorkItem(
        request="Implement persistent memory",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-dev",
        source_turn_id="turn-dev",
    )
    store.create(item)
    reasoner.decisions[item.work_id] = [
        BrainDecision(action=None, summary="Done", goal_complete=True)
    ]

    result = await engine.advance(item.work_id)

    assert result.state is WorkState.RUNNING
    assert store.require(item.work_id).state is WorkState.RUNNING
    steps = store.list_steps(item.work_id)
    assert steps[-1].kind == "completion_guard"
    assert steps[-1].observation["allowed"] is False


@pytest.mark.asyncio
async def test_research_completion_requires_successful_evidence(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()

    class ResearchNoopExecutor:
        descriptor = BrainAction(
            name="research_web",
            description="Research",
            parameter_schema={"type": "object"},
        )
        work_types = frozenset({WorkType.RESEARCH})

        async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
            del work, parameters
            return {"ok": False}

    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ResearchNoopExecutor(),)),
    )
    item = WorkItem(
        request="Research current orchestration",
        work_type=WorkType.RESEARCH,
        source_session_id="session-research",
        source_turn_id="turn-research",
    )
    store.create(item)
    reasoner.decisions[item.work_id] = [
        BrainDecision(action=None, summary="Done", goal_complete=True)
    ]

    await engine.advance(item.work_id)

    assert store.require(item.work_id).state is WorkState.RUNNING
    assert store.list_steps(item.work_id)[-1].kind == "completion_guard"


def test_work_submission_is_idempotent_for_same_canonical_turn(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)

    first = orchestrator.start(
        request="Research this in background",
        work_type=WorkType.RESEARCH,
        source_session_id="session-idem",
        source_turn_id="turn-idem",
    )
    second = orchestrator.start(
        request="Research this in background",
        work_type=WorkType.RESEARCH,
        source_session_id="session-idem",
        source_turn_id="turn-idem",
    )

    assert first.work.work_id == second.work.work_id
    assert backend.submitted == [first.work.work_id]


@pytest.mark.asyncio
async def test_single_brain_lease_honors_work_priority(tmp_path: Path) -> None:
    class OrderedReasoner:
        def __init__(self) -> None:
            self.order: list[str] = []
            self.blocker_started = asyncio.Event()
            self.release_blocker = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def decide(self, request: BrainRequest) -> BrainDecision:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.order.append(request.work.request)
            try:
                if request.work.request == "blocker":
                    self.blocker_started.set()
                    await self.release_blocker.wait()
                return BrainDecision(action="do_step", summary="Execute")
            finally:
                self.active -= 1

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = OrderedReasoner()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )

    blocker = WorkItem(
        request="blocker",
        work_type=WorkType.GENERIC,
        source_session_id="session-priority",
        source_turn_id="turn-blocker",
        priority=WorkPriority.NORMAL,
    )
    low = WorkItem(
        request="low",
        work_type=WorkType.GENERIC,
        source_session_id="session-priority",
        source_turn_id="turn-low",
        priority=WorkPriority.LOW,
    )
    urgent = WorkItem(
        request="urgent",
        work_type=WorkType.GENERIC,
        source_session_id="session-priority",
        source_turn_id="turn-urgent",
        priority=WorkPriority.URGENT,
    )
    for item in (blocker, low, urgent):
        store.create(item)

    blocker_task = asyncio.create_task(engine.advance(blocker.work_id))
    await reasoner.blocker_started.wait()
    low_task = asyncio.create_task(engine.advance(low.work_id))
    await asyncio.sleep(0)
    urgent_task = asyncio.create_task(engine.advance(urgent.work_id))
    await asyncio.sleep(0)
    reasoner.release_blocker.set()

    await asyncio.gather(blocker_task, low_task, urgent_task)

    assert reasoner.max_active == 1
    assert reasoner.order == ["blocker", "urgent", "low"]


@pytest.mark.asyncio
async def test_repeated_step_failures_are_bounded(tmp_path: Path) -> None:
    class FailingExecutor:
        descriptor = BrainAction(
            name="always_fail",
            description="Always fail",
            parameter_schema={"type": "object"},
        )
        work_types = frozenset({WorkType.GENERIC})

        async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
            del work, parameters
            raise RuntimeError("boom")

    class AlwaysActReasoner:
        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            return BrainDecision(action="always_fail", summary="Try bounded action")

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(AlwaysActReasoner()),
        actions=WorkActionRegistry((FailingExecutor(),)),
    )
    item = create_item(store, request="Fail safely")

    first = await engine.advance(item.work_id)
    second = await engine.advance(item.work_id)
    third = await engine.advance(item.work_id)

    assert first.state is WorkState.RETRYING
    assert second.state is WorkState.RETRYING
    assert third.state is WorkState.FAILED
    assert len(store.list_pending_deliveries()) == 1


@pytest.mark.asyncio
async def test_work_waits_for_dependency_then_resumes(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )
    dependency = create_item(store, request="dependency")
    dependent = WorkItem(
        request="dependent",
        work_type=WorkType.GENERIC,
        source_session_id="session-dependency",
        source_turn_id="turn-dependent",
        dependencies=(dependency.work_id,),
    )
    store.create(dependent)
    reasoner.decisions[dependent.work_id] = [
        BrainDecision(action="do_step", summary="Run after dependency")
    ]

    waiting = await engine.advance(dependent.work_id)
    assert waiting.state is WorkState.WAITING_DEPENDENCY
    assert reasoner.max_active == 0

    running_dependency = dependency.transition(WorkState.RUNNING)
    store.save(running_dependency, expected_version=dependency.version)
    completed_dependency = running_dependency.transition(WorkState.COMPLETED)
    store.save(completed_dependency, expected_version=running_dependency.version)

    resumed = await engine.advance(dependent.work_id)
    assert resumed.state is WorkState.RUNNING
    assert store.list_steps(dependent.work_id)[-1].kind == "do_step"


@pytest.mark.asyncio
async def test_failed_dependency_fails_only_dependent_work(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = ScriptedReasoner()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )
    dependency = create_item(store, request="dependency")
    dependent = WorkItem(
        request="dependent",
        work_type=WorkType.GENERIC,
        source_session_id="session-dependency-fail",
        source_turn_id="turn-dependent-fail",
        dependencies=(dependency.work_id,),
    )
    store.create(dependent)

    running_dependency = dependency.transition(WorkState.RUNNING)
    store.save(running_dependency, expected_version=dependency.version)
    failed_dependency = running_dependency.transition(
        WorkState.FAILED,
        status_detail="dependency failed",
    )
    store.save(failed_dependency, expected_version=running_dependency.version)

    result = await engine.advance(dependent.work_id)

    assert result.state is WorkState.FAILED
    assert store.require(dependency.work_id).state is WorkState.FAILED
    assert store.require(dependent.work_id).state is WorkState.FAILED


def test_cancel_one_work_item_does_not_affect_another(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)

    first = orchestrator.start(
        request="Task A",
        work_type=WorkType.GENERIC,
        source_session_id="session-cancel",
        source_turn_id="turn-a",
    )
    second = orchestrator.start(
        request="Task B",
        work_type=WorkType.GENERIC,
        source_session_id="session-cancel",
        source_turn_id="turn-b",
    )

    orchestrator.cancel(first.work.work_id)

    assert store.require(first.work.work_id).state is WorkState.CANCELLED
    assert store.require(second.work.work_id).state is WorkState.QUEUED
    assert backend.cancelled == [first.work.work_id]


def test_delivery_policy_is_durable_ordered_and_exactly_once(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    store = SQLiteWorkStore(path)
    idle = WorkItem(
        request="Idle delivery",
        work_type=WorkType.GENERIC,
        source_session_id="session-delivery",
        source_turn_id="turn-idle",
        delivery_policy=DeliveryPolicy.WHEN_IDLE,
    )
    interrupt = WorkItem(
        request="Interrupt delivery",
        work_type=WorkType.GENERIC,
        source_session_id="session-delivery",
        source_turn_id="turn-interrupt",
        delivery_policy=DeliveryPolicy.INTERRUPT,
    )
    silent = WorkItem(
        request="Silent delivery",
        work_type=WorkType.GENERIC,
        source_session_id="session-delivery",
        source_turn_id="turn-silent",
        delivery_policy=DeliveryPolicy.SILENT,
    )
    for item in (idle, interrupt, silent):
        store.create(item)

    store.enqueue_delivery(
        work=idle,
        kind=WorkDeliveryKind.COMPLETION,
        message="Idle complete",
        event_key="completion",
    )
    store.enqueue_delivery(
        work=interrupt,
        kind=WorkDeliveryKind.FAILURE,
        message="Urgent failure",
        event_key="failure",
    )
    assert (
        store.enqueue_delivery(
            work=silent,
            kind=WorkDeliveryKind.COMPLETION,
            message="Never speak",
            event_key="completion",
        )
        is None
    )

    reopened = SQLiteWorkStore(path)
    pending = reopened.list_pending_deliveries()
    assert [item.work_id for item in pending] == [
        interrupt.work_id,
        idle.work_id,
    ]

    reopened.mark_delivery_delivered(pending[0].delivery_id)
    assert [item.work_id for item in reopened.list_pending_deliveries()] == [
        idle.work_id
    ]

    duplicate = reopened.enqueue_delivery(
        work=idle,
        kind=WorkDeliveryKind.COMPLETION,
        message="Idle complete",
        event_key="completion",
    )
    assert duplicate is not None
    assert len(reopened.list_pending_deliveries()) == 1


def test_pause_resume_restores_waiting_for_owner_state(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)
    submission = orchestrator.start(
        request="Need a decision later",
        work_type=WorkType.GENERIC,
        source_session_id="session-pause-wait",
        source_turn_id="turn-pause-wait",
    )
    queued = submission.work
    running = queued.transition(WorkState.RUNNING)
    store.save(running, expected_version=queued.version)
    waiting = running.transition(
        WorkState.WAITING_FOR_OWNER,
        status_detail="Choose A or B?",
    )
    store.save(waiting, expected_version=running.version)

    paused = orchestrator.pause(waiting.work_id)
    assert paused.state is WorkState.PAUSED
    assert paused.paused_from_state is WorkState.WAITING_FOR_OWNER

    reopened = SQLiteWorkStore(tmp_path / "work.sqlite")
    recovered = reopened.require(waiting.work_id)
    assert recovered.paused_from_state is WorkState.WAITING_FOR_OWNER

    resumed = orchestrator.resume(waiting.work_id)
    assert resumed.state is WorkState.WAITING_FOR_OWNER
    assert resumed.paused_from_state is None


@pytest.mark.asyncio
async def test_executor_can_request_owner_input_without_becoming_failure(
    tmp_path: Path,
) -> None:
    class OwnerGateExecutor:
        descriptor = BrainAction(
            name="owner_gate",
            description="Require owner input",
            parameter_schema={"type": "object"},
        )
        work_types = frozenset({WorkType.GENERIC})

        async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
            del work, parameters
            raise WorkOwnerInputRequired("Safe sandbox is required.")

    class GateReasoner:
        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            return BrainDecision(action="owner_gate", summary="Run gated step")

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(GateReasoner()),
        actions=WorkActionRegistry((OwnerGateExecutor(),)),
    )
    item = create_item(store, request="Run safely")

    result = await engine.advance(item.work_id)

    assert result.state is WorkState.WAITING_FOR_OWNER
    assert result.owner_question == "Safe sandbox is required."
    step = store.list_steps(item.work_id)[-1]
    assert step.state.value == "completed"
    assert step.observation["needs_owner"] is True
    assert len(store.list_pending_deliveries()) == 1


@pytest.mark.asyncio
async def test_interactive_voice_preempts_inflight_background_reasoning() -> None:
    class BlockingReasoner:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
            raise AssertionError("unreachable")

    reasoner = BlockingReasoner()
    gate = InteractiveBrainGate()
    coordinator = BrainCoordinator(reasoner, interactive_gate=gate)
    item = WorkItem(
        request="Background reasoning",
        work_type=WorkType.GENERIC,
        source_session_id="session-brain-gate",
        source_turn_id="turn-brain-gate",
    )
    request = BrainRequest(
        work=item,
        recent_steps=(),
        purpose="test interactive preemption",
        allowed_actions=(
            BrainAction(
                name="do_step",
                description="Do one bounded step",
                parameter_schema={"type": "object"},
            ),
        ),
    )

    task = asyncio.create_task(coordinator.decide(request))
    await reasoner.started.wait()
    gate.set_interactive_active(True)

    with pytest.raises(BrainPreempted):
        await task

    assert reasoner.cancelled.is_set()
    assert coordinator.busy is False


@pytest.mark.asyncio
async def test_brain_preemption_waits_without_consuming_failure_budget(
    tmp_path: Path,
) -> None:
    class PreemptibleReasoner:
        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()

        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            self.calls += 1
            if self.calls == 1:
                self.started.set()
                await asyncio.Event().wait()
            return BrainDecision(action="do_step", summary="Continue after voice")

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = PreemptibleReasoner()
    gate = InteractiveBrainGate()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner, interactive_gate=gate),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )
    item = create_item(store, request="Background task")

    first_advance = asyncio.create_task(engine.advance(item.work_id))
    await reasoner.started.wait()
    gate.set_interactive_active(True)
    preempted = await first_advance

    assert preempted.state is WorkState.WAITING_RESOURCE
    assert store.list_steps(item.work_id) == ()
    assert store.list_pending_deliveries() == ()

    gate.set_interactive_active(False)
    resumed = await engine.advance(item.work_id)

    assert resumed.state is WorkState.RUNNING
    assert store.list_steps(item.work_id)[-1].kind == "do_step"


@pytest.mark.asyncio
async def test_deterministic_worker_continues_while_voice_owns_brain(
    tmp_path: Path,
) -> None:
    class ImmediateReasoner:
        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            return BrainDecision(
                action="controlled_step", summary="Run deterministic work"
            )

    class ControlledExecutor:
        descriptor = BrainAction(
            name="controlled_step",
            description="Controlled deterministic work",
            parameter_schema={"type": "object"},
        )
        work_types = frozenset({WorkType.GENERIC})

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
            del work, parameters
            self.started.set()
            await self.release.wait()
            return {"finished": True}

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    gate = InteractiveBrainGate()
    executor = ControlledExecutor()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(ImmediateReasoner(), interactive_gate=gate),
        actions=WorkActionRegistry((executor,)),
    )
    item = create_item(store, request="Keep deterministic work running")

    task = asyncio.create_task(engine.advance(item.work_id))
    await executor.started.wait()

    gate.set_interactive_active(True)
    executor.release.set()
    result = await task

    assert result.state is WorkState.RUNNING
    assert store.list_steps(item.work_id)[-1].observation == {"finished": True}
    assert gate.interactive_active is True


def test_unique_waiting_owner_work_can_be_resolved_without_id(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)
    submission = orchestrator.start(
        request="Need one owner answer",
        work_type=WorkType.GENERIC,
        source_session_id="session-natural-owner",
        source_turn_id="turn-natural-owner",
    )
    queued = submission.work
    running = queued.transition(WorkState.RUNNING)
    store.save(running, expected_version=queued.version)
    waiting = running.transition(
        WorkState.WAITING_FOR_OWNER,
        status_detail="Proceed?",
    )
    store.save(waiting, expected_version=running.version)

    from jarvis.work.runtime import WorkRuntime

    runtime = object.__new__(WorkRuntime)
    runtime.store = store

    resolved = runtime.resolve_waiting_owner_work(None)

    assert resolved.work_id == waiting.work_id


def test_multiple_waiting_owner_tasks_require_disambiguation(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    for index in range(2):
        item = WorkItem(
            request=f"Owner task {index}",
            work_type=WorkType.GENERIC,
            source_session_id="session-owner-ambiguous",
            source_turn_id=f"turn-owner-{index}",
        )
        store.create(item)
        running = item.transition(WorkState.RUNNING)
        store.save(running, expected_version=item.version)
        waiting = running.transition(
            WorkState.WAITING_FOR_OWNER,
            status_detail="Need owner input",
        )
        store.save(waiting, expected_version=running.version)

    from jarvis.work.runtime import WorkRuntime

    runtime = object.__new__(WorkRuntime)
    runtime.store = store

    with pytest.raises(ValueError, match="multiple background tasks"):
        runtime.resolve_waiting_owner_work(None)


def test_development_completion_requires_post_edit_verification_order() -> None:
    work = WorkItem(
        request="Implement safely",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-dev-order",
        source_turn_id="turn-dev-order",
    )

    def completed_step(
        kind: str,
        observation: dict | None = None,
    ) -> WorkStep:
        return (
            WorkStep(
                work_id=work.work_id,
                kind=kind,
                summary=kind,
            )
            .start()
            .complete(observation or {})
        )

    stale_verification = (
        completed_step("dev_run_tests", {"passed": True, "sandbox": "docker"}),
        completed_step("dev_write_file", {"path": "module.py"}),
        completed_step("dev_diff", {"diff": "changed"}),
        completed_step(
            "dev_commit",
            {"committed": True, "clean": True, "commit": "abc"},
        ),
    )
    allowed, reason = WorkEngine._completion_guard(work, stale_verification)
    assert allowed is False
    assert reason is not None
    assert "after the latest edit" in reason

    correct_order = (
        completed_step("dev_write_file", {"path": "module.py"}),
        completed_step("dev_run_tests", {"passed": True, "sandbox": "docker"}),
        completed_step("dev_diff", {"diff": "changed"}),
        completed_step(
            "dev_commit",
            {"committed": True, "clean": True, "commit": "def"},
        ),
    )
    allowed, reason = WorkEngine._completion_guard(work, correct_order)
    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_pause_during_inflight_reasoning_stops_before_execution(
    tmp_path: Path,
) -> None:
    class BlockingReasoner:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def decide(self, request: BrainRequest) -> BrainDecision:
            del request
            self.started.set()
            await self.release.wait()
            return BrainDecision(action="do_step", summary="Should not execute")

    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    reasoner = BlockingReasoner()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((ConcurrentExecutor(),)),
    )
    backend = FakeBackend()
    orchestrator = WorkOrchestrator(store, backend)
    submission = orchestrator.start(
        request="Pause me while reasoning",
        work_type=WorkType.GENERIC,
        source_session_id="session-pause-reasoning",
        source_turn_id="turn-pause-reasoning",
    )

    advance = asyncio.create_task(engine.advance(submission.work.work_id))
    await reasoner.started.wait()
    paused = orchestrator.pause(submission.work.work_id)
    reasoner.release.set()
    result = await advance

    assert paused.state is WorkState.PAUSED
    assert result.state is WorkState.PAUSED
    assert store.list_steps(submission.work.work_id) == ()
