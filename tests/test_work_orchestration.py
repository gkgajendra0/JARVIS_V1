from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.work.brain import BrainAction, BrainCoordinator, BrainDecision, BrainRequest
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import DeliveryPolicy, WorkItem, WorkPriority, WorkState, WorkType
from jarvis.work.orchestrator import WorkOrchestrator
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
        self.resumed: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id

    def cancel(self, execution_id: str) -> None:
        self.cancelled.append(execution_id)

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
    assert backend.cancelled == [work_id]

    resumed = orchestrator.resume(work_id)
    assert resumed.state is WorkState.RUNNING
    assert backend.resumed == [work_id]

    cancelled = orchestrator.cancel(work_id)
    assert cancelled.state is WorkState.CANCELLED
    assert backend.cancelled == [work_id, work_id]
