"""DBOS durable execution adapter for JARVIS WorkItems."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from dbos import DBOS, DBOSConfig, SetEnqueueOptions, SetWorkflowID

from jarvis.work.engine import WorkEngine
from jarvis.work.models import WorkPriority, WorkState
from jarvis.work.store import default_work_state_dir

_QUEUE_NAME = "jarvis-work"
_OWNER_TOPIC = "owner-input"
_CONTROL_TOPIC = "work-control"
_RUNTIME_WAKE_TOPIC = "runtime-wake"
_SHUTDOWN_WAKE_COMMAND = "__jarvis_shutdown_wake__"
_EVENT_STATE = "jarvis-work-state"
_MAX_REASONING_CYCLES = 200
_WAITING_STATES = frozenset(
    {
        WorkState.WAITING_RESOURCE,
        WorkState.WAITING_DEPENDENCY,
        WorkState.WAITING_UNTIL,
        WorkState.WAITING_FOR_OWNER,
        WorkState.PAUSED,
    }
)

_ENGINE: WorkEngine | None = None
_JARVIS_EVENT_LOOP: asyncio.AbstractEventLoop | None = None
_ON_WORK_TERMINAL: Callable[[str], object] | None = None
_ACTIVE_ADVANCE_LOCK = threading.Lock()
_ACTIVE_ADVANCES: dict[Future[Any], threading.Event] = {}
_ADVANCE_QUIESCING = False


def configure_terminal_reconciliation(callback: Callable[[str], object]) -> None:
    global _ON_WORK_TERMINAL
    _ON_WORK_TERMINAL = callback


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
    global _ADVANCE_QUIESCING
    with _ACTIVE_ADVANCE_LOCK:
        if _ACTIVE_ADVANCES:
            raise RuntimeError("JARVIS work runtime still has active engine advances")
        _ADVANCE_QUIESCING = False
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


def _run_dbos_sync(callable_, /, *args, **kwargs):
    """Keep DBOS synchronous APIs off JARVIS's active asyncio event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return callable_(*args, **kwargs)

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="jarvis-dbos-call",
    ) as pool:
        return pool.submit(callable_, *args, **kwargs).result()


def _consumes_reasoning_budget(state: WorkState) -> bool:
    return not state.terminal and state not in _WAITING_STATES


def _queue_priority(priority: WorkPriority) -> int:
    return {
        WorkPriority.URGENT: 1,
        WorkPriority.HIGH: 10,
        WorkPriority.NORMAL: 100,
        WorkPriority.LOW: 1000,
    }[priority]


def _waiting_resource_delay(payload: dict[str, Any]) -> float:
    raw = payload.get("retry_after_seconds")
    if raw is None:
        return 0.25
    try:
        delay = float(raw)
    except (TypeError, ValueError):
        return 0.25
    if delay <= 0:
        return 0.25
    return min(delay, 60.0)


def _durable_interruptible_wait(seconds: float, *, patch_name: str) -> None:
    """Preserve absolute durable timing while making new waits wakeable.

    Historical workflow executions may already have a DBOS.sleep checkpoint at
    this position. DBOS.patch replays that exact legacy sleep once. New history
    uses DBOS.recv with a timeout instead: DBOS persists the absolute timeout,
    while JARVIS can wake the wait immediately on shutdown through a dedicated
    runtime topic. A normal timeout returns None and changes no WorkItem truth.
    """

    delay = max(0.0, float(seconds))
    if delay <= 0:
        return
    if not DBOS.patch(patch_name):
        DBOS.sleep(delay)
        return
    DBOS.recv(
        topic=_RUNTIME_WAKE_TOPIC,
        timeout_seconds=delay,
    )


async def _advance_on_jarvis_loop(
    work_id: str,
    completion: threading.Event,
):
    try:
        return await _engine().advance(work_id)
    finally:
        # This event is stronger than concurrent Future.done(): it is set only
        # after the canonical asyncio coroutine has actually unwound.
        completion.set()


