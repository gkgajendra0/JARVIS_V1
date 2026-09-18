"""DBOS durable execution adapter for JARVIS WorkItems."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from dbos import DBOS, DBOSConfig, SetEnqueueOptions, SetWorkflowID

from jarvis.work.engine import WorkEngine
from jarvis.work.models import WorkPriority, WorkState

_QUEUE_NAME = "jarvis-work"
_OWNER_TOPIC = "owner-input"
_EVENT_STATE = "jarvis-work-state"
_DEFAULT_GLOBAL_CONCURRENCY = 4
_MAX_REASONING_CYCLES = 200

_ENGINE: WorkEngine | None = None


def configure_work_engine(engine: WorkEngine) -> None:
    global _ENGINE
    if _ENGINE is not None and _ENGINE is not engine:
        raise RuntimeError("JARVIS work engine is already configured")
    _ENGINE = engine


def _engine() -> WorkEngine:
    if _ENGINE is None:
        raise RuntimeError("JARVIS work engine is not configured")
    return _ENGINE


def _queue_priority(priority: WorkPriority) -> int:
    return {
        WorkPriority.URGENT: 1,
        WorkPriority.HIGH: 10,
        WorkPriority.NORMAL: 100,
        WorkPriority.LOW: 1000,
    }[priority]


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
async def _advance_work(work_id: str) -> dict[str, Any]:
    result = await _engine().advance(work_id)
    return asdict(result)


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _apply_owner_input(work_id: str, response: str) -> str:
    return _engine().apply_owner_input(work_id, response).state.value


@DBOS.workflow(max_recovery_attempts=20)
async def durable_workflow(work_id: str) -> dict[str, Any]:
    for _ in range(_MAX_REASONING_CYCLES):
        payload = await _advance_work(work_id)
        state = WorkState(str(payload["state"]))
        await DBOS.set_event_async(_EVENT_STATE, payload)

        if state.terminal:
            return payload
        if state is WorkState.WAITING_FOR_OWNER:
            while True:
                owner_input = await DBOS.recv_async(
                    topic=_OWNER_TOPIC,
                    timeout_seconds=3600,
                )
                if owner_input is None:
                    continue
                await _apply_owner_input(work_id, str(owner_input))
                break
        elif state is WorkState.PAUSED:
            return payload

    raise RuntimeError("JARVIS work exceeded bounded reasoning cycle limit")


class DBOSWorkExecutionBackend:
    """Queue/recovery mechanics only; canonical work truth remains in JARVIS store."""

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        with SetWorkflowID(work_id), SetEnqueueOptions(
            priority=_queue_priority(priority)
        ):
            handle = DBOS.enqueue_workflow(_QUEUE_NAME, durable_workflow, work_id)
        if handle.workflow_id != work_id:
            raise RuntimeError("DBOS did not preserve canonical JARVIS work ID")
        return handle.workflow_id

    def cancel(self, execution_id: str) -> None:
        DBOS.cancel_workflow(execution_id, cancel_children=True)

    def resume(self, execution_id: str) -> None:
        DBOS.resume_workflow(execution_id, queue_name=_QUEUE_NAME)

    def send_owner_input(self, work_id: str, response: str) -> None:
        normalized = response.strip()
        if not normalized:
            raise ValueError("owner response must not be empty")
        DBOS.send(work_id, normalized, topic=_OWNER_TOPIC)


def initialize_dbos_work_runtime(
    *,
    engine: WorkEngine,
    application_version: str,
    global_concurrency: int = _DEFAULT_GLOBAL_CONCURRENCY,
    system_database_url: str | None = None,
) -> DBOSWorkExecutionBackend:
    if global_concurrency <= 0:
        raise ValueError("work global concurrency must be positive")
    configure_work_engine(engine)
    config: DBOSConfig = {
        "name": "jarvis-v1-work",
        "application_version": application_version,
        "system_database_url": (
            system_database_url
            or os.getenv("JARVIS_WORK_DBOS_DATABASE_URL")
            or None
        ),
    }
    DBOS(config=config)
    DBOS.launch()
    DBOS.register_queue(_QUEUE_NAME, global_concurrency=global_concurrency)
    return DBOSWorkExecutionBackend()


def shutdown_dbos_work_runtime() -> None:
    DBOS.destroy()
