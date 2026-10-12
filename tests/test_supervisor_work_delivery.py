import pytest

from jarvis.work.brain import BrainAction, BrainCoordinator, BrainDecision
from jarvis.work.engine import (
    WorkActionRegistry,
    WorkEngine,
    WorkOwnerInputRequired,
    WorkResourceBlocked,
    WorkTerminalFailure,
)
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class SingleActionReasoner:
    def __init__(self, action: str) -> None:
        self.action = action

    async def decide(self, request):
        del request
        return BrainDecision(action=self.action, summary="Run bounded specialist step.")


class TerminalExecutor:
    descriptor = BrainAction(
        name="terminal_step",
        description="Return one typed terminal specialist outcome.",
        parameter_schema={"type": "object"},
    )
    work_types = frozenset({WorkType.GENERIC})

    async def execute(self, *, work, parameters):
        del work, parameters
        raise WorkTerminalFailure(
            "The specialist could not satisfy its exact contract.",
            failure_code="specialist_contract_failed",
        )


class ResourceExecutor:
    descriptor = BrainAction(
        name="resource_step",
        description="Return one temporary resource blocker.",
        parameter_schema={"type": "object"},
    )
    work_types = frozenset({WorkType.GENERIC})

    async def execute(self, *, work, parameters):
        del work, parameters
        raise WorkResourceBlocked(
            "Provider capacity is temporarily unavailable.",
            retry_after_seconds=60.0,
            blocker_code="provider_capacity",
        )


class OwnerInputExecutor:
    descriptor = BrainAction(
        name="owner_step",
        description="Request deterministic owner input.",
        parameter_schema={"type": "object"},
    )
    work_types = frozenset({WorkType.GENERIC})

    async def execute(self, *, work, parameters):
        del work, parameters
        raise WorkOwnerInputRequired("Please confirm the reviewed pairing code.")


def _engine(tmp_path, action, executor):
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    return (
        store,
        WorkEngine(
            store=store,
            brain=BrainCoordinator(SingleActionReasoner(action)),
            actions=WorkActionRegistry((executor,)),
        ),
    )


@pytest.mark.asyncio
async def test_governed_change_child_failure_is_internal_evidence(tmp_path) -> None:
    store, engine = _engine(tmp_path, "terminal_step", TerminalExecutor())
    work = store.create(
        WorkItem(
            request="Research an EngineeringChange.",
            work_type=WorkType.GENERIC,
            source_session_id="change:change-test",
            source_turn_id="research:1",
        )
    )

    result = await engine.advance(work.work_id)

    assert result.state is WorkState.FAILED
    assert store.list_pending_deliveries() == ()


@pytest.mark.asyncio
async def test_standalone_terminal_failure_uses_supervisor_voice(tmp_path) -> None:
    store, engine = _engine(tmp_path, "terminal_step", TerminalExecutor())
    work = store.create(
        WorkItem(
            request="Run a standalone task.",
            work_type=WorkType.GENERIC,
            source_session_id="owner-session",
            source_turn_id="owner-turn",
        )
    )

    result = await engine.advance(work.work_id)

    assert result.state is WorkState.FAILED
    deliveries = store.list_pending_deliveries()
    assert len(deliveries) == 1
    assert deliveries[0].message.startswith("A background task stopped:")
    assert "specialist_contract_failed" not in deliveries[0].message


@pytest.mark.asyncio
async def test_internal_resource_blocker_does_not_interrupt_owner(tmp_path) -> None:
    store, engine = _engine(tmp_path, "resource_step", ResourceExecutor())
    work = store.create(
        WorkItem(
            request="Wait for a temporary provider resource.",
            work_type=WorkType.GENERIC,
            source_session_id="change:change-resource",
            source_turn_id="research:1",
        )
    )

    result = await engine.advance(work.work_id)

    assert result.state is WorkState.WAITING_RESOURCE
    assert result.retry_after_seconds == 60.0
    assert store.list_pending_deliveries() == ()


@pytest.mark.asyncio
async def test_owner_input_is_surfaced_through_supervisor_voice(tmp_path) -> None:
    store, engine = _engine(tmp_path, "owner_step", OwnerInputExecutor())
    work = store.create(
        WorkItem(
            request="Continue only after owner input.",
            work_type=WorkType.GENERIC,
            source_session_id="change:change-owner",
            source_turn_id="research:1",
        )
    )

    result = await engine.advance(work.work_id)

    assert result.state is WorkState.WAITING_FOR_OWNER
    deliveries = store.list_pending_deliveries()
    assert len(deliveries) == 1
    assert deliveries[0].message == (
        "I need your input before I can continue: "
        "Please confirm the reviewed pairing code."
    )


@pytest.mark.asyncio
async def test_governed_child_completion_is_not_directly_announced(tmp_path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(SingleActionReasoner("unused")),
        actions=WorkActionRegistry(()),
    )
    work = store.create(
        WorkItem(
            request="Completed governed child.",
            work_type=WorkType.GENERIC,
            source_session_id="gicc:goal-test",
            source_turn_id="node:1",
        )
    )
    running = store.save(
        work.transition(WorkState.RUNNING),
        expected_version=work.version,
    )
    store.save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="Specialist work completed.",
        ),
        expected_version=running.version,
    )

    result = await engine.advance(work.work_id)

    assert result.state is WorkState.COMPLETED
    assert store.list_pending_deliveries() == ()
