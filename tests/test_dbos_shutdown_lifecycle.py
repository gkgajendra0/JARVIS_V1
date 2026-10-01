from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
from types import SimpleNamespace

import pytest

import jarvis.work.dbos_backend as dbos_backend
import jarvis.work.runtime as work_runtime_module
from jarvis.work.dbos_backend import DBOSWorkExecutionBackend
from jarvis.work.models import WorkPriority, WorkState
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.runtime import WorkRuntime


class _FakeGate:
    def __init__(self) -> None:
        self.preempted = False

    def preempt_background_for_shutdown(self) -> None:
        self.preempted = True


class _FakeShutdownStore:
    def __init__(self) -> None:
        self.execution_ids = {
            "work-a": "work-a",
            "work-b": "work-b__retry_v3",
        }

    def get_execution_id(self, work_id: str) -> str | None:
        return self.execution_ids.get(work_id)


class _FakeShutdownOrchestrator:
    def list_active(self, *, limit: int = 100):
        assert limit == 10_000
        return (
            SimpleNamespace(work_id="work-a"),
            SimpleNamespace(work_id="work-b"),
        )


class _FakeShutdownBackend:
    def __init__(self) -> None:
        self.began_shutdown = False
        self.parked: tuple[str, ...] = ()
        self.quiesced = False

    def begin_shutdown(self) -> None:
        self.began_shutdown = True

    def park_for_shutdown(self, execution_ids: tuple[str, ...]) -> tuple[str, ...]:
        self.parked = execution_ids
        return execution_ids

    async def quiesce_active_advances(self, *, timeout_seconds: float = 5.0) -> int:
        assert timeout_seconds == 5.0
        self.quiesced = True
        return len(self.parked)


@pytest.mark.asyncio
async def test_work_runtime_shutdown_keeps_event_loop_alive_during_dbos_drain(
    monkeypatch,
) -> None:
    runtime = object.__new__(WorkRuntime)
    runtime._closed = False
    runtime._interactive_brain_gate = _FakeGate()
    runtime._status_update_task = None
    runtime._release_bridge_task = None
    runtime._autonomy_periodic_reconciler = None
    runtime.store = _FakeShutdownStore()
    runtime.orchestrator = _FakeShutdownOrchestrator()
    runtime.backend = _FakeShutdownBackend()

    loop = asyncio.get_running_loop()
    observed: list[str] = []
    shutdown_timeouts: list[int] = []

    async def event_loop_probe() -> str:
        await asyncio.sleep(0)
        return "event-loop-alive"

    def fake_shutdown_dbos_work_runtime(
        *,
        workflow_completion_timeout_sec: int = 0,
    ) -> None:
        shutdown_timeouts.append(workflow_completion_timeout_sec)
        future = asyncio.run_coroutine_threadsafe(event_loop_probe(), loop)
        observed.append(future.result(timeout=2.0))

    monkeypatch.setattr(
        work_runtime_module,
        "shutdown_dbos_work_runtime",
        fake_shutdown_dbos_work_runtime,
    )

    await runtime.aclose()

    assert runtime.backend.began_shutdown is True
    assert runtime._interactive_brain_gate.preempted is True
    assert runtime.backend.parked == ("work-a", "work-b__retry_v3")
    assert runtime.backend.quiesced is True
    assert observed == ["event-loop-alive"]
    assert shutdown_timeouts == [10]


