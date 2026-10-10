"""Composition root for persistent concurrent JARVIS work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from jarvis.ai_provider import provider_api_key
from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)
from jarvis.brain_routing.deterministic import default_work_deterministic_resolvers
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.brain_routing.work import GlobalBrainRouterReasoner
from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.activation import (
    CapabilityAcquisitionLifecycleCoordinator,
)
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
    migrate_legacy_gicc_external_acceptance_contracts,
)
from jarvis.capability_acquisition.discovery_workflow import (
    build_acquisition_discovery_executors,
)
from jarvis.capability_acquisition.external_acceptance import (
    ExternalAcceptanceCoordinator,
    build_external_acceptance_executors,
    external_acceptance_completion_guard,
)
from jarvis.capability_acquisition.owner_sources import registered_source_adapters
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.promotion import (
    CapabilityAcquisitionReleaseBridge,
    CapabilityAcquisitionReleaseBridgeError,
)
from jarvis.capability_acquisition.resolver import AcquisitionCandidateAdvisor
from jarvis.capability_acquisition.runtime_context import (
    AcquisitionContextProvider,
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.sdk_verification import (
    build_acquisition_sdk_verification_executors,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.substrate_workflow import (
    build_capability_substrate_executors,
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
from jarvis.chatgpt_plan import (
    CHATGPT_PLAN_PROVIDER_ID,
    ChatGPTPlanSessionManager,
)
from jarvis.development_engine.codex import CodexPlanDevelopmentEngine
from jarvis.development_engine.coordinator import DevelopmentEngineCoordinator
from jarvis.development_engine.phase9 import (
    Phase9DevelopmentControlPlaneDecider,
    Phase9DevelopmentEngineExecutor,
    Phase9DevelopmentTicketBuilder,
    Phase9ResearchControlPlaneDecider,
    Phase9ResearchEvidenceExecutor,
    handle_phase9_model_owner_request,
    phase9_development_completion_guard,
)
from jarvis.development_engine.session_store import DevelopmentSessionStore
from jarvis.engineering_change import (
    SystemOutcomeKind,
    classify_work_system_outcome,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.change_integration import (
    EngineeringSubstrateChangeService,
)
from jarvis.engineering_substrate.dependency.runtime import (
    build_runtime_dependency_broker,
)
from jarvis.engineering_substrate.discovery import default_discovery_broker
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
from jarvis.model_routing.cost import ProviderCostEventStore
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
from jarvis.provider_circuit import (
    BackgroundProviderCircuitRegistry,
    provider_circuit_key,
)
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
from jarvis.work.estimates import estimate_work
from jarvis.work.models import WorkDeliveryKind, WorkItem, WorkState, WorkType
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.prompt_compression import LLMLingua2WorkPayloadCompressor
from jarvis.work.reasoner import RoutedWorkReasoner
from jarvis.work.resources import ResourceLeaseManager, engineering_resource_capacities
from jarvis.work.store import SQLiteWorkStore, WorkStoreError, default_work_store_path

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
        brain_route_store: BrainRouteStore | None = None,
        capability_acquisition: CapabilityAcquisitionCoordinator | None = None,
        capability_lifecycle: CapabilityAcquisitionLifecycleCoordinator | None = None,
        capability_external_acceptance: ExternalAcceptanceCoordinator | None = None,
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
        self.brain_route_store = brain_route_store
        self.capability_acquisition = capability_acquisition
        self.capability_lifecycle = capability_lifecycle
        self.capability_external_acceptance = capability_external_acceptance
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
        self._status_update_task: asyncio.Task[None] | None = None
        self._owner_work_focus_id: str | None = None
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

    @property
    def owner_work_focus_id(self) -> str | None:
        """Return the latest canonical WorkItem explicitly surfaced to the owner."""

        return getattr(self, "_owner_work_focus_id", None)

    def set_owner_work_focus(self, work_id: str | None) -> None:
        """Keep a volatile owner task focus across wake sessions.

        The focus is intentionally runtime-local rather than persisted. A JARVIS
        restart clears it, avoiding stale cross-process references.
        """

        normalized = str(work_id or "").strip()
        if not normalized:
            self._owner_work_focus_id = None
            return
        self.store.require(normalized)
        self._owner_work_focus_id = normalized

    def focused_work(self) -> WorkItem | None:
        work_id = self.owner_work_focus_id
        if work_id is None:
            return None
        try:
            return self.store.require(work_id)
        except WorkStoreError:
            self._owner_work_focus_id = None
            return None

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
        execution_id = self.store.get_execution_id(work.work_id) or work.work_id
        self.backend.send_owner_input(
            execution_id,
            response,
            idempotency_key=f"owner-input:{work.version}",
        )
        return work

    def resolve_retryable_work(self, work_id: str | None = None) -> WorkItem:
        normalized = str(work_id or "").strip()
        if normalized:
            work = self.store.require(normalized)
            if work.state is not WorkState.FAILED:
                raise ValueError("work is not failed and cannot be retried")
            return work

        focused = self.focused_work()
        if focused is not None:
            if focused.state is not WorkState.FAILED:
                raise ValueError(
                    "owner-focused background work is not failed and cannot be retried"
                )
            return focused

        failed = self.store.list(states=(WorkState.FAILED,), limit=10)
        if len(failed) == 1:
            return failed[0]
        if not failed:
            raise ValueError("no failed background work is available to retry")
        raise ValueError(
            "multiple failed background tasks exist; identify the task before retrying"
        )

    def retry_failed_work(
        self,
        work_id: str | None,
        *,
        owner_request: str,
        source_session_id: str,
        source_turn_id: str,
    ) -> WorkItem:
        work = self.resolve_retryable_work(work_id)
        reopened_change = (
            None
            if self.changes is None
            else self.changes.prepare_failed_work_retry(work.work_id)
        )
        try:
            return self.orchestrator.retry_failed(
                work.work_id,
                owner_request=owner_request,
                source_session_id=source_session_id,
                source_turn_id=source_turn_id,
            )
        except Exception:
            if self.changes is not None:
                try:
                    self.changes.reconcile_for_work(work.work_id)
                except Exception:
                    LOGGER.exception(
                        "Failed to reconcile EngineeringChange after Work retry "
                        "submission failure | work_id=%s | change_id=%s",
                        work.work_id,
                        (
                            reopened_change.change_id
                            if reopened_change is not None
                            else "unknown"
                        ),
                    )
            raise

    def retry_failed_work_from_supervisor(
        self,
        work_id: str,
        *,
        reason: str,
    ) -> WorkItem:
        """Retry only canonical failures already classified retryable by JARVIS."""

        work = self.store.require(str(work_id).strip())
        if work.state is not WorkState.FAILED:
            raise ValueError("Supervisor retry requires a failed WorkItem")
        outcome = classify_work_system_outcome(
            work,
            steps=self.store.list_steps(work.work_id),
        )
        if outcome.kind is not SystemOutcomeKind.RETRYABLE:
            raise ValueError(
                "Supervisor retry is allowed only for deterministic retryable outcomes"
            )
        if self.changes is None:
            raise RuntimeError("Supervisor retry requires EngineeringChange runtime")

        reopened_change = self.changes.prepare_failed_work_retry(work.work_id)
        try:
            return self.orchestrator.retry_failed_system(
                work.work_id,
                reason=reason,
                source="global_supervisor",
            )
        except Exception:
            try:
                self.changes.reconcile_for_work(work.work_id)
            except Exception:
                LOGGER.exception(
                    "Failed to reconcile EngineeringChange after Supervisor retry "
                    "submission failure | work_id=%s | change_id=%s",
                    work.work_id,
                    (
                        reopened_change.change_id
                        if reopened_change is not None
                        else "unknown"
                    ),
                )
            raise

    def resolve_status_target(self, work_id: str | None = None) -> WorkItem:
        normalized = str(work_id or "").strip()
        if normalized:
            return self.store.require(normalized)
        active = self.orchestrator.list_active(limit=10)
        if len(active) == 1:
            return active[0]
        if not active:
            raise ValueError("no active background work is available")
        raise ValueError(
            "multiple background tasks are active; identify the task for scheduled updates"
        )

    def configure_status_updates(
        self,
        work_id: str | None,
        *,
        interval_minutes: int,
    ) -> WorkItem:
        work = self.resolve_status_target(work_id)
        if work.state.terminal:
            raise ValueError("terminal work does not need scheduled progress updates")
        if isinstance(interval_minutes, bool) or interval_minutes < 0:
            raise ValueError(
                "update interval must be zero or a positive number of minutes"
            )
        if interval_minutes == 0:
            self.store.clear_status_update_interval(work.work_id)
            return work
        if interval_minutes > 24 * 60:
            raise ValueError("update interval cannot exceed 1440 minutes")
        self.store.set_status_update_interval(
            work.work_id,
            interval_seconds=int(interval_minutes) * 60,
        )
        return work

    def _process_due_status_updates(self) -> None:
        """Run durable progress-status database work off the realtime loop."""

        due = self.store.list_due_status_updates(limit=20)
        for work_id, interval_seconds, due_at in due:
            work = self.store.require(work_id)
            if work.state.terminal:
                self.store.clear_status_update_interval(work_id)
                continue
            estimate = estimate_work(self.store, work)
            parts = [
                f"Background task update: approximately {estimate.progress_percent}% complete."
            ]
            if work.status_detail:
                parts.append(f"Current status: {work.status_detail}.")
            if estimate.blocked_reason:
                parts.append(f"Blocker: {estimate.blocked_reason}.")
            if estimate.remaining_work:
                parts.append(
                    "Remaining work: " + ", ".join(estimate.remaining_work[:3]) + "."
                )
            event_key = f"progress:{int(due_at.timestamp())}"
            intent = OwnerCommunicationIntentV1.create(
                kind=OwnerCommunicationKind.PROGRESS,
                event_key=event_key,
                summary=" ".join(parts),
                work_id=work.work_id,
                system_outcome_kind=work.state.value,
                technical_detail=work.status_detail,
            )
            owner_message = SupervisorOwnerCommunication.compile(intent)
            if owner_message is not None:
                self.store.enqueue_delivery(
                    work=work,
                    kind=WorkDeliveryKind.PROGRESS,
                    message=owner_message.message,
                    event_key=owner_message.event_key,
                )
            self.store.advance_status_update_interval(
                work_id,
                interval_seconds=interval_seconds,
            )

    async def _status_update_loop(self) -> None:
        while not self._closed:
            try:
                # The DBOS/SQLite lock may wait; never stall LiveKit audio.
                await asyncio.to_thread(self._process_due_status_updates)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Scheduled background-work status update failed")
            await asyncio.sleep(1.0)

    def start_status_updates(
        self,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        if self._status_update_task is not None and not self._status_update_task.done():
            return
        loop = event_loop or asyncio.get_running_loop()
        self._status_update_task = loop.create_task(
            self._status_update_loop(),
            name="jarvis-work-status-updates",
        )

    async def aclose(self) -> None:
        """Gracefully park durable work before tearing down DBOS.

        DBOS destroy does not interrupt workflows that outlive its completion
        timeout. Because DBOS steps call back onto JARVIS's asyncio loop, running
        destroy synchronously on that same loop prevents those steps from reaching
        a checkpoint. Shutdown therefore preempts provider reasoning, stops local
        schedulers, durably parks exact DBOS executions, and performs the blocking
        DBOS drain on a worker thread while the canonical event loop remains alive.
        """

        if self._closed:
            return
        self._closed = True

        begin_shutdown = getattr(self.backend, "begin_shutdown", None)
        if callable(begin_shutdown):
            begin_shutdown()

        shutdown_preempt = getattr(
            self._interactive_brain_gate,
            "preempt_background_for_shutdown",
            None,
        )
        if callable(shutdown_preempt):
            shutdown_preempt()
        else:
            self._interactive_brain_gate.set_interactive_active(True)

        status_task = getattr(self, "_status_update_task", None)
        if status_task is not None and not status_task.done():
            status_task.cancel()

        autonomy = getattr(self, "_autonomy_periodic_reconciler", None)
        if autonomy is not None:
            autonomy.stop()

        release_task = getattr(self, "_release_bridge_task", None)
        if release_task is not None and not release_task.done():
            release_task.cancel()

        pending_tasks = tuple(
            task
            for task in (status_task, release_task)
            if task is not None and not task.done()
        )
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # Let the provider cancellation scheduled by the interactive-brain gate
        # run before DBOS begins waiting for active workflow steps to checkpoint.
        await asyncio.sleep(0)

        execution_ids = tuple(
            sorted(
                {
                    self.store.get_execution_id(work.work_id) or work.work_id
                    for work in self.orchestrator.list_active(limit=10_000)
                    if work.work_type is not WorkType.MONITORING
                }
            )
        )
        park_for_shutdown = getattr(self.backend, "park_for_shutdown", None)
        if execution_ids and callable(park_for_shutdown):
            parked = await asyncio.to_thread(
                park_for_shutdown,
                execution_ids,
            )
            LOGGER.info(
                "Durably parked active DBOS executions for shutdown: %s",
                ", ".join(parked),
            )

        # DBOS cancellation prevents another durable step from starting, while
        # InteractiveBrainGate separately preempts provider reasoning. Do not
        # cancel an already-admitted action: it may have produced an external
        # side effect that still needs its canonical JARVIS evidence checkpoint.
        quiesce_advances = getattr(self.backend, "quiesce_active_advances", None)
        if callable(quiesce_advances):
            quiesced = await quiesce_advances()
            if quiesced:
                LOGGER.info(
                    "Quiesced active JARVIS engine advances before DBOS shutdown: %s",
                    quiesced,
                )

        # Keep the canonical event loop free while DBOS drains. New
        # WAITING_RESOURCE history uses wakeable DBOS.recv timeouts that preserve
        # absolute durable timing. The longer bound only exists for one legacy
        # single DBOS.sleep (historically capped at 60s); PAUSED recv calls are
        # explicitly woken by park_for_shutdown().
        await asyncio.to_thread(
            shutdown_dbos_work_runtime,
            workflow_completion_timeout_sec=70,
        )

    def close(self) -> None:
        """Synchronous compatibility wrapper for non-async callers only."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.aclose())
            return
        raise RuntimeError(
            "WorkRuntime.close() cannot block an active event loop; "
            "use 'await WorkRuntime.aclose()'"
        )


