"""JARVIS-owned persistent work orchestration service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.work.models import (
    DeliveryPolicy,
    WorkDeliveryKind,
    WorkItem,
    WorkPriority,
    WorkState,
    WorkStep,
    WorkType,
)
from jarvis.work.store import SQLiteWorkStore, WorkStoreError


class WorkExecutionBackend(Protocol):
    """Durable execution substrate; DBOS is the production implementation."""

    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...

    def cancel(
        self,
        execution_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None: ...

    def pause(self, execution_id: str) -> None: ...

    def resume(
        self,
        execution_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None: ...

    def restart(
        self,
        work_id: str,
        *,
        priority: WorkPriority,
        retry_token: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class WorkSubmission:
    work: WorkItem
    execution_id: str


class WorkOrchestrator:
    """Own work identity/state while delegating durable execution mechanics."""

    _EVENT_DRIVEN_WORK_TYPES = frozenset({WorkType.MONITORING})

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
        dependencies: tuple[str, ...] = (),
    ) -> WorkSubmission:
        existing = self._store.find_by_source_turn(
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            work_type=work_type,
        )
        if existing is not None:
            return WorkSubmission(work=existing, execution_id=existing.work_id)

        event_driven = work_type in self._EVENT_DRIVEN_WORK_TYPES
        item = WorkItem(
            request=request,
            work_type=work_type,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            state=(WorkState.WAITING_RESOURCE if event_driven else WorkState.QUEUED),
            priority=priority,
            delivery_policy=delivery_policy,
            dependencies=dependencies,
            status_detail=("waiting for monitored event" if event_driven else None),
        )
        self._store.create(item)
        if event_driven:
            return WorkSubmission(work=item, execution_id=item.work_id)
        try:
            execution_id = self._backend.submit(item.work_id, priority=priority)
        except Exception as exc:
            detail = " ".join(str(exc).split())[:400]
            reason = f"durable execution could not be submitted: {type(exc).__name__}"
            if detail:
                reason += f": {detail}"
            failed = item.transition(
                WorkState.FAILED,
                status_detail=reason,
            )
            failed = self._store.save(failed, expected_version=item.version)
            self._store.enqueue_delivery(
                work=failed,
                kind=WorkDeliveryKind.FAILURE,
                message=reason,
                event_key=f"failure:{failed.version}",
            )
            raise
        if execution_id != item.work_id:
            reason = "durable backend returned a mismatched execution id"
            failed = item.transition(
                WorkState.FAILED,
                status_detail=reason,
            )
            failed = self._store.save(failed, expected_version=item.version)
            self._store.enqueue_delivery(
                work=failed,
                kind=WorkDeliveryKind.FAILURE,
                message=reason,
                event_key=f"failure:{failed.version}",
            )
            raise RuntimeError("durable backend must use work_id as execution_id")
        self._store.set_execution_id(item.work_id, execution_id)
        return WorkSubmission(work=item, execution_id=execution_id)

    def get(self, work_id: str) -> WorkItem:
        return self._store.require(work_id)

    def reconcile_active(self, *, limit: int = 10_000) -> tuple[str, ...]:
        """Idempotently ensure canonical active WorkItems have durable executions."""

        reconciled: list[str] = []
        for item in self.list_active(limit=limit):
            if item.work_type in self._EVENT_DRIVEN_WORK_TYPES:
                reconciled.append(item.work_id)
                continue
            bound_execution = self._store.get_execution_id(item.work_id)
            if bound_execution is not None and bound_execution != item.work_id:
                # Retry executions intentionally use a non-canonical DBOS ID. After
                # graceful shutdown they may be durably parked as CANCELLED, so let
                # production backends resume that exact execution instead of creating
                # a second canonical executor for the same WorkItem.
                reconcile_execution = getattr(
                    self._backend,
                    "reconcile_execution",
                    None,
                )
                if callable(reconcile_execution):
                    resumed_id = reconcile_execution(bound_execution)
                    if resumed_id != bound_execution:
                        raise RuntimeError(
                            "durable backend changed retry execution identity"
                        )
                reconciled.append(item.work_id)
                continue
            execution_id = self._backend.submit(item.work_id, priority=item.priority)
            if execution_id != item.work_id:
                raise RuntimeError("durable backend must use work_id as execution_id")
            self._store.set_execution_id(item.work_id, execution_id)
            reconciled.append(item.work_id)
        return tuple(reconciled)

    def list_active(self, *, limit: int = 100) -> tuple[WorkItem, ...]:
        return self._store.list(
            states=(
                WorkState.QUEUED,
                WorkState.RUNNING,
                WorkState.WAITING_RESOURCE,
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
            self._store.clear_sensitive_inputs(item.work_id)
            return item

        # First make the durable cancellation request. If that fails, canonical
        # truth must remain active instead of falsely claiming terminal cancel.
        if item.work_type not in self._EVENT_DRIVEN_WORK_TYPES:
            execution_id = self._store.get_execution_id(work_id) or work_id
            self._backend.cancel(
                execution_id,
                idempotency_key=f"cancel:{item.version}",
            )

        # The engine may advance one optimistic version while cancellation is
        # being requested. Re-read and CAS the latest non-terminal state so an
        # already-running atomic executor cannot later resurrect the WorkItem.
        for _ in range(8):
            latest = self._store.require(work_id)
            if latest.state.terminal:
                self._store.clear_sensitive_inputs(latest.work_id)
                return latest
            cancelled = latest.transition(
                WorkState.CANCELLED,
                status_detail="cancelled by owner",
                current_step_id=latest.current_step_id,
            )
            try:
                saved = self._store.save(
                    cancelled,
                    expected_version=latest.version,
                )
                self._store.clear_sensitive_inputs(saved.work_id)
                return saved
            except WorkStoreError as exc:
                if "stale work update rejected" not in str(exc):
                    raise

        raise WorkStoreError(
            f"could not persist cancellation after repeated concurrent updates: {work_id}"
        )

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
        if item.work_type not in self._EVENT_DRIVEN_WORK_TYPES:
            execution_id = self._store.get_execution_id(work_id) or work_id
            self._backend.pause(execution_id)
        return saved

    def resume(self, work_id: str) -> WorkItem:
        item = self._store.require(work_id)
        if item.state is not WorkState.PAUSED:
            raise ValueError("only paused work can be resumed")
        target_state = (
            item.paused_from_state
            if item.paused_from_state
            in {
                WorkState.QUEUED,
                WorkState.WAITING_RESOURCE,
                WorkState.WAITING_DEPENDENCY,
                WorkState.WAITING_UNTIL,
                WorkState.WAITING_FOR_OWNER,
            }
            else WorkState.RUNNING
        )
        resumed = item.transition(
            target_state,
            status_detail="resumed by owner",
            current_step_id=item.current_step_id,
        )
        saved = self._store.save(resumed, expected_version=item.version)
        if item.work_type in self._EVENT_DRIVEN_WORK_TYPES:
            return saved
        try:
            execution_id = self._store.get_execution_id(work_id) or work_id
            self._backend.resume(
                execution_id,
                idempotency_key=f"resume:{item.version}",
            )
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

    def retry_failed(
        self,
        work_id: str,
        *,
        owner_request: str,
        source_session_id: str,
        source_turn_id: str,
    ) -> WorkItem:
        """Retry failed canonical work without losing its identity or evidence."""

        item = self._store.require(work_id)
        if item.state is not WorkState.FAILED:
            raise ValueError("only failed work can be retried")
        if item.work_type in self._EVENT_DRIVEN_WORK_TYPES:
            raise ValueError(
                "event-driven monitoring retry requires the owning goal to be re-armed"
            )
        normalized = owner_request.strip()
        if not normalized:
            raise ValueError("retry request must not be empty")

        retry_step = WorkStep(
            work_id=item.work_id,
            kind="owner_retry",
            summary="Owner requested retry of failed work",
            input_data={
                "source_session_id": source_session_id,
                "source_turn_id": source_turn_id,
            },
        )
        self._store.add_step(retry_step)
        self._store.save_step(retry_step.start().complete({"response": normalized}))

        retrying = item.transition(
            WorkState.RETRYING,
            status_detail="retry requested by owner",
            current_step_id=None,
        )
        saved = self._store.save(retrying, expected_version=item.version)
        try:
            execution_id = self._backend.restart(
                saved.work_id,
                priority=saved.priority,
                retry_token=f"v{saved.version}",
            )
            self._store.set_execution_id(saved.work_id, execution_id)
        except Exception as exc:
            latest = self._store.require(saved.work_id)
            failed = latest.transition(
                WorkState.FAILED,
                status_detail=f"retry submission failed: {type(exc).__name__}: {exc}",
                current_step_id=latest.current_step_id,
            )
            failed = self._store.save(failed, expected_version=latest.version)
            self._store.enqueue_delivery(
                work=failed,
                kind=WorkDeliveryKind.FAILURE,
                message=failed.status_detail or "Background work retry failed.",
                event_key=f"failure:{failed.version}",
            )
            raise
        return saved

    def reprioritize(self, work_id: str, priority: WorkPriority) -> WorkItem:
        item = self._store.require(work_id)
        updated = item.with_priority(priority)
        if updated is item:
            return item
        return self._store.save(updated, expected_version=item.version)