def _run_advance_work(work_id: str) -> dict[str, Any]:
    """Run one engine advance while exposing a shutdown completion barrier."""

    completion = threading.Event()
    with _ACTIVE_ADVANCE_LOCK:
        if _ADVANCE_QUIESCING:
            raise RuntimeError("JARVIS work runtime is quiescing")
        future = asyncio.run_coroutine_threadsafe(
            _advance_on_jarvis_loop(work_id, completion),
            _jarvis_loop(),
        )
        _ACTIVE_ADVANCES[future] = completion

    try:
        result = future.result()
    finally:
        with _ACTIVE_ADVANCE_LOCK:
            _ACTIVE_ADVANCES.pop(future, None)

    return {
        "work_id": result.work_id,
        "state": result.state.value,
        "progressed": result.progressed,
        "owner_question": result.owner_question,
        "retry_after_seconds": result.retry_after_seconds,
    }


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _advance_work(work_id: str) -> dict[str, Any]:
    """Run one async JARVIS cycle on the canonical production event loop."""

    return _run_advance_work(work_id)


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _apply_owner_input(work_id: str, response: str) -> str:
    return _engine().apply_owner_input(work_id, response).state.value


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=1.0)
def _fail_bounded_work(work_id: str) -> str:
    return (
        _engine()
        .fail(
            work_id,
            "bounded reasoning cycle budget exceeded",
        )
        .state.value
    )


@DBOS.workflow(max_recovery_attempts=20)
def durable_workflow(
    work_id: str,
    max_reasoning_cycles: int = _MAX_REASONING_CYCLES,
) -> dict[str, Any]:
    """Durable outer loop. Waiting time never consumes semantic-work budget."""

    if max_reasoning_cycles <= 0:
        raise ValueError("max reasoning cycles must be positive")
    reasoning_cycles = 0
    while reasoning_cycles < max_reasoning_cycles:
        payload = _advance_work(work_id)
        state = WorkState(payload["state"])
        if state.terminal and _ON_WORK_TERMINAL is not None:
            _ON_WORK_TERMINAL(work_id)
        DBOS.set_event(_EVENT_STATE, payload)

        if state.terminal:
            return payload

        if _consumes_reasoning_budget(state):
            reasoning_cycles += 1

        if state is WorkState.WAITING_FOR_OWNER:
            owner_input = DBOS.recv(
                topic=_OWNER_TOPIC,
                timeout_seconds=1,
            )
            if owner_input is not None:
                _apply_owner_input(work_id, str(owner_input))

        elif state is WorkState.WAITING_RESOURCE:
            _durable_interruptible_wait(
                _waiting_resource_delay(payload),
                patch_name="wakeable-waiting-resource-v1",
            )

        elif state in {
            WorkState.WAITING_DEPENDENCY,
            WorkState.WAITING_UNTIL,
            WorkState.RETRYING,
        }:
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
    if _ON_WORK_TERMINAL is not None:
        _ON_WORK_TERMINAL(work_id)
    return {
        "work_id": work_id,
        "state": state,
        "progressed": True,
        "owner_question": None,
    }


