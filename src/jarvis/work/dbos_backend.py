"""DBOS durable execution adapter for JARVIS WorkItems."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dbos import DBOS, DBOSConfig, SetEnqueueOptions, SetWorkflowID

from jarvis.work.engine import WorkEngine
from jarvis.work.models import WorkPriority, WorkState
from jarvis.work.store import default_work_state_dir

_QUEUE_NAME = "jarvis-work"
_OWNER_TOPIC = "owner-input"
_CONTROL_TOPIC = "work-control"
_EVENT_STATE = "jarvis-work-state"
_MAX_REASONING_CYCLES = 200

_ENGINE: WorkEngine | None = None
_JARVIS_EVENT_LOOP: asyncio.AbstractEventLoop | None = None


def default_dbos_system_database_url() -> str:
    path = (default_work_state_dir() / "dbos.sqlite3").resolve()
    return f"sqlite:///{path.as_posix()}"


def configure_work_engine(
    engine: WorkEngine,
    event_loop: asyncio.AbstractEventLoop,
) -> None:
    global _ENGINE, _JARVIS_EVENT_LOOP
    if _ENGINE is not None and _ENGINE is not engine:
        raise RuntimeError("JARVIS work engine is already configured")
    if _JARVIS_EVENT_LOOP is not None and _JARVIS_EVENT_LOOP is not event_loop:
        raise RuntimeError("JARVIS work event loop is already configured")
    if event_loop.is_closed():
        raise RuntimeError("JARVIS work event loop is closed")
    _ENGINE = engine
    _JARVIS_EVENT_LOOP = event_loop


def _engine() -> WorkEngine:
    if _ENGINE is None:
        raise RuntimeError("JARVIS work engine is not configured")
    return _ENGINE


def _jarvis_loop() -> asyncio.AbstractEventLoop:
    if _JARVIS_EVENT_LOOP is None or _JARVIS_EVENT_LOOP.is_closed():
        raise RuntimeError("JARVIS work event loop is unavailable")
    return _JARVIS_EVENT_LOOP


def _queue_priority(priority: WorkPriority) -> int:
    return {
        WorkPriority.URGENT: 1,
        WorkPriority.HIGH: 10,
        WorkPriority.NORMAL: 100,
        WorkPriority.LOW: 1000,
    }[priority]


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _advance_work(work_id: str) -> dict[str, Any]:
    """Run one async JARVIS cycle on the canonical production event loop."""

    future = asyncio.run_coroutine_threadsafe(
        _engine().advance(work_id),
        _jarvis_loop(),
    )
    result = future.result()
    return {
        "work_id": result.work_id,
        "state": result.state.value,
        "progressed": result.progressed,
        "owner_question": result.owner_question,
    }


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _apply_owner_input(work_id: str, response: str) -> str:
    return _engine().apply_owner_input(work_id, response).state.value


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _fail_bounded_work(work_id: str) -> str:
    return _engine().fail(
        work_id,
        "bounded reasoning cycle limit exceeded",
    ).state.value


@DBOS.workflow(max_recovery_attempts=20)
def durable_workflow(work_id: str) -> dict[str, Any]:
    """Durable outer loop. JARVIS still owns every semantic step and state."""

    for _ in range(_MAX_REASONING_CYCLES):
        payload = _advance_work(work_id)
        state = WorkState(payload["state"])
        DBOS.set_event(_EVENT_STATE, payload)

        if state.terminal:
            return payload

        if state is WorkState.WAITING_FOR_OWNER:
            owner_input = DBOS.recv(
                topic=_OWNER_TOPIC,
                timeout_seconds=1,
            )
            if owner_input is not None:
                _apply_owner_input(work_id, str(owner_input))

        elif state is WorkState.WAITING_DEPENDENCY:
            DBOS.sleep(1.0)

        elif state is WorkState.RETRYING:
            DBOS.sleep(1.0)

        elif state is WorkState.PAUSED:
            while True:
                command = DBOS.recv(
                    topic=_CONTROL_TOPIC,
                    timeout_seconds=3600,
                )
                if command == "resume":
                    break
                if command == "cancel":
                    return {
                        "work_id": work_id,
                        "state": WorkState.CANCELLED.value,
                        "progressed": False,
                        "owner_question": None,
                    }

    state = _fail_bounded_work(work_id)
    return {
        "work_id": work_id,
        "state": state,
        "progressed": True,
        "owner_question": None,
    }


class DBOSWorkExecutionBackend:
    """Queue/recovery mechanics only; canonical work truth remains in JARVIS store."""

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        with SetWorkflowID(work_id), SetEnqueueOptions(
            priority=_queue_priority(priority)
        ):
            handle = DBOS.enqueue_workflow(_QUEUE_NAME, durable_workflow, work_id)
        workflow_id = handle.get_workflow_id()
        if workflow_id != work_id:
            raise RuntimeError("DBOS did not preserve canonical JARVIS work ID")
        return workflow_id

    def cancel(self, execution_id: str) -> None:
        DBOS.send(execution_id, "cancel", topic=_CONTROL_TOPIC)
        DBOS.cancel_workflow(execution_id, cancel_children=True)

    def pause(self, execution_id: str) -> None:
        # Canonical PAUSED state is sufficient. An already-started atomic step may
        # finish safely; the durable loop observes PAUSED before starting another step.
        del execution_id

    def resume(self, execution_id: str) -> None:
        DBOS.send(execution_id, "resume", topic=_CONTROL_TOPIC)

    def send_owner_input(self, work_id: str, response: str) -> None:
        normalized = response.strip()
        if not normalized:
            raise ValueError("owner response must not be empty")
        DBOS.send(work_id, normalized, topic=_OWNER_TOPIC)


def initialize_dbos_work_runtime(
    *,
    engine: WorkEngine,
    event_loop: asyncio.AbstractEventLoop,
    application_version: str,
    queue_concurrency: int | None = None,
    system_database_url: str | None = None,
) -> DBOSWorkExecutionBackend:
    if queue_concurrency is not None and queue_concurrency <= 0:
        raise ValueError("DBOS queue concurrency must be positive when configured")
    configure_work_engine(engine, event_loop)

    config: DBOSConfig = {
        "name": "jarvis-v1-work",
        "application_version": application_version,
        "enable_patching": True,
        "system_database_url": (
            system_database_url
            or os.getenv("JARVIS_WORK_DBOS_DATABASE_URL")
            or default_dbos_system_database_url()
        ),
    }
    DBOS(config=config)
    DBOS.launch()
    DBOS.register_queue(_QUEUE_NAME, global_concurrency=queue_concurrency)
    return DBOSWorkExecutionBackend()


def shutdown_dbos_work_runtime() -> None:
    global _ENGINE, _JARVIS_EVENT_LOOP
    try:
        DBOS.destroy()
    finally:
        _ENGINE = None
        _JARVIS_EVENT_LOOP = None
