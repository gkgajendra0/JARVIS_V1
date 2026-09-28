"""Composition root for persistent concurrent JARVIS work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.activation import (
    CapabilityAcquisitionLifecycleCoordinator,
)
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.discovery_workflow import (
    build_acquisition_discovery_executors,
)
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
)
from jarvis.capability_acquisition.owner_sources import registered_source_adapters
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.promotion import (
    CapabilityAcquisitionReleaseBridge,
    CapabilityAcquisitionReleaseBridgeError,
)
from jarvis.capability_acquisition.runtime_context import (
    AcquisitionContextProvider,
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.verification import (
    CapabilityAcquisitionDevelopmentCompletionHandler,
)
from jarvis.capability_acquisition.workflow import (
    AcquisitionWorkContextResolver,
    acquisition_completion_guard,
    build_acquisition_protocol_executors,
)
from jarvis.capability_registry.admission import CapabilityPackageAdmissionService
from jarvis.capability_registry.lifecycle import CapabilityLifecycleService
from jarvis.capability_registry.reconciliation import CapabilityLifecycleReconciler
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_substrate.discovery import default_discovery_broker
from jarvis.engineering_change.store import ChangeStore
from jarvis.incident_repair.architecture import (
    IncidentRepairDevelopmentRevisionResolver,
    IncidentRepairSourceCompletionHandler,
)
from jarvis.incident_repair.code_index import (
    DiagnosticCodeIndex,
    build_diagnostic_code_intelligence_executors,
)
from jarvis.incident_repair.diagnostics import (
    DiagnosticContextResolver,
    build_diagnostic_protocol_executors,
)
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.incident_repair.reproduction import (
    DiagnosticRunReproductionExecutor,
    build_diagnostic_reproduction_runner,
)
from jarvis.incident_repair.static_analysis import (
    DiagnosticStaticCheckExecutor,
    build_diagnostic_static_runner,
)
from jarvis.incident_repair.verification import (
    IncidentRepairDevelopmentCompletionHandler,
)
from jarvis.incident_repair.workspace import (
    ChangeStoreDiagnosticRevisionResolver,
    DiagnosticWorkspaceManager,
    build_diagnostic_workspace_executors,
)
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
from jarvis.promotion.release import DeploymentMetadataStore
from jarvis.promotion.runtime_composition import (
    PromotionRuntime,
    PromotionRuntimeConfig,
)
from jarvis.promotion.store import PromotionStore
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
from jarvis.work.resources import ResourceLeaseManager, engineering_resource_capacities
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

LOGGER = logging.getLogger(__name__)


def _application_version() -> str:
    try:
        return version("jarvis")
    except PackageNotFoundError:
        return "0.1.0"


class _CompositeDevelopmentRevisionResolver:
    def __init__(self, *resolvers) -> None:
        self._resolvers = tuple(resolvers)

    def revision_for(self, work_id: str) -> str | None:
        revisions = tuple(
            revision
            for resolver in self._resolvers
            if (revision := resolver.revision_for(work_id)) is not None
        )
        if not revisions:
            return None
        if len(set(revisions)) != 1:
            raise RuntimeError("development revision resolvers disagree")
        return revisions[0]


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
        capability_acquisition: CapabilityAcquisitionCoordinator | None = None,
        capability_lifecycle: CapabilityAcquisitionLifecycleCoordinator | None = None,
        promotion_runtime: PromotionRuntime | None = None,
        release_bridge_task: asyncio.Task[None] | None = None,
        capability_catalog_refresher: Callable[[], object] | None = None,
        source_revision_provider: Callable[[], str] | None = None,
        autonomy_periodic_reconciler: object | None = None,
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
        self.capability_acquisition = capability_acquisition
        self.capability_lifecycle = capability_lifecycle
        self.promotion_runtime = promotion_runtime
        self._release_bridge_task = release_bridge_task
        self._capability_catalog_refresher = capability_catalog_refresher
        self._source_revision_provider = source_revision_provider
        if autonomy_periodic_reconciler is not None and (
            not callable(getattr(autonomy_periodic_reconciler, "start", None))
            or not callable(getattr(autonomy_periodic_reconciler, "stop", None))
        ):
            raise TypeError(
                "autonomy_periodic_reconciler must provide start() and stop()"
            )
        self._autonomy_periodic_reconciler = autonomy_periodic_reconciler
        self._closed = False

    @property
    def autonomy_reconciliation_attached(self) -> bool:
        return self._autonomy_periodic_reconciler is not None

    def start_autonomy_reconciliation(self) -> None:
        service = self._autonomy_periodic_reconciler
        if service is None:
            raise RuntimeError("autonomy reconciler is not attached")
        service.start()

    def stop_autonomy_reconciliation(self) -> None:
        service = self._autonomy_periodic_reconciler
        if service is not None:
            service.stop()

    def refresh_capability_catalog(self) -> None:
        refresher = getattr(self, "_capability_catalog_refresher", None)
        if refresher is not None:
            refresher()

    def current_source_revision(self) -> str:
        provider = self._source_revision_provider
        if provider is None:
            raise RuntimeError("trusted JARVIS source revision is unavailable")
        revision = str(provider()).strip().casefold()
        if len(revision) != 40 or any(
            char not in "0123456789abcdef" for char in revision
        ):
            raise RuntimeError("trusted JARVIS source revision is invalid")
        return revision

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
        autonomy = getattr(self, "_autonomy_periodic_reconciler", None)
        if autonomy is not None:
            autonomy.stop()
        task = getattr(self, "_release_bridge_task", None)
        if task is not None and not task.done():
            task.cancel()
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
    diagnostic_test_image: str | None = None,
    store_path: str | Path | None = None,
    dbos_database_url: str | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
    acquisition_context_provider: AcquisitionContextProvider | None = None,
    capability_lifecycle_service: CapabilityLifecycleService | None = None,
    capability_deployment_metadata: DeploymentMetadataStore | None = None,
    capability_package_admission: CapabilityPackageAdmissionService | None = None,
    capability_package_reconciler: CapabilityLifecycleReconciler | None = None,
    promotion_runtime_config: PromotionRuntimeConfig | None = None,
    capability_catalog_refresher: Callable[[], object] | None = None,
    autonomy_periodic_reconciler: object | None = None,
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
    change_store = ChangeStore(
        store,
        processes=(
            UNKNOWN_INCIDENT_REPAIR_PROCESS,
            OWNER_CAPABILITY_ACQUISITION_PROCESS,
        ),
    )
    acquisition_context = (
        acquisition_context_provider
        or StaticAcquisitionContextProvider(
            AcquisitionContextV1(
                catalog=CapabilityCatalog(sources=(), capabilities=()),
                inventory=(),
            )
        )
    )
    acquisition_sources = CapabilitySourceRegistry(
        (
            ExistingCapabilitySourceAdapter(),
            *registered_source_adapters(),
            CustomBuildCapabilitySourceAdapter(),
        )
    )
    acquisition_work_context = AcquisitionWorkContextResolver(change_store)
    acquisition_discovery = default_discovery_broker()

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
    workspace_manager = DevelopmentWorkspaceManager(
        base_revision_resolver=_CompositeDevelopmentRevisionResolver(
            IncidentRepairDevelopmentRevisionResolver(change_store),
            CapabilityAcquisitionDevelopmentRevisionResolver(change_store),
        )
    )
    diagnostic_workspace_manager = DiagnosticWorkspaceManager(
        ChangeStoreDiagnosticRevisionResolver(change_store)
    )
    diagnostic_code_index = DiagnosticCodeIndex(diagnostic_workspace_manager)
    diagnostic_context = DiagnosticContextResolver(change_store)
    diagnostic_image = diagnostic_test_image or development_test_image
    diagnostic_reproduction_runner = build_diagnostic_reproduction_runner(
        diagnostic_image
    )
    diagnostic_static_runner = build_diagnostic_static_runner(
        diagnostic_image,
        protected_main_root=diagnostic_workspace_manager.repository_root,
    )
    executors = (
        ResearchWorkExecutor(research_service),
        *build_acquisition_discovery_executors(
            acquisition_work_context,
            broker=acquisition_discovery,
        ),
        *build_acquisition_protocol_executors(
            acquisition_work_context,
            context_provider=acquisition_context,
            sources=acquisition_sources,
        ),
        *build_diagnostic_workspace_executors(diagnostic_workspace_manager),
        *build_diagnostic_code_intelligence_executors(diagnostic_code_index),
        *build_diagnostic_protocol_executors(diagnostic_context),
        DiagnosticRunReproductionExecutor(
            diagnostic_workspace_manager,
            diagnostic_reproduction_runner,
        ),
        DiagnosticStaticCheckExecutor(
            diagnostic_workspace_manager,
            diagnostic_static_runner,
        ),
        *build_development_executors(
            workspace_manager,
            test_runner=build_development_test_runner(development_test_image),
        ),
    )
    actions = WorkActionRegistry(tuple(executors))
    resource_capacities = {
        "work": max(1, global_concurrency),
        "cpu": max(1, min(2, global_concurrency)),
        "git": 1,
        "network": max(1, global_concurrency),
        "local_discovery": 1,
        "gpu": 1,
        "browser": 1,
        "desktop": 1,
        "provider_api": 1,
        **engineering_resource_capacities(),
    }
    resources = ResourceLeaseManager(
        resource_capacities,
        min_available_memory_mb=min_available_memory_mb,
    )

    def _completion_guard(work: WorkItem, steps):
        stage = change_store.stage_for_work(work.work_id)
        if stage is None:
            return None
        change = change_store.require(stage.change_id)
        if (
            change.process_key == OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            and change.process_version == OWNER_CAPABILITY_ACQUISITION_PROCESS.version
            and stage.stage_key
            == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
        ):
            return acquisition_completion_guard(steps)
        return None

    engine = WorkEngine(
        store=store,
        brain=brain,
        actions=actions,
        resources=resources,
        base_resource_keys=("work",),
        action_admission=change_store.work_admitted,
        completion_guard=_completion_guard,
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
    changes = ChangeCoordinator(
        change_store,
        backend,
        source_completion_handlers=(
            IncidentRepairSourceCompletionHandler(change_store),
            CapabilityAcquisitionSourceCompletionHandler(change_store),
        ),
        development_completion_handlers=(
            IncidentRepairDevelopmentCompletionHandler(
                change_store,
                workspace_manager,
            ),
            CapabilityAcquisitionDevelopmentCompletionHandler(
                change_store,
                workspace_manager,
            ),
        ),
    )
    capability_acquisition = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=acquisition_context,
    )
    if (
        capability_lifecycle_service is not None
        and capability_deployment_metadata is None
    ):
        raise ValueError(
            "capability lifecycle service requires canonical deployment metadata"
        )
    capability_lifecycle = (
        None
        if capability_lifecycle_service is None
        else CapabilityAcquisitionLifecycleCoordinator(
            change_store,
            capability_deployment_metadata,
            capability_lifecycle_service,
        )
    )
    promotion_runtime = None
    if promotion_runtime_config is not None:
        if capability_deployment_metadata is None:
            raise ValueError("live promotion requires canonical deployment metadata")
        promotion_runtime = PromotionRuntime(
            change_store,
            workspace_manager,
            capability_deployment_metadata,
            promotion_runtime_config,
        )

    release_bridge_task = None
    if (
        capability_package_admission is not None
        or capability_package_reconciler is not None
    ):
        if (
            capability_package_admission is None
            or capability_package_reconciler is None
            or capability_deployment_metadata is None
        ):
            raise ValueError(
                "Phase-9 release bridge requires admission, reconciler and deployment metadata"
            )
        bridge = CapabilityAcquisitionReleaseBridge(
            change_store,
            PromotionStore(change_store),
            capability_deployment_metadata,
            admission=capability_package_admission,
            reconciler=capability_package_reconciler,
        )

        async def reconcile_release_bridge() -> None:
            last_success: tuple[str, str] | None = None
            while True:
                try:
                    active = capability_deployment_metadata.active()
                    if active is not None:
                        key = (active.release_sha, active.promotion_attempt_id)
                        if key != last_success:
                            attempt = PromotionStore(change_store).get(
                                active.promotion_attempt_id
                            )
                            if attempt is not None:
                                change = change_store.require(attempt.change_id)
                                if (
                                    change.process_key
                                    == OWNER_CAPABILITY_ACQUISITION_PROCESS.key
                                ):
                                    await asyncio.to_thread(
                                        bridge.reconcile,
                                        change.change_id,
                                        attempt_id=attempt.attempt_id,
                                    )
                                    last_success = key
                                    LOGGER.info(
                                        "Phase-9 active release bridge reconciled: "
                                        "change=%s release=%s",
                                        change.change_id,
                                        active.release_sha,
                                    )
                except CapabilityAcquisitionReleaseBridgeError as exc:
                    # DEPLOYING -> OBSERVING is parent-owned. Retry the same exact
                    # release after the supervisor commits the durable transition.
                    LOGGER.debug(
                        "Phase-9 release bridge not ready yet: %s",
                        exc.reason_code,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Phase-9 release bridge reconciliation failed")
                await asyncio.sleep(1.0)

        release_bridge_task = loop.create_task(reconcile_release_bridge())

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
        capability_acquisition=capability_acquisition,
        capability_lifecycle=capability_lifecycle,
        promotion_runtime=promotion_runtime,
        release_bridge_task=release_bridge_task,
        capability_catalog_refresher=capability_catalog_refresher,
        source_revision_provider=workspace_manager.current_revision,
        autonomy_periodic_reconciler=autonomy_periodic_reconciler,
    )
