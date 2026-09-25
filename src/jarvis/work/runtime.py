"""Composition root for persistent concurrent JARVIS work."""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.store import ChangeStore
from jarvis.knowledge.research import CurrentResearchService
from jarvis.model_routing.eligibility import EligibilityPolicy
from jarvis.model_routing.invoker import (
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.registry import RoutingStrategyRegistry
from jarvis.model_routing.router import (
    ModelRouter,
    build_default_work_targets,
)
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.model_routing.strategy import EngineeringStageStrategy
from jarvis.work.actions import ResearchWorkExecutor
from jarvis.work.brain import BrainCoordinator, InteractiveBrainGate
from jarvis.work.dbos_backend import (
    DBOSWorkExecutionBackend,
    configure_terminal_reconciliation,
    initialize_dbos_work_runtime,
    shutdown_dbos_work_runtime,
)
from jarvis.work.development import (
    DevelopmentWorkspaceManager,
    build_development_executors,
    build_development_test_runner,
)
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.reasoner import RoutedWorkReasoner
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
        changes: ChangeCoordinator | None = None,
        routing_store: ModelRoutingStore | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        self.store = store
        self.engine = engine
        self.backend = backend
        self.orchestrator = orchestrator
        self.supported_work_types = supported_work_types
        self._interactive_brain_gate = interactive_brain_gate
        self.changes = changes
        self.routing_store = routing_store
        self.model_router = model_router
        self._closed = False

    def supports(self, work_type: WorkType) -> bool:
        return work_type in self.supported_work_types

    @property
    def interactive_brain_active(self) -> bool:
        return self._interactive_brain_gate.interactive_active

    def set_interactive_brain_active(self, active: bool) -> None:
        self._interactive_brain_gate.set_interactive_active(active)

    def resolve_waiting_owner_work(
        self,
        work_id: str | None = None,
    ) -> WorkItem:
        normalized = str(work_id or "").strip()
        if normalized:
            work = self.store.require(normalized)
            if work.state is not WorkState.WAITING_FOR_OWNER:
                raise ValueError("work is not waiting for owner input")
            return work

        waiting = self.store.list(
            states=(WorkState.WAITING_FOR_OWNER,),
            limit=10,
        )
        if len(waiting) == 1:
            return waiting[0]
        if not waiting:
            raise ValueError("no background work is waiting for owner input")
        raise ValueError(
            "multiple background tasks are waiting for owner input; "
            "identify the task before continuing"
        )

    def submit_owner_input(
        self,
        work_id: str | None,
        response: str,
    ) -> WorkItem:
        work = self.resolve_waiting_owner_work(work_id)
        self.backend.send_owner_input(
            work.work_id,
            response,
            idempotency_key=f"owner-input:{work.version}",
        )
        return work

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # A jarvis-dev restart must not tear DBOS down while a provider reasoning
        # cycle is still using the canonical event loop. Preempt background
        # reasoning first, then give already-running DBOS workflow code a bounded
        # window to checkpoint before database connections are closed.
        self._interactive_brain_gate.set_interactive_active(True)
        shutdown_dbos_work_runtime(workflow_completion_timeout_sec=5)


def build_work_runtime(
    *,
    provider: str,
    research_service: CurrentResearchService,
    model: str | None = None,
    global_concurrency: int = 4,
    max_reasoning_cycles: int = 64,
    min_available_memory_mb: int = 768,
    development_test_image: str | None = None,
    store_path: str | Path | None = None,
    dbos_database_url: str | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> WorkRuntime:
    """Build one durable work runtime around the configured JARVIS brain provider."""

    loop = event_loop or asyncio.get_running_loop()
    resolved_store_path = Path(store_path or default_work_store_path())
    payload_codec = build_default_work_payload_codec(resolved_store_path)
    store = SQLiteWorkStore(
        resolved_store_path,
        payload_codec=payload_codec,
    )
    store.protect_existing_payloads()
    change_store = ChangeStore(store)
    adapter_registry = build_default_model_adapter_registry()
    work_targets = build_default_work_targets(
        configured_provider=provider,
        configured_model=model,
        adapter_registry=adapter_registry,
    )
    routing_store = ModelRoutingStore(store)
    strategy_registry = RoutingStrategyRegistry((EngineeringStageStrategy(),))
    model_router = ModelRouter(
        target_registry=work_targets.registry,
        adapter_registry=adapter_registry,
        strategy_registry=strategy_registry,
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
    )
    reasoner = RoutedWorkReasoner(
        router=model_router,
        invoker=ModelInvoker(adapter_registry),
        primary_target_id=work_targets.primary_target_id,
    )
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
            "work": max(1, global_concurrency),
            "cpu": max(1, min(2, global_concurrency)),
            "git": 1,
            "network": max(1, global_concurrency),
            "gpu": 1,
            "browser": 1,
            "desktop": 1,
            "provider_api": 1,
        },
        min_available_memory_mb=min_available_memory_mb,
    )
    engine = WorkEngine(
        store=store,
        brain=brain,
        actions=actions,
        resources=resources,
        base_resource_keys=("work",),
        action_admission=change_store.work_admitted,
    )
    engine.reconcile_interrupted_steps()
    backend = initialize_dbos_work_runtime(
        engine=engine,
        event_loop=loop,
        application_version=_application_version(),
        queue_concurrency=None,
        system_database_url=dbos_database_url,
        max_reasoning_cycles=max_reasoning_cycles,
    )
    orchestrator = WorkOrchestrator(store, backend)
    orchestrator.reconcile_active()
    changes = ChangeCoordinator(change_store, backend)
    configure_terminal_reconciliation(changes.reconcile_for_work)
    changes.reconcile_active()
    return WorkRuntime(
        store=store,
        engine=engine,
        backend=backend,
        orchestrator=orchestrator,
        supported_work_types=actions.supported_work_types,
        interactive_brain_gate=interactive_brain_gate,
        changes=changes,
        routing_store=routing_store,
        model_router=model_router,
    )
