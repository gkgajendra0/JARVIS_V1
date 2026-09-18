"""Composition root for persistent concurrent JARVIS work."""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from jarvis.knowledge.research import CurrentResearchService
from jarvis.work.actions import ResearchWorkExecutor
from jarvis.work.brain import BrainCoordinator, InteractiveBrainGate
from jarvis.work.development import (
    DevelopmentWorkspaceManager,
    build_development_executors,
    build_development_test_runner,
)
from jarvis.work.dbos_backend import (
    DBOSWorkExecutionBackend,
    initialize_dbos_work_runtime,
    shutdown_dbos_work_runtime,
)
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.reasoner import ProviderWorkReasoner
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


def _application_version() -> str:
    try:
        return version("jarvis")
    except PackageNotFoundError:
        return "0.1.0"


class WorkRuntime:
    """Long-lived work subsystem that survives individual voice conversations."""

    def __init__(
        self,
        *,
        store: SQLiteWorkStore,
        engine: WorkEngine,
        backend: DBOSWorkExecutionBackend,
        orchestrator: WorkOrchestrator,
        supported_work_types: frozenset[WorkType],
        interactive_brain_gate: InteractiveBrainGate,
    ) -> None:
        self.store = store
        self.engine = engine
        self.backend = backend
        self.orchestrator = orchestrator
        self.supported_work_types = supported_work_types
        self._interactive_brain_gate = interactive_brain_gate
        self._closed = False

    def supports(self, work_type: WorkType) -> bool:
        return work_type in self.supported_work_types

    @property
    def interactive_brain_active(self) -> bool:
        return self._interactive_brain_gate.interactive_active

    def set_interactive_brain_active(self, active: bool) -> None:
        self._interactive_brain_gate.set_interactive_active(active)

    def submit_owner_input(self, work_id: str, response: str) -> WorkItem:
        work = self.store.require(work_id)
        if work.state is not WorkState.WAITING_FOR_OWNER:
            raise ValueError("work is not waiting for owner input")
        self.backend.send_owner_input(work_id, response)
        return work

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        shutdown_dbos_work_runtime()


async def build_work_runtime(
    *,
    provider: str,
    research_service: CurrentResearchService,
    model: str | None = None,
    global_concurrency: int = 4,
    development_test_image: str | None = None,
    store_path: str | Path | None = None,
    dbos_database_url: str | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> WorkRuntime:
    """Build one durable work runtime around the configured JARVIS brain provider."""

    loop = event_loop or asyncio.get_running_loop()
    store = SQLiteWorkStore(store_path or default_work_store_path())
    reasoner = ProviderWorkReasoner(provider=provider, model=model)
    interactive_brain_gate = InteractiveBrainGate()
    brain = BrainCoordinator(
        reasoner,
        interactive_gate=interactive_brain_gate,
    )
    workspace_manager = DevelopmentWorkspaceManager()
    executors = (
        ResearchWorkExecutor(research_service),
        *build_development_executors(
            workspace_manager,
            test_runner=build_development_test_runner(development_test_image),
        ),
    )
    actions = WorkActionRegistry(tuple(executors))
    resources = ResourceLeaseManager(
        {
            "cpu": max(1, min(2, global_concurrency)),
            "git": 1,
            "network": max(1, global_concurrency),
        }
    )
    engine = WorkEngine(
        store=store,
        brain=brain,
        actions=actions,
        resources=resources,
    )
    backend = await initialize_dbos_work_runtime(
        engine=engine,
        event_loop=loop,
        application_version=_application_version(),
        queue_concurrency=None,
        system_database_url=dbos_database_url,
    )
    orchestrator = WorkOrchestrator(store, backend)
    return WorkRuntime(
        store=store,
        engine=engine,
        backend=backend,
        orchestrator=orchestrator,
        supported_work_types=actions.supported_work_types,
        interactive_brain_gate=interactive_brain_gate,
    )