def build_work_runtime(
    *,
    provider: str,
    research_service: CurrentResearchService,
    model: str | None = None,
    chatgpt_plan_enabled: bool = False,
    chatgpt_plan_model: str | None = None,
    development_engine_enabled: bool = False,
    development_engine_model: str | None = None,
    paid_fallback_enabled: bool = False,
    provider_circuit_registry: BackgroundProviderCircuitRegistry | None = None,
    work_context_mode: str = "shadow",
    work_prompt_compression_mode: str = "off",
    work_prompt_compression_rate: float = 0.8,
    global_brain_router_mode: str = "shadow",
    global_concurrency: int = 4,
    max_reasoning_cycles: int = 64,
    min_available_memory_mb: int = 768,
    development_test_image: str | None = None,
    diagnostic_test_image: str | None = None,
    store_path: str | Path | None = None,
    dbos_database_url: str | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
    acquisition_context_provider: AcquisitionContextProvider | None = None,
    capability_runtime: CapabilityRuntime | None = None,
    capability_lifecycle_service: CapabilityLifecycleService | None = None,
    capability_deployment_metadata: DeploymentMetadataStore | None = None,
    capability_package_admission: CapabilityPackageAdmissionService | None = None,
    capability_package_reconciler: CapabilityLifecycleReconciler | None = None,
    promotion_runtime_config: PromotionRuntimeConfig | None = None,
    capability_catalog_refresher: Callable[[], object] | None = None,
    autonomy_periodic_reconciler: object | None = None,
    acquisition_candidate_advisor: AcquisitionCandidateAdvisor | None = None,
) -> WorkRuntime:
    """Build one durable work runtime around the configured JARVIS brain provider."""

    if capability_lifecycle_service is not None and capability_runtime is None:
        raise ValueError(
            "capability lifecycle service requires governed capability runtime "
            "for Phase-9 external acceptance"
        )

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

    chatgpt_plan_session = ChatGPTPlanSessionManager() if chatgpt_plan_enabled else None
    adapter_registry = build_default_model_adapter_registry(
        chatgpt_plan_session_manager=chatgpt_plan_session,
    )
    chatgpt_plan_available_models: tuple[str, ...] = ()
    if chatgpt_plan_session is not None and chatgpt_plan_session.is_connected():
        try:
            chatgpt_plan_available_models = tuple(
                item.slug for item in chatgpt_plan_session.list_models()
            )
        except Exception as exc:  # noqa: BLE001 - catalog failure keeps legacy route
            LOGGER.warning(
                "ChatGPT-plan model catalog unavailable; using configured single "
                "model routing: %s",
                type(exc).__name__,
            )
    work_targets = build_default_work_targets(
        configured_provider=provider,
        configured_model=model,
        adapter_registry=adapter_registry,
        chatgpt_plan_enabled=chatgpt_plan_enabled,
        chatgpt_plan_model=chatgpt_plan_model,
        chatgpt_plan_available_models=chatgpt_plan_available_models,
        paid_fallback_enabled=paid_fallback_enabled,
    )
    provider_circuits = provider_circuit_registry or BackgroundProviderCircuitRegistry()
    routing_store = ModelRoutingStore(store)
    brain_route_store = BrainRouteStore(store)
    provider_cost_store = ProviderCostEventStore(store)
    strategy_registry = RoutingStrategyRegistry((EngineeringStageStrategy(),))

    resource_capacities = {
        "work": max(1, global_concurrency),
        "cpu": max(1, min(2, global_concurrency)),
        "git": 1,
        "network": max(1, global_concurrency),
        "gpu": 1,
        "browser": 1,
        "desktop": 1,
        "provider_api": 1,
        "prompt_compression": 1,
        "development_intelligence": 1,
        **engineering_resource_capacities(),
    }
    resources = ResourceLeaseManager(
        resource_capacities,
        min_available_memory_mb=min_available_memory_mb,
    )

    def _credential_available(target) -> bool:
        if target.provider_id == CHATGPT_PLAN_PROVIDER_ID:
            return bool(
                chatgpt_plan_session is not None and chatgpt_plan_session.is_connected()
            )
        try:
            return provider_api_key(target.provider_id) is not None
        except (KeyError, TypeError, ValueError):
            return False

    model_router = ModelRouter(
        target_registry=work_targets.registry,
        adapter_registry=adapter_registry,
        strategy_registry=strategy_registry,
        routing_store=routing_store,
        eligibility_policy=EligibilityPolicy(),
        credential_available=_credential_available,
    )
    compression_mode = str(work_prompt_compression_mode).strip().casefold()
    prompt_compressor = (
        None
        if compression_mode == "off"
        else LLMLingua2WorkPayloadCompressor(
            rate=float(work_prompt_compression_rate),
        )
    )
    model_reasoner = RoutedWorkReasoner(
        router=model_router,
        invoker=ModelInvoker(adapter_registry),
        primary_target_id=work_targets.primary_target_id,
        provider_circuit_registry=provider_circuits,
        resources=resources,
        resource_keys=("provider_api",),
        prompt_compressor=prompt_compressor,
        prompt_compression_mode=compression_mode,
        prompt_compression_work_types=frozenset({WorkType.RESEARCH}),
        prompt_compression_resource_keys=("cpu", "prompt_compression"),
    )
    reasoner = GlobalBrainRouterReasoner(
        model_reasoner,
        work_store=store,
        route_store=brain_route_store,
        model_routing_store=routing_store,
        resolvers=default_work_deterministic_resolvers(),
        mode=global_brain_router_mode,
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
    phase9_ticket_builder = Phase9DevelopmentTicketBuilder(change_store)
    executors = (
        ResearchWorkExecutor(
            research_service,
            cost_store=provider_cost_store,
        ),
        *build_acquisition_discovery_executors(
            acquisition_work_context,
            broker=acquisition_discovery,
        ),
        *build_acquisition_sdk_verification_executors(
            acquisition_work_context,
            broker_factory=lambda: build_runtime_dependency_broker(
                protected_main_root=workspace_manager.repository_root,
            ),
        ),
        *build_acquisition_protocol_executors(
            acquisition_work_context,
            context_provider=acquisition_context,
            sources=acquisition_sources,
            advisor=acquisition_candidate_advisor,
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
        *build_capability_substrate_executors(
            change_store,
            broker_factory=lambda: build_runtime_dependency_broker(
                protected_main_root=workspace_manager.repository_root,
            ),
        ),
        Phase9ResearchEvidenceExecutor(change_store, phase9_ticket_builder),
        *(
            ()
            if capability_runtime is None
            else build_external_acceptance_executors(
                change_store,
                capability_runtime=capability_runtime,
            )
        ),
        *build_development_executors(
            workspace_manager,
            test_runner=build_development_test_runner(development_test_image),
        ),
    )
    base_actions = WorkActionRegistry(tuple(executors))

    control_plane_decider = None
    if development_engine_enabled:
        if not chatgpt_plan_enabled or chatgpt_plan_session is None:
            raise ValueError(
                "DevelopmentEngine requires Sign in with ChatGPT to be enabled"
            )
        development_model = str(development_engine_model or "").strip()
        if not development_model:
            capable_plan_targets = tuple(
                target
                for target in work_targets.registry.for_role("capable")
                if target.provider_id == CHATGPT_PLAN_PROVIDER_ID
            )
            if capable_plan_targets:
                development_model = capable_plan_targets[0].model_id
            else:
                primary_target = work_targets.registry.require(
                    work_targets.primary_target_id
                )
                if primary_target.provider_id == CHATGPT_PLAN_PROVIDER_ID:
                    development_model = primary_target.model_id
                else:
                    development_model = str(chatgpt_plan_model or "").strip()
        if not development_model:
            raise ValueError(
                "DevelopmentEngine requires an available ChatGPT-plan coding model"
            )
        development_sessions = DevelopmentSessionStore(store)
        development_specialist = CodexPlanDevelopmentEngine(
            chatgpt_plan=chatgpt_plan_session,
            model=development_model,
            sessions=development_sessions,
            provider_circuit=provider_circuits.circuit(
                provider_circuit_key(
                    provider=CHATGPT_PLAN_PROVIDER_ID,
                    model=development_model,
                )
            ),
        )
        development_coordinator = DevelopmentEngineCoordinator(
            engine=development_specialist,
            sessions=development_sessions,
            resources=resources,
            resource_keys=("development_intelligence", "provider_api"),
        )
        phase9_engine_executor = Phase9DevelopmentEngineExecutor(
            builder=phase9_ticket_builder,
            coordinator=development_coordinator,
            actions=base_actions,
            resources=resources,
            change_store=change_store,
        )
        actions = WorkActionRegistry((*executors, phase9_engine_executor))
        phase9_research_decider = Phase9ResearchControlPlaneDecider(
            phase9_ticket_builder
        )
        phase9_development_decider = Phase9DevelopmentControlPlaneDecider(
            phase9_ticket_builder
        )

        def control_plane_decider(work, available_actions, steps):
            research = phase9_research_decider(work, available_actions, steps)
            if research is not None:
                return research
            return phase9_development_decider(work, available_actions, steps)
    else:
        actions = base_actions

    def _completion_guard(work: WorkItem, steps):
        if work.work_type is WorkType.EXTERNAL_ACCEPTANCE:
            return external_acceptance_completion_guard(steps)
        development_engine_guard = phase9_development_completion_guard(
            change_store,
            work,
            steps,
        )
        if development_engine_guard is not None:
            return development_engine_guard
        stage = change_store.stage_for_work(work.work_id)
        if stage is None:
            return None
        change = change_store.require(stage.change_id)
        if (
            change.process_key == OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            and change.process_version == OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            if (
                stage.stage_key
                == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
            ):
                return acquisition_completion_guard(steps)
            if (
                stage.stage_key
                == OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
            ):
                architecture = change_store.latest_artifact(
                    change.change_id,
                    "architecture",
                )
                if (
                    architecture is not None
                    and any(
                        tuple(architecture.payload.get(field, ()))
                        for field in (
                            "dependency_refs",
                            "secret_scopes",
                            "discovery_scopes",
                        )
                    )
                    and not EngineeringSubstrateChangeService(
                        change_store
                    ).verification_current(change.change_id)
                ):
                    return (
                        False,
                        (
                            "capability development requires current Phase-5 "
                            "substrate verification"
                        ),
                    )
        return None

    engine = WorkEngine(
        store=store,
        brain=brain,
        actions=actions,
        resources=resources,
        base_resource_keys=("work",),
        action_admission=change_store.work_admitted,
        completion_guard=_completion_guard,
        model_owner_request_handler=lambda work, question: (
            handle_phase9_model_owner_request(
                change_store,
                work,
                question,
            )
        ),
        control_plane_decider=control_plane_decider,
        context_mode=work_context_mode,
    )
    engine.reconcile_interrupted_steps()
    reconciled_model_owner = engine.reconcile_waiting_model_owner_requests()
    if reconciled_model_owner:
        LOGGER.info(
            "Migrated stale Phase-9 model owner waits into governed research: %s",
            ", ".join(reconciled_model_owner),
        )
    reconciled_owner_deliveries = engine.reconcile_waiting_owner_deliveries()
    if reconciled_owner_deliveries:
        LOGGER.info(
            "Reopened stale owner-input deliveries for waiting WorkItems: %s",
            ", ".join(reconciled_owner_deliveries),
        )
    backend = initialize_dbos_work_runtime(
        engine=engine,
        event_loop=loop,
        application_version=_application_version(),
        queue_concurrency=None,
        system_database_url=dbos_database_url,
        max_reasoning_cycles=max_reasoning_cycles,
    )
    orchestrator = WorkOrchestrator(store, backend)
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

    def _reconcile_terminal_change(work_id: str) -> None:
        changes.reconcile_for_work(work_id)
        reconcile_owner_change_gates(changes)

    # DBOS may recover an existing workflow as soon as it launches. Install the
    # EngineeringChange terminal bridge immediately after its coordinator exists,
    # then repair any parent/child drift that occurred in the startup window before
    # running compatibility migrations.
    configure_terminal_reconciliation(_reconcile_terminal_change)
    changes.reconcile_active()

    recovered_revision_research = (
        change_store.reopen_recoverable_architecture_revision_failures(
            recovery_generation="phase9-research-provider-sdk-v1",
        )
    )
    for change_id in recovered_revision_research:
        changes.reconcile(change_id)
    if recovered_revision_research:
        LOGGER.warning(
            "Recovered compatible architecture-revision research failure(s) with "
            "fresh source attempts: %s",
            ", ".join(recovered_revision_research),
        )

    recovered_provisional_resolution = (
        change_store.reopen_recoverable_provisional_candidate_resolution_failures(
            recovery_generation="phase9-provisional-candidate-resolution-v1",
        )
    )
    for change_id in recovered_provisional_resolution:
        changes.reconcile(change_id)
    if recovered_provisional_resolution:
        LOGGER.warning(
            "Recovered provisional acquisition candidate collision(s) with fresh "
            "source attempts: %s",
            ", ".join(recovered_provisional_resolution),
        )

    recovered_development = change_store.reopen_recoverable_development_engine_failures(
        recovery_generation="codex-contract-repair-v1",
    )
    for change_id in recovered_development:
        changes.reconcile(change_id)
    if recovered_development:
        LOGGER.warning(
            "Recovered compatible DevelopmentEngine failure(s) under their existing "
            "approved architecture: %s",
            ", ".join(recovered_development),
        )

    recovered_dependencies = (
        change_store.reopen_recoverable_superseded_dependency_failures(
            recovery_generation="phase9-authoritative-source-dependency-v1",
        )
    )
    for change_id in recovered_dependencies:
        changes.reconcile(change_id)
    if recovered_dependencies:
        LOGGER.warning(
            "Recovered development attempt(s) poisoned by superseded architecture-"
            "source dependencies: %s",
            ", ".join(recovered_dependencies),
        )

    migrated_acceptance_contracts = migrate_legacy_gicc_external_acceptance_contracts(
        change_store,
    )
    if migrated_acceptance_contracts:
        surfaced = reconcile_owner_change_gates(
            changes,
            change_ids=migrated_acceptance_contracts,
        )
        LOGGER.warning(
            "Migrated legacy GICC capability architecture(s) to the mandatory "
            "real-target acceptance contract; fresh owner architecture approval is "
            "required: changes=%s gates=%s",
            ", ".join(migrated_acceptance_contracts),
            ", ".join(surfaced),
        )

    capability_acquisition = CapabilityAcquisitionCoordinator(
        changes=changes,
        context_provider=acquisition_context,
    )
    capability_external_acceptance = (
        None
        if capability_runtime is None
        else ExternalAcceptanceCoordinator(change_store, backend)
    )
    if capability_external_acceptance is not None:
        recovered_acceptance_work = (
            capability_external_acceptance.reconcile_current_activations()
        )
        if recovered_acceptance_work:
            LOGGER.warning(
                "Reconciled current post-activation external acceptance mission(s): %s",
                ", ".join(recovered_acceptance_work),
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

    # Resume/repair ordinary active Work only after terminal parent reconciliation
    # and compatibility recovery are in place.
    orchestrator.reconcile_active()
    changes.reconcile_active()
    surfaced_change_gates = reconcile_owner_change_gates(changes)
    if surfaced_change_gates:
        LOGGER.info(
            "Owner approval gates surfaced automatically: %s",
            ", ".join(surfaced_change_gates),
        )
    runtime = WorkRuntime(
        store=store,
        engine=engine,
        backend=backend,
        orchestrator=orchestrator,
        supported_work_types=actions.supported_work_types,
        interactive_brain_gate=interactive_brain_gate,
        changes=changes,
        routing_store=routing_store,
        model_router=model_router,
        brain_route_store=brain_route_store,
        capability_acquisition=capability_acquisition,
        capability_lifecycle=capability_lifecycle,
        capability_external_acceptance=capability_external_acceptance,
        promotion_runtime=promotion_runtime,
        release_bridge_task=release_bridge_task,
        capability_catalog_refresher=capability_catalog_refresher,
        source_revision_provider=workspace_manager.current_revision,
        autonomy_periodic_reconciler=autonomy_periodic_reconciler,
    )
    runtime.start_status_updates(loop)
    return runtime
