"""Canonical durable-execution binding and restart recovery for JARVIS WorkItems."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from jarvis.work.models import WorkItem, WorkPriority


class DurableExecutionStore(Protocol):
    def get_execution_id(self, work_id: str) -> str | None: ...

    def set_execution_id(self, work_id: str, execution_id: str) -> None: ...


class DurableExecutionBackend(Protocol):
    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...


def ensure_durable_execution(
    *,
    store: DurableExecutionStore,
    backend: DurableExecutionBackend,
    item: WorkItem,
) -> str:
    """Ensure one canonical active WorkItem has exactly one durable execution.

    Production DBOS backends may expose richer restart hooks. Recovery is always
    attempted before ordinary submission so legacy WorkItems that lost their
    execution binding can still discover and safely rebind an existing canonical
    DBOS workflow.
    """

    bound_execution = store.get_execution_id(item.work_id)
    recover_execution = getattr(backend, "recover_execution", None)
    reconcile_execution = getattr(backend, "reconcile_execution", None)

    if callable(recover_execution):
        recovery_source = bound_execution or item.work_id
        predecessor_digest = sha256(recovery_source.encode()).hexdigest()[:12]
        recovery_token = f"startup_recovery_{predecessor_digest}"
        execution_id = recover_execution(
            recovery_source,
            work_id=item.work_id,
            priority=item.priority,
            recovery_token=recovery_token,
        )
        retry_prefix = f"{item.work_id}__retry_"
        if execution_id != item.work_id and not execution_id.startswith(retry_prefix):
            raise RuntimeError(
                "durable backend returned an invalid recovery execution id"
            )
        if bound_execution != execution_id:
            store.set_execution_id(item.work_id, execution_id)
        return execution_id

    if bound_execution is not None and callable(reconcile_execution):
        execution_id = reconcile_execution(bound_execution)
        if execution_id != bound_execution:
            raise RuntimeError("durable backend changed retry execution identity")
        return execution_id

    if bound_execution is not None and bound_execution != item.work_id:
        # A non-canonical retry execution is already authoritative. A backend
        # without restart reconciliation support must never create a duplicate.
        return bound_execution

    execution_id = backend.submit(item.work_id, priority=item.priority)
    if execution_id != item.work_id:
        raise RuntimeError("durable backend must use work_id as execution_id")
    store.set_execution_id(item.work_id, execution_id)
    return execution_id
