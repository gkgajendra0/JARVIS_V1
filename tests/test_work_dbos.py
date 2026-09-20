from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from dbos import DBOS

from jarvis.work.dbos_backend import (
    _consumes_reasoning_budget,
    initialize_dbos_work_runtime,
    shutdown_dbos_work_runtime,
)
from jarvis.work.engine import WorkAdvanceResult
from jarvis.work.models import WorkPriority, WorkState


class ImmediateCompleteEngine:
    async def advance(self, work_id: str) -> WorkAdvanceResult:
        return WorkAdvanceResult(work_id, WorkState.COMPLETED, progressed=True)

    def apply_owner_input(self, work_id: str, response: str):
        del work_id, response
        return SimpleNamespace(state=WorkState.RUNNING)

    def fail(self, work_id: str, reason: str):
        del work_id, reason
        return SimpleNamespace(state=WorkState.FAILED)


class WaitingEngine:
    def __init__(self) -> None:
        self.waiting = asyncio.Event()

    async def advance(self, work_id: str) -> WorkAdvanceResult:
        self.waiting.set()
        return WorkAdvanceResult(
            work_id,
            WorkState.WAITING_FOR_OWNER,
            progressed=True,
            owner_question="Continue?",
        )

    def apply_owner_input(self, work_id: str, response: str):
        del work_id, response
        return SimpleNamespace(state=WorkState.RUNNING)

    def fail(self, work_id: str, reason: str):
        del work_id, reason
        return SimpleNamespace(state=WorkState.FAILED)


class RecoveredEngine:
    def __init__(self) -> None:
        self.owner_input: str | None = None

    async def advance(self, work_id: str) -> WorkAdvanceResult:
        if self.owner_input is None:
            return WorkAdvanceResult(
                work_id,
                WorkState.WAITING_FOR_OWNER,
                progressed=False,
                owner_question="Continue?",
            )
        return WorkAdvanceResult(work_id, WorkState.COMPLETED, progressed=True)

    def apply_owner_input(self, work_id: str, response: str):
        del work_id
        self.owner_input = response
        return SimpleNamespace(state=WorkState.RUNNING)

    def fail(self, work_id: str, reason: str):
        del work_id, reason
        return SimpleNamespace(state=WorkState.FAILED)


@pytest.mark.asyncio
async def test_dbos_executes_durable_work_without_blocking_event_loop(
    tmp_path,
) -> None:
    backend = initialize_dbos_work_runtime(
        engine=ImmediateCompleteEngine(),  # type: ignore[arg-type]
        event_loop=asyncio.get_running_loop(),
        application_version="test-work-v1",
        queue_concurrency=None,
        system_database_url=f"sqlite:///{(tmp_path / 'dbos.sqlite3').as_posix()}",
    )
    work_id = "work_dbos_complete"
    try:
        assert backend.submit(work_id, priority=WorkPriority.NORMAL) == work_id
        handle = await DBOS.retrieve_workflow_async(work_id)
        result = await handle.get_result()
        assert result["state"] == WorkState.COMPLETED.value
    finally:
        shutdown_dbos_work_runtime()


@pytest.mark.asyncio
async def test_dbos_recovers_waiting_work_after_runtime_restart(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'dbos-recovery.sqlite3').as_posix()}"
    first_engine = WaitingEngine()
    first_backend = initialize_dbos_work_runtime(
        engine=first_engine,  # type: ignore[arg-type]
        event_loop=asyncio.get_running_loop(),
        application_version="test-work-recovery-v1",
        queue_concurrency=None,
        system_database_url=database_url,
    )
    work_id = "work_dbos_recovery"
    first_backend.submit(work_id, priority=WorkPriority.NORMAL)
    await asyncio.wait_for(first_engine.waiting.wait(), timeout=10.0)

    shutdown_dbos_work_runtime()

    recovered_engine = RecoveredEngine()
    recovered_backend = initialize_dbos_work_runtime(
        engine=recovered_engine,  # type: ignore[arg-type]
        event_loop=asyncio.get_running_loop(),
        application_version="test-work-recovery-v1",
        queue_concurrency=None,
        system_database_url=database_url,
    )
    try:
        recovered_backend.send_owner_input(work_id, "yes")
        handle = await DBOS.retrieve_workflow_async(work_id)
        result = await asyncio.wait_for(
            handle.get_result(),
            timeout=15.0,
        )
        assert result["state"] == WorkState.COMPLETED.value
        assert recovered_engine.owner_input == "yes"
    finally:
        shutdown_dbos_work_runtime()


@pytest.mark.parametrize(
    "state",
    [
        WorkState.WAITING_RESOURCE,
        WorkState.WAITING_DEPENDENCY,
        WorkState.WAITING_UNTIL,
        WorkState.WAITING_FOR_OWNER,
        WorkState.PAUSED,
    ],
)
def test_waiting_states_do_not_consume_reasoning_budget(state: WorkState) -> None:
    assert _consumes_reasoning_budget(state) is False


@pytest.mark.parametrize(
    "state",
    [WorkState.QUEUED, WorkState.RUNNING, WorkState.RETRYING],
)
def test_active_states_consume_reasoning_budget(state: WorkState) -> None:
    assert _consumes_reasoning_budget(state) is True


def test_dbos_control_messages_use_idempotency_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str | None]] = []

    def fake_run_dbos_sync(callable_, /, *args, **kwargs):
        del callable_
        calls.append(
            (
                str(args[0]),
                str(args[1]),
                kwargs.get("idempotency_key"),
            )
        )

    monkeypatch.setattr(
        "jarvis.work.dbos_backend._run_dbos_sync",
        fake_run_dbos_sync,
    )
    from jarvis.work.dbos_backend import DBOSWorkExecutionBackend

    backend = DBOSWorkExecutionBackend()
    backend.resume("work_control", idempotency_key="resume:4")
    backend.send_owner_input(
        "work_control",
        "yes",
        idempotency_key="owner-input:7",
    )

    assert calls == [
        ("work_control", "resume", "resume:4"),
        ("work_control", "yes", "owner-input:7"),
    ]


def test_dbos_backend_rejects_invalid_reasoning_budget() -> None:
    from jarvis.work.dbos_backend import DBOSWorkExecutionBackend

    with pytest.raises(ValueError, match="max reasoning cycles"):
        DBOSWorkExecutionBackend(max_reasoning_cycles=0)