def test_dbos_backend_resumes_exact_cancelled_execution(monkeypatch) -> None:
    backend = DBOSWorkExecutionBackend()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        dbos_backend,
        "_run_dbos_sync",
        lambda callable_, /, *args, **kwargs: callable_(*args, **kwargs),
    )
    monkeypatch.setattr(
        dbos_backend.DBOS,
        "get_workflow_status",
        staticmethod(
            lambda workflow_id: SimpleNamespace(
                workflow_id=workflow_id,
                status="CANCELLED",
            )
        ),
    )

    class _Handle:
        def __init__(self, workflow_id: str) -> None:
            self._workflow_id = workflow_id

        def get_workflow_id(self) -> str:
            return self._workflow_id

    def resume_workflow(workflow_id: str, *, queue_name: str | None = None):
        calls.append(("resume", (workflow_id, queue_name)))
        return _Handle(workflow_id)

    monkeypatch.setattr(
        dbos_backend.DBOS,
        "resume_workflow",
        staticmethod(resume_workflow),
    )

    assert backend.reconcile_execution("work-a__retry_v3") == "work-a__retry_v3"
    assert calls == [("resume", ("work-a__retry_v3", "jarvis-work"))]


def test_dbos_backend_parks_exact_execution_ids(monkeypatch) -> None:
    backend = DBOSWorkExecutionBackend()
    cancelled: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        dbos_backend,
        "_run_dbos_sync",
        lambda callable_, /, *args, **kwargs: callable_(*args, **kwargs),
    )

    def cancel_workflows(workflow_ids: list[str]) -> None:
        cancelled.append(tuple(workflow_ids))

    monkeypatch.setattr(
        dbos_backend.DBOS,
        "cancel_workflows",
        staticmethod(cancel_workflows),
    )

    parked = backend.park_for_shutdown(
        ("work-b__retry_v3", "work-a", "work-a", ""),
    )

    assert parked == ("work-a", "work-b__retry_v3")
    assert cancelled == [("work-a", "work-b__retry_v3")]


class _RetryStore:
    def __init__(self) -> None:
        self.item = SimpleNamespace(
            work_id="work-retry",
            state=WorkState.RETRYING,
            priority=WorkPriority.HIGH,
        )
        self.execution_id = "work-retry__retry_v4"

    def list(self, *, states, limit):
        del states, limit
        return (self.item,)

    def get_execution_id(self, work_id: str) -> str | None:
        assert work_id == self.item.work_id
        return self.execution_id

    def set_execution_id(self, work_id: str, execution_id: str) -> None:
        raise AssertionError(
            f"retry reconciliation must not replace {work_id} with {execution_id}"
        )


class _RetryBackend:
    def __init__(self) -> None:
        self.reconciled: list[str] = []
        self.submitted: list[str] = []

    def reconcile_execution(self, execution_id: str) -> str:
        self.reconciled.append(execution_id)
        return execution_id

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def test_orchestrator_reconciles_parked_retry_without_duplicate_submission() -> None:
    store = _RetryStore()
    backend = _RetryBackend()
    orchestrator = WorkOrchestrator(store, backend)

    assert orchestrator.reconcile_active() == ("work-retry",)
    assert backend.reconciled == ["work-retry__retry_v4"]
    assert backend.submitted == []



@pytest.mark.asyncio
async def test_active_engine_advance_unwinds_before_dbos_teardown(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    released = asyncio.Event()

    class _BlockingEngine:
        async def advance(self, work_id: str):
            assert work_id == "work-active"
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

    monkeypatch.setattr(dbos_backend, "_ENGINE", _BlockingEngine())
    monkeypatch.setattr(
        dbos_backend,
        "_JARVIS_EVENT_LOOP",
        asyncio.get_running_loop(),
    )
    monkeypatch.setattr(dbos_backend, "_ADVANCE_QUIESCING", False)
    with dbos_backend._ACTIVE_ADVANCE_LOCK:
        dbos_backend._ACTIVE_ADVANCES.clear()

    backend = DBOSWorkExecutionBackend()
    worker = asyncio.create_task(
        asyncio.to_thread(dbos_backend._run_advance_work, "work-active")
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    backend.begin_shutdown()
    quiesced = await backend.quiesce_active_advances(timeout_seconds=1.0)

    assert quiesced == 1
    assert released.is_set()
    with pytest.raises(FutureCancelledError):
        await worker
