"""Stepwise JARVIS-controlled work engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.work.brain import BrainAction, BrainCoordinator, BrainRequest
from jarvis.work.models import (
    WorkDeliveryKind,
    WorkItem,
    WorkState,
    WorkStep,
    WorkType,
)
from jarvis.work.store import SQLiteWorkStore


class WorkActionExecutor(Protocol):
    descriptor: BrainAction
    work_types: frozenset[WorkType]

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]: ...


class WorkActionRegistry:
    def __init__(self, executors: tuple[WorkActionExecutor, ...]) -> None:
        by_name: dict[str, WorkActionExecutor] = {}
        for executor in executors:
            name = executor.descriptor.name
            if name in by_name:
                raise ValueError(f"duplicate work action: {name}")
            by_name[name] = executor
        self._by_name = by_name

    def actions_for(self, work_type: WorkType) -> tuple[BrainAction, ...]:
        return tuple(
            executor.descriptor
            for executor in self._by_name.values()
            if work_type in executor.work_types
        )

    def require(self, action: str, work_type: WorkType) -> WorkActionExecutor:
        executor = self._by_name.get(action)
        if executor is None or work_type not in executor.work_types:
            raise ValueError(f"work action is unavailable for {work_type.value}: {action}")
        return executor


@dataclass(frozen=True, slots=True)
class WorkAdvanceResult:
    work_id: str
    state: WorkState
    progressed: bool
    owner_question: str | None = None


class WorkEngine:
    """Advance one WorkItem by one JARVIS-controlled reasoning/execution cycle."""

    def __init__(
        self,
        *,
        store: SQLiteWorkStore,
        brain: BrainCoordinator,
        actions: WorkActionRegistry,
    ) -> None:
        self._store = store
        self._brain = brain
        self._actions = actions

    def _make_running(self, work: WorkItem) -> WorkItem:
        if work.state is WorkState.QUEUED or work.state is WorkState.RETRYING:
            running = work.transition(WorkState.RUNNING, status_detail="reasoning")
            return self._store.save(running, expected_version=work.version)
        return work

    async def advance(self, work_id: str) -> WorkAdvanceResult:
        work = self._store.require(work_id)
        if work.state.terminal or work.state is WorkState.PAUSED:
            return WorkAdvanceResult(work.work_id, work.state, progressed=False)
        if work.state is WorkState.WAITING_FOR_OWNER:
            return WorkAdvanceResult(
                work.work_id,
                work.state,
                progressed=False,
                owner_question=work.status_detail,
            )

        work = self._make_running(work)
        actions = self._actions.actions_for(work.work_type)
        if not actions:
            failed = work.transition(
                WorkState.FAILED,
                status_detail=f"no registered executor for {work.work_type.value}",
            )
            self._store.save(failed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=failed,
                kind=WorkDeliveryKind.FAILURE,
                message=failed.status_detail or "Background work failed.",
                event_key=f"failure:{failed.version}",
            )
            return WorkAdvanceResult(work.work_id, failed.state, progressed=True)

        steps = self._store.list_steps(work.work_id)
        decision = await self._brain.decide(
            BrainRequest(
                work=work,
                recent_steps=steps[-12:],
                purpose="choose the next bounded step for this JARVIS-owned work item",
                allowed_actions=actions,
            )
        )

        if decision.goal_complete:
            completed = work.transition(
                WorkState.COMPLETED,
                status_detail=decision.summary,
                result={"summary": decision.summary},
            )
            self._store.save(completed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=completed,
                kind=WorkDeliveryKind.COMPLETION,
                message=decision.summary,
                event_key="completion",
            )
            return WorkAdvanceResult(work.work_id, completed.state, progressed=True)

        if decision.needs_owner:
            waiting = work.transition(
                WorkState.WAITING_FOR_OWNER,
                status_detail=decision.owner_question,
            )
            self._store.save(waiting, expected_version=work.version)
            self._store.enqueue_delivery(
                work=waiting,
                kind=WorkDeliveryKind.OWNER_INPUT,
                message=decision.owner_question or "This work needs your input.",
                event_key=f"owner:{waiting.version}",
            )
            return WorkAdvanceResult(
                work.work_id,
                waiting.state,
                progressed=True,
                owner_question=decision.owner_question,
            )

        assert decision.action is not None
        executor = self._actions.require(decision.action, work.work_type)
        step = WorkStep(
            work_id=work.work_id,
            kind=decision.action,
            summary=decision.summary,
            input_data=dict(decision.parameters),
        )
        self._store.add_step(step)
        running_step = step.start()
        self._store.save_step(running_step)
        with_step = work.with_progress(
            current_step_id=step.step_id,
            status_detail=decision.summary,
        )
        self._store.save(with_step, expected_version=work.version)

        try:
            observation = await executor.execute(
                work=with_step,
                parameters=dict(decision.parameters),
            )
        except Exception as exc:
            failed_step = running_step.fail(type(exc).__name__ + ": " + str(exc))
            self._store.save_step(failed_step)
            latest = self._store.require(work.work_id)
            retrying = latest.transition(
                WorkState.RETRYING,
                status_detail=f"step failed: {decision.action}",
                current_step_id=step.step_id,
            )
            self._store.save(retrying, expected_version=latest.version)
            return WorkAdvanceResult(work.work_id, retrying.state, progressed=True)

        completed_step = running_step.complete(observation)
        self._store.save_step(completed_step)
        latest = self._store.require(work.work_id)
        progressed = latest.with_progress(
            current_step_id=None,
            status_detail=f"completed step: {decision.action}",
        )
        self._store.save(progressed, expected_version=latest.version)
        return WorkAdvanceResult(work.work_id, progressed.state, progressed=True)

    def fail(self, work_id: str, reason: str) -> WorkItem:
        work = self._store.require(work_id)
        if work.state.terminal:
            return work
        normalized = reason.strip()
        if not normalized:
            raise ValueError("work failure reason must not be empty")
        failed = work.transition(
            WorkState.FAILED,
            status_detail=normalized,
            current_step_id=work.current_step_id,
        )
        saved = self._store.save(failed, expected_version=work.version)
        self._store.enqueue_delivery(
            work=saved,
            kind=WorkDeliveryKind.FAILURE,
            message=normalized,
            event_key=f"failure:{saved.version}",
        )
        return saved

    def apply_owner_input(self, work_id: str, response: str) -> WorkItem:
        work = self._store.require(work_id)
        if work.state is not WorkState.WAITING_FOR_OWNER:
            raise ValueError("work is not waiting for owner input")
        normalized = response.strip()
        if not normalized:
            raise ValueError("owner response must not be empty")
        step = WorkStep(
            work_id=work.work_id,
            kind="owner_input",
            summary="Owner supplied requested input",
            input_data={},
        )
        self._store.add_step(step)
        completed = step.start().complete({"response": normalized})
        self._store.save_step(completed)
        resumed = work.transition(
            WorkState.RUNNING,
            status_detail="owner input received",
        )
        return self._store.save(resumed, expected_version=work.version)
