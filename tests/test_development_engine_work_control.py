from __future__ import annotations

from typing import Any

import pytest

from jarvis.work.brain import BrainAction, BrainCoordinator, BrainDecision
from jarvis.work.engine import (
    WorkActionRegistry,
    WorkEngine,
    WorkResourceBlocked,
)
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class NeverReason:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, request):
        self.calls += 1
        raise AssertionError("control-plane work must not invoke the model reasoner")


class DevelopmentEngineAction:
    descriptor = BrainAction(
        name="dev_engine_execute",
        description="Synthetic coherent development engine.",
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self) -> None:
        self.calls = 0

    def available_for(self, work: WorkItem) -> bool:
        return work.source_session_id == "phase9"

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work, parameters
        self.calls += 1
        return {
            "ticket_id": "dev_ticket_demo",
            "ticket_digest": "a" * 64,
            "development_result": {
                "disposition": "needs_research",
                "summary": "Fresh protocol evidence is required.",
                "reason": "Approved evidence is insufficient.",
            },
        }


class ResourceBlockedDevelopmentAction(DevelopmentEngineAction):
    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work, parameters
        self.calls += 1
        if self.calls == 1:
            raise WorkResourceBlocked(
                "Shared engineering capacity is temporarily unavailable.",
                retry_after_seconds=123.0,
                blocker_code="shared_capacity",
                observation={
                    "development_result": {
                        "disposition": "blocked_resource",
                        "summary": "Waiting for engineering capacity.",
                    }
                },
            )
        return {
            "ticket_id": "dev_ticket_demo",
            "ticket_digest": "b" * 64,
            "development_result": {
                "disposition": "needs_research",
                "summary": "Fresh evidence is required.",
                "reason": "Current evidence is insufficient.",
            },
        }


def _decider(work, actions, steps):
    del work
    assert any(action.name == "dev_engine_execute" for action in actions)
    terminal = next(
        (
            step
            for step in reversed(steps)
            if step.kind == "dev_engine_execute"
            and step.state.value == "completed"
            and step.observation.get("resource_blocked") is not True
        ),
        None,
    )
    if terminal is None:
        return BrainDecision(
            action="dev_engine_execute",
            summary="Run coherent engineering.",
        )
    return BrainDecision(
        action=None,
        summary="Coherent engineering returned a typed lifecycle result.",
        goal_complete=True,
    )


def _store_with_development(tmp_path) -> tuple[SQLiteWorkStore, WorkItem]:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    work = WorkItem(
        request="Develop approved capability.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="phase9",
        source_turn_id="development:1",
    )
    store.create(work)
    return store, work


@pytest.mark.asyncio
async def test_control_plane_development_bypasses_model_micro_steps(tmp_path) -> None:
    store, work = _store_with_development(tmp_path)
    reasoner = NeverReason()
    action = DevelopmentEngineAction()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((action,)),
        control_plane_decider=_decider,
        completion_guard=lambda *_: (True, None),
    )

    first = await engine.advance(work.work_id)
    assert first.state is WorkState.RUNNING
    assert action.calls == 1
    assert reasoner.calls == 0

    second = await engine.advance(work.work_id)
    assert second.state is WorkState.COMPLETED
    assert reasoner.calls == 0
    completed = store.require(work.work_id)
    assert completed.result["development_engine"]["disposition"] == "needs_research"


@pytest.mark.asyncio
async def test_executor_resource_blocker_parks_without_reasoning_failure(tmp_path) -> None:
    store, work = _store_with_development(tmp_path)
    reasoner = NeverReason()
    action = ResourceBlockedDevelopmentAction()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(reasoner),
        actions=WorkActionRegistry((action,)),
        control_plane_decider=_decider,
        completion_guard=lambda *_: (True, None),
    )

    blocked = await engine.advance(work.work_id)
    assert blocked.state is WorkState.WAITING_RESOURCE
    assert blocked.retry_after_seconds == 123.0
    blocker_step = store.list_steps(work.work_id)[-1]
    assert blocker_step.state.value == "completed"
    assert blocker_step.observation["resource_blocked"] is True
    assert blocker_step.observation["blocker_code"] == "shared_capacity"
    assert reasoner.calls == 0

    resumed = await engine.advance(work.work_id)
    assert resumed.state is WorkState.RUNNING
    assert action.calls == 2
    assert reasoner.calls == 0

    completed = await engine.advance(work.work_id)
    assert completed.state is WorkState.COMPLETED
    assert reasoner.calls == 0


def test_work_action_registry_filters_exact_work_availability(tmp_path) -> None:
    store, work = _store_with_development(tmp_path)
    action = DevelopmentEngineAction()
    registry = WorkActionRegistry((action,))

    assert [item.name for item in registry.actions_for_work(work)] == [
        "dev_engine_execute"
    ]

    unrelated = WorkItem(
        request="Incident development.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="incident",
        source_turn_id="development:1",
    )
    store.create(unrelated)
    assert registry.actions_for_work(unrelated) == ()
