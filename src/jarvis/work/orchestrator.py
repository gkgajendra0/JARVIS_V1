"""JARVIS-owned persistent work orchestration service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.work.models import (
    DeliveryPolicy,
    WorkItem,
    WorkPriority,
    WorkState,
    WorkType,
)
from jarvis.work.store import SQLiteWorkStore


class WorkExecutionBackend(Protocol):
    """Durable execution substrate; DBOS is the production implementation."""

    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...

    def cancel(self, execution_id: str) -> None: ...

    def pause(self, execution_id: str) -> None: ...

    def resume(self, execution_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkSubmission:
    work: WorkItem
    execution_id: str


class WorkOrchestrator:
    """Own work identity/state while delegating durable execution mechanics."""

    def __init__(self, store: SQLiteWorkStore, backend: WorkExecutionBackend) -> None:
        self._store = store
        self._backend = backend

    def start(
        self,
        *,
        request: str,
        work_type: WorkType,
        source_session_id: str,
        source_turn_id: str,
        priority: WorkPriority = WorkPriority.NORMAL,
        delivery_policy: DeliveryPolicy = DeliveryPolicy.WHEN_IDLE,
    ) -> WorkSubmission:
        item = WorkItem(
            request=request,
            work_type=work_type,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            priority=priority,
            delivery_policy=delivery_policy,
        )
        self._store.create(item)
        try:
            execution_id = self._backend.submit(item.work_id, priority=priority)
        except Exception:
            failed = item.transition(
                WorkState.FAILED,
                status_detail="durable execution could not be submitted",
            )
            self._store.save(failed, expected_version=item.version)
            raise
        if execution_id != item.work_id:
            failed = item.transition(
                WorkState.FAILED,
                status_detail="durable backend returned a mismatched execution id",
            )
            self._store.save(failed, expected_version=item.version)
            raise RuntimeError("durable backend must use work_id as execution_id")
        return WorkSubmission(work=item, execution_id=execution_id)

    def get(self, work_id: str) -> WorkItem:
        return self._store.require(work_id)

    def list_active(self, *, limit: int = 100) -> tuple[WorkItem, ...]:
        return self._store.list(
            states=(
                WorkState.QUEUED,
                WorkState.RUNNING,
                WorkState.WAITING_RESOURCE,
                WorkState.WAITING_DEPENDENCY,
                WorkState.WAITING_UNTIL,
                WorkState.WAITING_FOR_OWNER,
                WorkState.PAUSED,
                WorkState.RETRYING,
            ),
            limit=limit,
        )

    def cancel(self, work_id: str) -> WorkItem:
        item = self._store.require(work_id)
        if item.state.terminal:
            return item
        cancelled = item.transition(
            WorkState.CANCELLED,
            status_detail="cancelled by owner",
            current_step_id=item.current_step_id,
        )
        saved = self._store.save(cancelled, expected_version=item.version)
        self._backend.cancel(work_id)
        return saved

    def pause(self, work_id: str) -> WorkItem:
        item = self._store.require(work_id)
        if item.state.terminal:
            raise ValueError("terminal work cannot be paused")
        if item.state is WorkState.PAUSED:
            return item
        paused = item.transition(
            WorkState.PAUSED,
            status_detail="paused by owner",
            current_step_id=item.current_step_id,
        )
        saved = self._store.save(paused, expected_version=item.version)
        self._backend.pause(work_id)
        return saved

    def resume(self, work_id: str) -> WorkItem:
        item = self._store.require(work_id)
        if item.state is not WorkState.PAUSED:
            raise ValueError("only paused work can be resumed")
        resumed = item.transition(
            WorkState.RUNNING,
            status_detail="resumed by owner",
            current_step_id=item.current_step_id,
        )
        saved = self._store.save(resumed, expected_version=item.version)
        try:
            self._backend.resume(work_id)
        except Exception:
            latest = self._store.require(work_id)
            reverted = latest.transition(
                WorkState.PAUSED,
                status_detail="resume failed; work remains paused",
                current_step_id=latest.current_step_id,
            )
            self._store.save(reverted, expected_version=latest.version)
            raise
        return saved

    def reprioritize(self, work_id: str, priority: WorkPriority) -> WorkItem:
        item = self._store.require(work_id)
        updated = item.with_priority(priority)
        if updated is item:
            return item
        return self._store.save(updated, expected_version=item.version)