class DBOSWorkExecutionBackend:
    """Queue/recovery mechanics only; canonical work truth remains in JARVIS store."""

    _ACTIVE_DBOS_STATES = frozenset({"PENDING", "ENQUEUED", "DELAYED"})
    _RESUMABLE_DBOS_STATES = frozenset({"CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"})
    _TERMINAL_DBOS_STATES = frozenset({"SUCCESS", "ERROR"})
    _RECOVERABLE_TERMINAL_DBOS_STATES = frozenset({"ERROR"})

    def __init__(
        self,
        *,
        max_reasoning_cycles: int = _MAX_REASONING_CYCLES,
    ) -> None:
        if isinstance(max_reasoning_cycles, bool) or max_reasoning_cycles <= 0:
            raise ValueError("max reasoning cycles must be positive")
        self._max_reasoning_cycles = int(max_reasoning_cycles)
        self._accepting_work = True

    def begin_shutdown(self) -> None:
        """Stop new work and prevent DBOS from starting another engine advance."""

        global _ADVANCE_QUIESCING
        self._accepting_work = False
        with _ACTIVE_ADVANCE_LOCK:
            _ADVANCE_QUIESCING = True

    async def quiesce_active_advances(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> int:
        """Await active atomic engine advances without cancelling side effects."""

        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("advance quiesce timeout must be positive")

        with _ACTIVE_ADVANCE_LOCK:
            active = tuple(_ACTIVE_ADVANCES.items())

        loop = asyncio.get_running_loop()
        deadline = None if timeout_seconds is None else loop.time() + timeout_seconds
        while True:
            incomplete = [
                completion for _future, completion in active if not completion.is_set()
            ]
            if not incomplete:
                return len(active)
            if deadline is not None and loop.time() >= deadline:
                raise RuntimeError(
                    "active JARVIS work did not quiesce before DBOS shutdown"
                )
            # Existing provider reasoning is preempted separately by
            # InteractiveBrainGate. Actions already admitted are atomic from the
            # durable-work perspective and must finish rather than be cancelled
            # after an external side effect may already have occurred.
            await asyncio.sleep(0.01)

    def _require_accepting_work(self) -> None:
        if not self._accepting_work:
            raise RuntimeError("JARVIS work runtime is shutting down")

    @classmethod
    def _classify_existing_status(cls, status: object | None) -> str | None:
        if status is None:
            return None
        value = str(getattr(status, "status", "")).strip().upper()
        if not value:
            raise RuntimeError("DBOS returned a workflow status without a state")
        return value

    def _resume_existing(self, execution_id: str) -> str:
        handle = _run_dbos_sync(
            DBOS.resume_workflow,
            execution_id,
            queue_name=_QUEUE_NAME,
        )
        workflow_id = handle.get_workflow_id()
        if workflow_id != execution_id:
            raise RuntimeError("DBOS did not preserve resumed workflow identity")
        return workflow_id

    def reconcile_execution(self, execution_id: str) -> str:
        """Ensure a known durable execution is runnable after restart.

        Shutdown parking deliberately uses DBOS cancellation without changing the
        canonical JARVIS WorkItem state. On restart, CANCELLED DBOS executions are
        resumed from their last durable checkpoint instead of creating duplicate
        WorkItems or workflow identities.
        """

        self._require_accepting_work()
        normalized = str(execution_id).strip()
        if not normalized:
            raise ValueError("execution id must not be empty")
        status = _run_dbos_sync(DBOS.get_workflow_status, normalized)
        state = self._classify_existing_status(status)
        if state is None:
            raise RuntimeError(f"durable execution is missing from DBOS: {normalized}")
        if state in self._ACTIVE_DBOS_STATES:
            return normalized
        if state in self._RESUMABLE_DBOS_STATES:
            return self._resume_existing(normalized)
        if state in self._TERMINAL_DBOS_STATES:
            raise RuntimeError(
                "canonical JARVIS work is active but its DBOS execution is "
                f"terminal: {normalized} ({state})"
            )
        raise RuntimeError(f"unsupported DBOS workflow state for {normalized}: {state}")

    def recover_execution(
        self,
        execution_id: str,
        *,
        work_id: str,
        priority: WorkPriority,
        recovery_token: str,
    ) -> str:
        """Recover one canonical-active execution without replaying side effects.

        This hook is called only after WorkEngine startup reconciliation. Any
        executor step that was in-flight at process loss has therefore already
        been marked INTERRUPTED and moved to WAITING_FOR_OWNER. A terminal ERROR
        can then be rebound to a fresh DBOS workflow ID for the same canonical
        WorkItem without silently replaying the unverified step.
        """

        self._require_accepting_work()
        normalized = str(execution_id).strip()
        if not normalized:
            raise ValueError("execution id must not be empty")
        status = _run_dbos_sync(DBOS.get_workflow_status, normalized)
        state = self._classify_existing_status(status)
        if state in self._RECOVERABLE_TERMINAL_DBOS_STATES:
            return self.restart(
                work_id,
                priority=priority,
                retry_token=recovery_token,
            )
        return self.reconcile_execution(normalized)

    def park_for_shutdown(self, execution_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Durably park active executions so process shutdown can drain safely."""

        normalized = tuple(
            sorted({str(item).strip() for item in execution_ids if str(item).strip()})
        )
        if not normalized:
            return ()
        _run_dbos_sync(DBOS.cancel_workflows, list(normalized))
        # Wake both durable wait classes. The control message releases PAUSED
        # workflows, including legacy 3600-second recv calls. The runtime-wake
        # message releases new WAITING_RESOURCE recv timeouts without shortening
        # their normal durable delay semantics.
        for execution_id in normalized:
            _run_dbos_sync(
                DBOS.send,
                execution_id,
                _SHUTDOWN_WAKE_COMMAND,
                topic=_CONTROL_TOPIC,
            )
            _run_dbos_sync(
                DBOS.send,
                execution_id,
                _SHUTDOWN_WAKE_COMMAND,
                topic=_RUNTIME_WAKE_TOPIC,
            )
        return normalized

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        self._require_accepting_work()
        existing = _run_dbos_sync(DBOS.get_workflow_status, work_id)
        state = self._classify_existing_status(existing)
        if state is not None:
            if state in self._ACTIVE_DBOS_STATES:
                return work_id
            if state in self._RESUMABLE_DBOS_STATES:
                return self._resume_existing(work_id)
            if state in self._TERMINAL_DBOS_STATES:
                raise RuntimeError(
                    "canonical JARVIS work is active but its DBOS execution is "
                    f"terminal: {work_id} ({state})"
                )
            raise RuntimeError(
                f"unsupported DBOS workflow state for {work_id}: {state}"
            )

        def enqueue():
            with (
                SetWorkflowID(work_id),
                SetEnqueueOptions(priority=_queue_priority(priority)),
            ):
                return DBOS.enqueue_workflow(
                    _QUEUE_NAME,
                    durable_workflow,
                    work_id,
                    self._max_reasoning_cycles,
                )

        handle = _run_dbos_sync(enqueue)
        workflow_id = handle.get_workflow_id()
        if workflow_id != work_id:
            raise RuntimeError("DBOS did not preserve canonical JARVIS work ID")
        return workflow_id

    def restart(
        self,
        work_id: str,
        *,
        priority: WorkPriority,
        retry_token: str,
    ) -> str:
        """Start a fresh durable execution attempt for the same canonical WorkItem."""

        self._require_accepting_work()
        token = str(retry_token).strip().replace(" ", "_")
        if not token:
            raise ValueError("retry token must not be empty")
        execution_id = f"{work_id}__retry_{token}"

        def enqueue():
            with (
                SetWorkflowID(execution_id),
                SetEnqueueOptions(priority=_queue_priority(priority)),
            ):
                return DBOS.enqueue_workflow(
                    _QUEUE_NAME,
                    durable_workflow,
                    work_id,
                    self._max_reasoning_cycles,
                )

        handle = _run_dbos_sync(enqueue)
        workflow_id = handle.get_workflow_id()
        if workflow_id != execution_id:
            raise RuntimeError("DBOS did not preserve retry execution ID")
        return workflow_id

    def cancel(
        self,
        execution_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        # Cancellation is cooperative: canonical WorkItem truth is transitioned to
        # CANCELLED by WorkOrchestrator, and the durable workflow observes that state
        # on its next bounded loop. Avoid DBOS.cancel_workflow() here because DBOS
        # reports owner-requested cancellation as a background workflow exception.
        _run_dbos_sync(
            DBOS.send,
            execution_id,
            "cancel",
            topic=_CONTROL_TOPIC,
            idempotency_key=idempotency_key,
        )

    def pause(self, execution_id: str) -> None:
        # Canonical PAUSED state is sufficient. An already-started atomic step may
        # finish safely; the durable loop observes PAUSED before starting another step.
        del execution_id

    def resume(
        self,
        execution_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        _run_dbos_sync(
            DBOS.send,
            execution_id,
            "resume",
            topic=_CONTROL_TOPIC,
            idempotency_key=idempotency_key,
        )

    def send_owner_input(
        self,
        work_id: str,
        response: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        normalized = response.strip()
        if not normalized:
            raise ValueError("owner response must not be empty")
        _run_dbos_sync(
            DBOS.send,
            work_id,
            normalized,
            topic=_OWNER_TOPIC,
            idempotency_key=idempotency_key,
        )


def initialize_dbos_work_runtime(
    *,
    engine: WorkEngine,
    event_loop: asyncio.AbstractEventLoop,
    application_version: str,
    queue_concurrency: int | None = None,
    system_database_url: str | None = None,
    max_reasoning_cycles: int = _MAX_REASONING_CYCLES,
) -> DBOSWorkExecutionBackend:
    if queue_concurrency is not None and queue_concurrency <= 0:
        raise ValueError("DBOS queue concurrency must be positive when configured")
    if isinstance(max_reasoning_cycles, bool) or max_reasoning_cycles <= 0:
        raise ValueError("max reasoning cycles must be positive")
    configure_work_engine(engine, event_loop)

    config: DBOSConfig = {
        "name": "jarvis-v1-work",
        "application_version": application_version,
        "enable_patching": True,
        "system_database_url": (
            system_database_url or default_dbos_system_database_url()
        ),
    }
    DBOS(config=config)
    DBOS.launch()
    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="jarvis-dbos-startup",
    ) as pool:
        pool.submit(
            DBOS.register_queue,
            _QUEUE_NAME,
            global_concurrency=queue_concurrency,
        ).result()
    return DBOSWorkExecutionBackend(
        max_reasoning_cycles=max_reasoning_cycles,
    )


def shutdown_dbos_work_runtime(
    *,
    workflow_completion_timeout_sec: int = 0,
) -> None:
    """Stop DBOS after a bounded drain window for already-running workflows."""

    global _ENGINE, _JARVIS_EVENT_LOOP, _ON_WORK_TERMINAL
    if (
        isinstance(workflow_completion_timeout_sec, bool)
        or workflow_completion_timeout_sec < 0
    ):
        raise ValueError("workflow completion timeout must be a non-negative integer")
    try:
        DBOS.destroy(
            workflow_completion_timeout_sec=int(workflow_completion_timeout_sec),
        )
    finally:
        _ENGINE = None
        _JARVIS_EVENT_LOOP = None
        _ON_WORK_TERMINAL = None
