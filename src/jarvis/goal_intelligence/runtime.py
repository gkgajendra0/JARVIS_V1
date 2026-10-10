"""Development GICC APPLY composition over existing governed JARVIS subsystems."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, replace

from jarvis.authority.proposal import ActionProposal
from jarvis.autonomy.existing_objective import ExistingObjectiveResumeController
from jarvis.autonomy.mode import AutonomyMode
from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)
from jarvis.autonomy.supervisor_cutover import (
    SupervisorCutoverController,
    SupervisorCutoverDisposition,
)
from jarvis.capabilities.authority_bridge import (
    AuthorizedNetworkDiscovery,
    CapabilityAuthorizationError,
)
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.architecture import (
    migrate_legacy_gicc_external_acceptance_contracts,
)
from jarvis.capability_acquisition.hardening import (
    blocking_capability_workspace_invariant_codes,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.config import JarvisConfig
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.hands.provider_adapters import (
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.voice.generic_grounded_hands import GenericGroundedVoiceHandsOrchestrator
from jarvis.voice.hands_fast_path import FAST_PATH_OPERATIONS, execute_fast_hint
from jarvis.work.models import WorkDeliveryKind
from jarvis.work.runtime import WorkRuntime

from .aep_authority import AepAuthorityExecutionGuard
from .capability_graph import CapabilityGraphResolver
from .composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from .device_suggestions import (
    UnverifiedDeviceSuggestionV1,
    pending_owner_device_suggestions,
)
from .evaluation import ReplanController
from .execution import GoalPlanDispatcher, PlanDispatchDisposition
from .information import (
    InformationResolutionResult,
    InformationResolutionStrategy,
    InformationResolver,
    can_rediscover_information,
)
from .interpretation import GoalInterpreter, build_goal_interpreter
from .local_network import WindowsNeighborInformationProbe
from .models import (
    ContinuationBlockerType,
    ContinuationState,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
    WorldEntityRefV1,
)
from .monitoring import (
    DEFAULT_MONITOR_OBSERVATION_BUS,
    GICC_MONITOR_EVENT_CONTRACT,
    GoalMonitoringDispatcher,
    MonitorEventProcessor,
    MonitoringStrategy,
    MonitoringWorkCoordinator,
    MonitorObservationBus,
    VerifiedMonitorObservationV1,
)
from .network_consent import prepare_pending_device_discovery_consent
from .owner_device_confirmation import confirm_single_discovered_device
from .phase9 import Phase9GoalBridge, migrate_legacy_phase9_gap_links
from .planning import GoalPlanner
from .requirements import RequirementDeriver
from .service import GoalOrchestrator, SpecialistActionDispatch
from .status import OwnerObjectiveStatusResolver
from .store import GoalStore, GoalStoreConflict, build_default_goal_store
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink
from .windows_aep import ReviewedAepScopeV1, WindowsAepIdentityBackend
from .windows_lan_scope import WindowsLanScopePlanner
from .workspace import ObjectiveWorkspaceProjector
from .world import EntityResolver, WorldRegistry, canonical_world_entity_type
from .world_discovery import (
    EntityInformationProbe,
    ReviewedLocalServiceEntityDiscovery,
)

LOGGER = logging.getLogger(__name__)


class HandsPlanActionDispatcher:
    """Route only canonical Hands operations through the existing Hands specialist."""

    def __init__(self, runtime: CapabilityRuntime) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        self._runtime = runtime
        self._orchestrator = GenericGroundedVoiceHandsOrchestrator(
            runtime,
            runtime.hands_planner,
        )

    def handles(self, node: PlanNodeV1) -> bool:
        operation = str(node.operation or "").strip()
        if not operation or self._runtime.hands_registry.operation(operation) is None:
            return False
        return self._runtime.capability_for_operation(operation) == node.capability_key

    @staticmethod
    def _result_from_payload(
        node: PlanNodeV1,
        payload: dict[str, object],
        *,
        route: str,
    ) -> SpecialistActionDispatch:
        ok = payload.get("ok") is True
        reason_value = payload.get("reason") or payload.get("clarification_question")
        reason = None if ok else str(reason_value or "Hands goal execution failed")
        result = CapabilityResult(
            status=(CapabilityStatus.SUCCEEDED if ok else CapabilityStatus.FAILED),
            capability_key=str(node.capability_key or "hands"),
            operation=str(node.operation or "hands_goal"),
            data={
                "verification_passed": ok,
                "hands_goal_result": payload,
            },
            reason=reason,
            provenance=("JARVIS Hands", route),
        )
        return SpecialistActionDispatch(result=result, route=route)

    async def execute(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        node: PlanNodeV1,
    ) -> SpecialistActionDispatch:
        del plan
        operation = str(node.operation or "").strip()
        if not self.handles(node):
            raise ValueError("plan node is not owned by JARVIS Hands")

        if operation in FAST_PATH_OPERATIONS:
            fast = await execute_fast_hint(
                self._orchestrator,
                session_id=goal.source_session_id,
                goal=goal.exact_owner_request,
                recent_user_turns=(),
                operation_hint=operation,
                parameters=dict(node.parameters),
            )
            if fast is not None:
                return self._result_from_payload(
                    node,
                    fast,
                    route="hands_fast_path",
                )

        if self._runtime.hands_planner is None:
            return self._result_from_payload(
                node,
                {
                    "ok": False,
                    "status": "unavailable",
                    "reason": "JARVIS Hands semantic planner is not configured",
                },
                route="hands",
            )

        result = await self._orchestrator.execute_goal(
            session_id=goal.source_session_id,
            goal=goal.exact_owner_request,
            recent_user_turns=(),
        )
        return self._result_from_payload(node, result, route="hands")


@dataclass(slots=True)
class GiccApplyRuntime:
    store: GoalStore
    world: WorldRegistry
    coordinator: GoalIntelligenceCoordinator
    dispatcher: GoalPlanDispatcher
    telemetry: GiccTelemetrySink
    capability_runtime: CapabilityRuntime
    objective_status: OwnerObjectiveStatusResolver | None = None
    replan_controller: ReplanController | None = None
    change_store: ChangeStore | None = None
    monitor_processor: MonitorEventProcessor | None = None
    monitor_bus: MonitorObservationBus | None = None
    supervisor_cutover: SupervisorCutoverController | None = None
    existing_objective_resume: ExistingObjectiveResumeController | None = None
    reconcile_interval_seconds: float = 1.0
    information_recheck_interval_seconds: float = 120.0
    _information_last_recheck: dict[str, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _monitor_subscription_id: str | None = field(default=None, init=False, repr=False)
    _event_loop: asyncio.AbstractEventLoop | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _advance_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )

    def prepare_network_discovery_consent(
        self,
        *,
        goal_id: str,
        session_id: str,
        planner: WindowsLanScopePlanner | None = None,
    ) -> ActionProposal | None:
        """Suggest one reviewed owner approval, never initiate a scan.

        The caller must use existing AuthorityService for owner consent,
        audit and exactly-once action-permit execution. This cannot turn a
        network observation into a trusted device or a control permission.
        """

        return prepare_pending_device_discovery_consent(
            store=self.store,
            goal_id=goal_id,
            session_id=session_id,
            planner=planner,
        )

    def pending_network_device_suggestions(
        self,
        *,
        goal_id: str,
        session_id: str,
        now_epoch: int | None = None,
    ) -> tuple[UnverifiedDeviceSuggestionV1, ...]:
        """Read short-lived identity hints; never confirm or control a device."""

        return pending_owner_device_suggestions(
            store=self.store,
            goal_id=goal_id,
            session_id=session_id,
            now_epoch=now_epoch,
        )

    def apply_approved_network_discovery(
        self,
        *,
        goal_id: str,
        need_id: str,
        session_id: str,
        scope: ReviewedAepScopeV1,
        authority_guard: AepAuthorityExecutionGuard,
        planner: WindowsLanScopePlanner | None = None,
    ) -> InformationResolutionResult | None:
        """Execute one owner-authorized network observation for an existing goal.

        No new goal, approval, entity, architecture or control ability is
        created. The one-time permit is consumed by the AEP backend before
        any WinRT watcher starts. An unverified result remains evidence on
        the same canonical InformationNeed, enabling ordinary GICC recovery.
        """

        if not isinstance(scope, ReviewedAepScopeV1):
            raise TypeError("network discovery needs a reviewed AEP scope")
        if not isinstance(authority_guard, AepAuthorityExecutionGuard):
            raise TypeError("network discovery needs an Authority execution guard")
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        session = session_id.strip()
        goal = self.store.get_goal(goal_id)
        if (
            goal is None
            or goal.state is not GoalState.WAITING_INFORMATION
            or goal.source_session_id != session
            or authority_guard.session_id != session
            or not authority_guard.binds_information_need(
                goal_id=goal.goal_id, need_id=need_id
            )
            or not authority_guard.binds_scope(scope)
        ):
            return None
        need = self.store.get_information_need(need_id)
        if (
            need is None
            or need.goal_id != goal.goal_id
            or not can_rediscover_information(need)
            or need.answer_schema.get("type") != "entity_id"
            or not {
                "bounded_local_discovery",
                "current_state_observation",
            }.issubset(need.allowed_resolution_sources)
        ):
            return None

        kind = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        if kind not in {"media_player", "camera"}:
            return None
        local_planner = planner or WindowsLanScopePlanner()
        # Windows can broadcast on every interface. The consent proposal
        # must still be valid against the CURRENT passive OS LAN scope.
        if not any(
            reviewed.protocol == scope.protocol
            and reviewed.approved_address_ranges == scope.approved_address_ranges
            and reviewed.all_local_interfaces_authorized
            == scope.all_local_interfaces_authorized
            and reviewed.timeout_seconds == scope.timeout_seconds
            and reviewed.max_results == scope.max_results
            for reviewed in local_planner.consent_scopes_for(kind)
        ):
            return None

        probe = WindowsNeighborInformationProbe(
            aep_backend=WindowsAepIdentityBackend(
                is_authorized=authority_guard,
            ),
            aep_scopes=(scope,),
        )
        # Reuse the existing protected WorkStore CAS/evidence path. The
        # candidate evidence cannot resolve a physical identity by itself.
        resolver = InformationResolver(store=self.store, probes=(probe,))
        result = resolver.resolve(need)
        if not authority_guard.consumed_for(scope):
            return result

        # A zero-result or timed-out scan still consumed one exact owner
        # permission. Persist that fact in the canonical InformationNeed so
        # the next proposal can offer another bounded protocol instead of
        # replaying UPnP indefinitely. Never record an attempt on denial.
        marker = f"windows_aep_authorized_scope_consumed:{scope.protocol}"
        for _ in range(3):
            current = self.store.get_information_need(need_id)
            if current is None or not can_rediscover_information(current):
                return result
            if marker in current.evidence_refs:
                return replace(result, need=current)
            try:
                updated = self.store.update_information_need_state(
                    need_id,
                    current.state,
                    expected_revision=current.revision,
                    evidence_refs=(marker,),
                )
            except GoalStoreConflict:
                continue
            return replace(result, need=updated)
        LOGGER.warning(
            "Authorized AEP scope was consumed but durable attempt marking raced"
        )
        return result

    def confirm_owner_discovered_device(
        self,
        *,
        goal_id: str,
        information_need_id: str,
        session_id: str,
        owner_turn_id: str,
        selected_evidence_ref: str | None = None,
    ) -> WorldEntityRefV1 | None:
        """Register owner-confirmed identity only; never pair or control it."""
        return confirm_single_discovered_device(
            store=self.store,
            world=self.world,
            goal_id=goal_id,
            information_need_id=information_need_id,
            session_id=session_id,
            owner_turn_id=owner_turn_id,
            selected_evidence_ref=selected_evidence_ref,
        )

    def authorize_and_discover_network(
        self,
        *,
        goal_id: str,
        session_id: str,
        planner: WindowsLanScopePlanner | None = None,
        owner_turn_id: str,
    ) -> InformationResolutionResult | None:
        """Run one reviewed AEP scan only after exact Windows Hello approval.

        An existing CapabilityRuntime broker issues the AuthorityService
        decision and permit. This never creates a separate approval service
        and never treats observed devices as trusted world entities.
        """
        local_planner = planner or WindowsLanScopePlanner()
        proposal = self.prepare_network_discovery_consent(
            goal_id=goal_id,
            session_id=session_id,
            planner=local_planner,
        )
        if proposal is None:
            return None
        target = proposal.target()
        need_id = str(target["gicc_need_id"])
        need = self.store.get_information_need(need_id)
        if need is None or not can_rediscover_information(need):
            return None
        kind = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        reviewed = next(
            (
                scope
                for scope in local_planner.consent_scopes_for(kind)
                if scope.protocol == target.get("protocol")
                and list(scope.approved_address_ranges)
                == target.get("address_result_filters")
                and scope.all_local_interfaces_authorized
                == target.get("all_local_interfaces")
            ),
            None,
        )
        if reviewed is None:
            return None
        # Atomically consume the canonical USER utterance *before* the Windows
        # Hello dialog. A replay cannot authorize another scan or protocol,
        # even if the first confirmation is denied or the tool is called twice.
        if not self.store.claim_network_discovery_owner_turn(
            goal_id=goal_id,
            need_id=need_id,
            owner_turn_id=owner_turn_id,
        ):
            return None
        authorized = self.capability_runtime.authorize_network_discovery_proposal(
            proposal
        )
        if (
            not isinstance(authorized, AuthorizedNetworkDiscovery)
            or authorized.proposal != proposal
            or authorized.context.session_id != session_id
        ):
            raise CapabilityAuthorizationError(
                "discovery authorization was not bound to exact GICC proposal"
            )
        scope = replace(
            reviewed,
            consent_record_id=authorized.approval_id,
        )
        guard = AepAuthorityExecutionGuard(
            authority=authorized.authority,
            proposal=authorized.proposal,
            context=authorized.context,
            permit_id=authorized.permit_id,
            approval_id=authorized.approval_id,
        )
        return self.apply_approved_network_discovery(
            goal_id=goal_id,
            need_id=need_id,
            session_id=session_id,
            scope=scope,
            authority_guard=guard,
            planner=local_planner,
        )

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._event_loop = asyncio.get_running_loop()
        if self.monitor_bus is not None and self._monitor_subscription_id is None:
            self._monitor_subscription_id = self.monitor_bus.subscribe(
                self._receive_monitor_observation
            )
        self._task = asyncio.create_task(
            self._reconcile_loop(),
            name="jarvis-gicc-runtime-reconciler",
        )

    async def close(self) -> None:
        subscription_id = self._monitor_subscription_id
        self._monitor_subscription_id = None
        if self.monitor_bus is not None and subscription_id is not None:
            self.monitor_bus.unsubscribe(subscription_id)
        self._event_loop = None

        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _receive_monitor_observation(
        self,
        observation: VerifiedMonitorObservationV1,
    ) -> None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                self._process_monitor_observation(observation),
                name=f"jarvis-gicc-monitor-{observation.predicate_id}",
            )
        )

    async def _process_monitor_observation(
        self,
        observation: VerifiedMonitorObservationV1,
    ) -> None:
        processor = self.monitor_processor
        if processor is None:
            return
        predicate = self.store.get_monitor_predicate(observation.predicate_id)
        if predicate is None:
            return
        runtime_state = self.store.get_monitor_runtime_state(predicate.predicate_id)
        if runtime_state is None:
            return

        descriptor = self.capability_runtime.catalog.by_key(
            observation.source_capability_key
        )
        if descriptor is None or not descriptor.execution_enabled:
            return
        semantic = descriptor.semantic_metadata()
        if (
            semantic.semantic_capability_family
            not in set(predicate.observation_capabilities)
            or observation.source_operation not in semantic.observation_operations
            or descriptor.metadata().get("monitor_event_contract")
            != GICC_MONITOR_EVENT_CONTRACT
        ):
            LOGGER.warning(
                "Rejected unbound GICC monitor observation | predicate_id=%s "
                "capability=%s operation=%s",
                predicate.predicate_id,
                observation.source_capability_key,
                observation.source_operation,
            )
            return

        goal = self.store.get_goal(predicate.goal_id)
        if goal is None or self._terminal_goal_state(goal.state):
            return
        await asyncio.to_thread(
            processor.process,
            predicate=predicate,
            observation_digest=observation.observation_digest,
            condition_met=observation.condition_met,
            observed_at_epoch=observation.observed_at_epoch,
            notification_message=(
                f"Monitoring condition verified: {goal.exact_owner_request}"
            ),
            evidence_refs=observation.evidence_refs,
        )

    @staticmethod
    def _terminal_goal_state(state: GoalState) -> bool:
        return state in {
            GoalState.COMPLETED,
            GoalState.FAILED,
            GoalState.CANCELLED,
        }

    def _set_goal_state(self, goal_id: str, state: GoalState) -> OwnerGoalV2:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"unknown GICC goal: {goal_id}")
        if self._terminal_goal_state(goal.state) or goal.state is state:
            return goal
        return self.store.update_goal_state(
            goal.goal_id,
            state,
            expected_revision=goal.goal_revision,
        )

    async def _replan_failed_verification(
        self,
        *,
        goal: OwnerGoalV2,
        failed_plan: PlanGraphV1,
    ) -> PlanGraphV1 | None:
        controller = self.replan_controller
        if controller is None:
            return None

        results = self.store.list_plan_node_results(
            plan_id=failed_plan.plan_id,
            limit=1000,
        )
        failed_verification = next(
            (
                item
                for item in reversed(results)
                if str(item.get("status") or "").strip().casefold() == "failed"
                and isinstance(item.get("payload"), dict)
                and item["payload"].get("route") == "verification"
                and item["payload"].get("verified") is False
            ),
            None,
        )
        if failed_verification is None:
            return None

        prior_evidence = tuple(
            json.dumps(
                {
                    "result_id": item.get("result_id"),
                    "status": item.get("status"),
                    "route": (
                        item["payload"].get("route")
                        if isinstance(item.get("payload"), dict)
                        else None
                    ),
                    "capability_key": (
                        item["payload"].get("capability_key")
                        if isinstance(item.get("payload"), dict)
                        else None
                    ),
                    "operation": (
                        item["payload"].get("operation")
                        if isinstance(item.get("payload"), dict)
                        else None
                    ),
                    "postcondition_ref": (
                        item["payload"].get("postcondition_ref")
                        if isinstance(item.get("payload"), dict)
                        else None
                    ),
                    "reason": (
                        item["payload"].get("reason")
                        if isinstance(item.get("payload"), dict)
                        else None
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in results[-20:]
        )
        try:
            replanned = await controller.replan(
                goal=goal,
                failed_plan=failed_plan,
                context=self.coordinator.current_plan_validation_context(goal.goal_id),
                prior_evidence=prior_evidence,
            )
        except Exception as exc:  # noqa: BLE001 - bounded replan fails closed
            LOGGER.warning(
                "GICC verification replan unavailable | goal_id=%s plan_id=%s error=%s",
                goal.goal_id,
                failed_plan.plan_id,
                type(exc).__name__,
            )
            return None

        self._set_goal_state(goal.goal_id, GoalState.PLANNED)
        return replanned.replacement

    async def _advance_plan_to_blocker(
        self,
        goal_id: str,
        *,
        max_steps: int = 16,
    ) -> tuple[OwnerGoalV2, PlanGraphV1 | None]:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")

        async with self._advance_lock:
            goal = self.store.get_goal(goal_id)
            if goal is None:
                raise ValueError(f"unknown GICC goal: {goal_id}")
            plan = self.store.latest_plan_for_goal(goal.goal_id)
            if plan is None:
                return goal, None

            plan = self.dispatcher.recover_interrupted(plan.plan_id)
            if plan.state is PlanState.FAILED:
                replacement = await self._replan_failed_verification(
                    goal=goal,
                    failed_plan=plan,
                )
                if replacement is None:
                    return self._set_goal_state(goal.goal_id, GoalState.FAILED), plan
                plan = replacement
                goal = self.store.get_goal(goal.goal_id) or goal
            if plan.state is PlanState.SUCCEEDED:
                return self._set_goal_state(goal.goal_id, GoalState.COMPLETED), plan

            for _ in range(max_steps):
                goal = self.store.get_goal(goal.goal_id)
                if goal is None:
                    raise ValueError(f"unknown GICC goal: {goal_id}")
                plan = self.store.latest_plan_for_goal(goal.goal_id)
                if plan is None:
                    return goal, None
                if plan.state is PlanState.SUCCEEDED:
                    return self._set_goal_state(
                        goal.goal_id,
                        GoalState.COMPLETED,
                    ), plan
                if plan.state is PlanState.FAILED:
                    replacement = await self._replan_failed_verification(
                        goal=goal,
                        failed_plan=plan,
                    )
                    if replacement is None:
                        return self._set_goal_state(
                            goal.goal_id,
                            GoalState.FAILED,
                        ), plan
                    plan = replacement
                    goal = self.store.get_goal(goal.goal_id) or goal

                ready = self.dispatcher.ready_nodes(plan)
                if not ready:
                    return goal, plan
                node = ready[0]

                if goal.goal_kind.value == "monitoring":
                    target_state = GoalState.MONITORING
                elif node.node_type is PlanNodeType.VERIFY:
                    target_state = GoalState.VERIFYING
                else:
                    target_state = GoalState.EXECUTING
                goal = self._set_goal_state(goal.goal_id, target_state)

                dispatched = await self.dispatcher.dispatch(
                    plan_id=plan.plan_id,
                    node_id=node.node_id,
                    session_id=goal.source_session_id,
                )
                plan = dispatched.plan

                if dispatched.disposition is PlanDispatchDisposition.SUCCEEDED:
                    if plan.state is PlanState.SUCCEEDED:
                        return self._set_goal_state(
                            goal.goal_id,
                            GoalState.COMPLETED,
                        ), plan
                    continue
                if dispatched.disposition is PlanDispatchDisposition.FAILED:
                    replacement = await self._replan_failed_verification(
                        goal=goal,
                        failed_plan=plan,
                    )
                    if replacement is None:
                        return self._set_goal_state(
                            goal.goal_id,
                            GoalState.FAILED,
                        ), plan
                    plan = replacement
                    goal = self.store.get_goal(goal.goal_id) or goal
                    continue
                return goal, plan

            LOGGER.warning(
                "GICC bounded plan advancement reached max_steps | goal_id=%s "
                "max_steps=%s",
                goal_id,
                max_steps,
            )
            latest_goal = self.store.get_goal(goal_id)
            latest_plan = self.store.latest_plan_for_goal(goal_id)
            assert latest_goal is not None
            return latest_goal, latest_plan

    async def _advance_intake_result(
        self,
        result: GoalIntakeResult,
    ) -> GoalIntakeResult:
        if (
            result.disposition is not GoalIntakeDisposition.PLAN_READY
            or result.goal is None
            or result.plan is None
        ):
            return result
        goal, plan = await self._advance_plan_to_blocker(result.goal.goal_id)
        return replace(result, goal=goal, plan=plan)

    async def pursue(self, *, conversation, turn) -> GoalIntakeResult:
        result = await self.coordinator.pursue(
            conversation=conversation,
            turn=turn,
        )
        if (
            result.goal is not None
            and result.goal.state is GoalState.WAITING_INFORMATION
        ):
            self._information_last_recheck[result.goal.goal_id] = time.monotonic()
        return await self._advance_intake_result(result)

    async def continue_goal(
        self, goal_id: str, *, retry_information: bool = False
    ) -> GoalIntakeResult:
        if retry_information:
            result = await self.coordinator.continue_goal(
                goal_id, retry_information=True
            )
        else:
            result = await self.coordinator.continue_goal(goal_id)
        return await self._advance_intake_result(result)

    def _enqueue_background_terminal_delivery(self, goal: OwnerGoalV2) -> bool:
        if goal.state not in {GoalState.COMPLETED, GoalState.FAILED}:
            return False
        work_ids = tuple(
            sorted(
                {
                    work_id
                    for continuation in self.store.list_continuations(
                        goal_id=goal.goal_id
                    )
                    for work_id in continuation.work_ids
                }
            )
        )
        if not work_ids:
            return False

        completed = goal.state is GoalState.COMPLETED
        kind = WorkDeliveryKind.COMPLETION if completed else WorkDeliveryKind.FAILURE
        event_key = f"gicc-goal:{goal.goal_id}:{goal.state.value}"
        intent = OwnerCommunicationIntentV1.create(
            kind=(
                OwnerCommunicationKind.COMPLETION
                if completed
                else OwnerCommunicationKind.FAILURE
            ),
            event_key=event_key,
            summary=(
                goal.exact_owner_request
                if completed
                else (
                    "I could not verify the required outcome for "
                    f"{goal.exact_owner_request}"
                )
            ),
            goal_id=goal.goal_id,
            terminal=not completed,
            system_outcome_kind=("completed" if completed else "terminal"),
        )
        owner_message = SupervisorOwnerCommunication.compile(intent)
        assert owner_message is not None
        for work_id in work_ids:
            work = self.store.work.get(work_id)
            if work is None:
                continue
            delivery = self.store.work.enqueue_delivery(
                work=work,
                kind=kind,
                message=owner_message.message,
                event_key=owner_message.event_key,
            )
            if delivery is not None:
                self.telemetry.emit(
                    "gicc_goal_owner_delivery_enqueued",
                    goal_id=goal.goal_id,
                    goal_state=goal.state.value,
                    work_id=work.work_id,
                    delivery_id=delivery.delivery_id,
                )
                return True
        return False

    def _capability_continuation_acceptance_ready(
        self,
        goal: OwnerGoalV2,
    ) -> bool:
        changes = self.change_store
        if changes is None:
            return True

        continuations = tuple(
            continuation
            for continuation in self.store.list_continuations(goal_id=goal.goal_id)
            if continuation.blocked_by_type
            is ContinuationBlockerType.CAPABILITY_ACQUISITION
            and continuation.state is ContinuationState.BLOCKED
        )
        for continuation in continuations:
            if not continuation.work_ids:
                # Phase-9 existing-capability reuse creates no EngineeringChange
                # work. Let continue_goal() re-read canonical capability truth.
                continue
            verified = False
            for work_id in continuation.work_ids:
                stage = changes.stage_for_work(work_id)
                if stage is None:
                    continue
                try:
                    lineage = verify_capability_acquisition_completion(
                        changes,
                        change_id=stage.change_id,
                        motivating_goal_id=goal.goal_id,
                        gap_id=continuation.blocked_by_id,
                    )
                except CapabilityAcquisitionLineageError:
                    return False
                if lineage is not None:
                    verified = True
                    break
            if not verified:
                return False
        return True

    async def reconcile_once(self) -> int:
        active = self.store.list_active_goals(limit=100)
        if not active:
            return 0

        if any(goal.state is GoalState.WAITING_CAPABILITY for goal in active):
            self.capability_runtime.refresh_catalog()

        # Only retry deadlines are volatile. Goal, identity and approval
        # evidence remains in the canonical protected store across restart.
        active_ids = {goal.goal_id for goal in active}
        for stale_id in tuple(self._information_last_recheck):
            if stale_id not in active_ids:
                self._information_last_recheck.pop(stale_id, None)

        advanced = 0
        for goal in active:
            before_goal = self.store.get_goal(goal.goal_id)
            before_plan = self.store.latest_plan_for_goal(goal.goal_id)
            if (
                goal.state is GoalState.WAITING_CAPABILITY
                and self.supervisor_cutover is not None
            ):
                cutover = self.supervisor_cutover.coordinate(goal.goal_id)
                self.telemetry.emit(
                    "global_supervisor_cutover_observed",
                    goal_id=goal.goal_id,
                    action=None if cutover.action is None else cutover.action.value,
                    disposition=cutover.disposition.value,
                    accepted=cutover.accepted,
                    mutation_performed=cutover.mutation_performed,
                    decision_digest=cutover.decision_digest,
                )
                if not cutover.accepted:
                    continue
                if (
                    cutover.disposition
                    is SupervisorCutoverDisposition.TERMINAL_OBSERVED
                ):
                    failed_goal = self._set_goal_state(goal.goal_id, GoalState.FAILED)
                    advanced += 1
                    self._enqueue_background_terminal_delivery(failed_goal)
                    LOGGER.warning(
                        "Global Supervisor proved terminal capability failure | "
                        "goal_id=%s change_id=%s",
                        goal.goal_id,
                        cutover.change_id,
                    )
                    continue
            if goal.state is GoalState.WAITING_CAPABILITY:
                if not self._capability_continuation_acceptance_ready(goal):
                    continue
                await self.continue_goal(goal.goal_id)
            elif goal.state is GoalState.WAITING_INFORMATION:
                if not any(
                    can_rediscover_information(need)
                    for need in self.store.list_information_needs(goal_id=goal.goal_id)
                ):
                    continue
                now = time.monotonic()
                last = self._information_last_recheck.get(goal.goal_id)
                interval = max(60.0, self.information_recheck_interval_seconds)
                if last is not None and now - last < interval:
                    continue
                self._information_last_recheck[goal.goal_id] = now
                await self.continue_goal(goal.goal_id, retry_information=True)
            elif goal.state in {
                GoalState.PLANNED,
                GoalState.EXECUTING,
                GoalState.VERIFYING,
            }:
                await self._advance_plan_to_blocker(goal.goal_id)
            else:
                continue

            after_goal = self.store.get_goal(goal.goal_id)
            after_plan = self.store.latest_plan_for_goal(goal.goal_id)
            if (
                before_goal is not None
                and after_goal is not None
                and (
                    before_goal.digest != after_goal.digest
                    or (
                        before_plan is not None
                        and after_plan is not None
                        and before_plan.digest != after_plan.digest
                    )
                )
            ):
                advanced += 1
                if before_goal.state not in {
                    GoalState.COMPLETED,
                    GoalState.FAILED,
                } and after_goal.state in {GoalState.COMPLETED, GoalState.FAILED}:
                    self._enqueue_background_terminal_delivery(after_goal)
                LOGGER.info(
                    "GICC runtime advanced | goal_id=%s from_state=%s "
                    "to_state=%s plan_state=%s",
                    goal.goal_id,
                    before_goal.state.value,
                    after_goal.state.value,
                    None if after_plan is None else after_plan.state.value,
                )
        return advanced

    async def _reconcile_loop(self) -> None:
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "GICC capability continuation reconciliation failed; "
                    "durable goal state remains authoritative"
                )
            await asyncio.sleep(self.reconcile_interval_seconds)


def _reasoning_client(config: JarvisConfig):
    if config.chatgpt_plan_enabled and str(config.chatgpt_plan_model or "").strip():
        return build_chatgpt_plan_structured_output_client(
            model=str(config.chatgpt_plan_model).strip()
        )
    model = str(
        config.hands_planner_model or config.work_orchestration_model or ""
    ).strip()
    if not model:
        raise RuntimeError(
            "GICC APPLY requires a configured structured reasoning model"
        )
    return build_structured_output_client(
        provider=config.ai_provider,
        model=model,
    )


def build_gicc_apply_runtime(
    *,
    config: JarvisConfig,
    capability_runtime: CapabilityRuntime,
    work_runtime: WorkRuntime,
    capability_context: AcquisitionContextProvider,
    telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
    approved_aep_scopes: tuple[ReviewedAepScopeV1, ...] = (),
    trusted_aep_consent_validator: AepAuthorityExecutionGuard | None = None,
) -> GiccApplyRuntime:
    """Compose GICC APPLY without creating new Authority or execution substrates."""

    if work_runtime.capability_acquisition is None:
        raise RuntimeError("GICC APPLY requires the existing Phase-9 coordinator")
    if work_runtime.changes is None:
        raise RuntimeError("GICC APPLY requires canonical EngineeringChange state")
    if not callable(getattr(capability_context, "current", None)):
        raise TypeError("capability_context must provide current()")
    if not callable(getattr(telemetry, "emit", None)):
        raise TypeError("telemetry must provide emit()")
    # Windows AEP may transmit discovery queries across *all* local adapters.
    # The caller must supply an Authority-backed consent validator for every
    # explicit scope; a config flag/voice command cannot activate this source.
    if len(approved_aep_scopes) > 3:
        raise ValueError("AEP protocol scope count exceeds reviewed bound")
    if len({scope.protocol for scope in approved_aep_scopes}) != len(
        approved_aep_scopes
    ):
        raise ValueError("AEP requires distinct reviewed protocol scopes")
    if approved_aep_scopes and not isinstance(
        trusted_aep_consent_validator, AepAuthorityExecutionGuard
    ):
        raise ValueError(
            "AEP requires a policy-audited one-time Authority execution permit"
        )

    store = build_default_goal_store()
    world = WorldRegistry(store)
    world.project_current_computer(capability_runtime.catalog)

    # A configured media target is a routing preference, not an observed
    # physical device. Never manufacture an ACTIVE GICC media_player entity
    # from its label: doing so would bypass device-identity preflight.
    # Existing trusted registry entities and independently reviewed discovery
    # remain the only sources for physical target binding.

    interpreter = build_goal_interpreter(
        provider=config.ai_provider,
        chatgpt_plan_enabled=config.chatgpt_plan_enabled,
        chatgpt_plan_model=config.chatgpt_plan_model,
        reasoning_model=(config.hands_planner_model or config.work_orchestration_model),
    )
    if interpreter is None:
        raise RuntimeError("GICC APPLY could not build GoalInterpreter")
    if not isinstance(interpreter, GoalInterpreter):
        raise TypeError("GICC interpreter composition returned wrong type")

    reasoning_client = _reasoning_client(config)
    planner = GoalPlanner(client=reasoning_client)
    entity_resolver = EntityResolver(
        world,
        discoveries=(ReviewedLocalServiceEntityDiscovery(),),
    )
    information_resolver = InformationResolver(
        store=store,
        probes=(
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.WORLD_REGISTRY,
            ),
            WindowsNeighborInformationProbe(
                aep_backend=(
                    WindowsAepIdentityBackend(
                        is_authorized=trusted_aep_consent_validator
                    )
                    if approved_aep_scopes
                    else None
                ),
                aep_scopes=approved_aep_scopes,
            ),
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY,
            ),
        ),
    )
    migrated_phase9_links = migrate_legacy_phase9_gap_links(
        goal_store=store,
        change_store=work_runtime.changes.store,
    )
    if migrated_phase9_links:
        LOGGER.warning(
            "Migrated durable GICC Phase-9 v1 lineage to append-only v2 evidence: %s",
            ", ".join(migrated_phase9_links),
        )
    migrated_gicc_architectures = migrate_legacy_gicc_external_acceptance_contracts(
        work_runtime.changes.store,
    )
    if migrated_gicc_architectures:
        surfaced = reconcile_owner_change_gates(
            work_runtime.changes,
            change_ids=migrated_gicc_architectures,
        )
        LOGGER.warning(
            "Migrated GICC architecture contracts after lineage upgrade; "
            "fresh owner architecture approval is required: changes=%s gates=%s",
            ", ".join(migrated_gicc_architectures),
            ", ".join(surfaced),
        )
    phase9_bridge = Phase9GoalBridge(
        coordinator=work_runtime.capability_acquisition,
        change_store=work_runtime.changes.store,
        goal_store=store,
        source_revision_provider=work_runtime.current_source_revision,
    )
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=interpreter,
        entity_resolver=entity_resolver,
        requirement_deriver=RequirementDeriver(client=reasoning_client),
        capability_context=capability_context,
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        information_resolver=information_resolver,
        phase9_bridge=phase9_bridge,
        planner=planner,
        telemetry=telemetry,
    )
    monitor_coordinator = MonitoringWorkCoordinator(
        goal_store=store,
        work_starter=work_runtime.orchestrator,
    )
    monitor_dispatcher = GoalMonitoringDispatcher(
        coordinator=monitor_coordinator,
        available_strategies=(MonitoringStrategy.NATIVE_EVENT,),
    )
    monitor_processor = MonitorEventProcessor(
        goal_store=store,
        work_store=work_runtime.store,
        telemetry=telemetry,
    )
    orchestrator = GoalOrchestrator(
        goal_store=store,
        capability_runtime=capability_runtime,
        specialist_action_dispatcher=HandsPlanActionDispatcher(capability_runtime),
        information_resolver=information_resolver,
        phase9_bridge=phase9_bridge,
        monitor_dispatcher=monitor_dispatcher,
        telemetry=telemetry,
    )
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=orchestrator,
    )
    supervisor_projector = ObjectiveWorkspaceProjector(
        goal_store=store,
        change_store=work_runtime.changes.store,
        work_store=work_runtime.store,
    )
    supervisor_mode = (
        AutonomyMode.ASSISTED
        if config.autonomy_mode is AutonomyMode.ASSISTED
        else AutonomyMode.SHADOW
    )
    supervisor_cutover = SupervisorCutoverController(
        projector=supervisor_projector,
        change_coordinator=work_runtime.changes,
        mode=supervisor_mode,
        retry_failed_work=lambda work_id: (
            work_runtime.retry_failed_work_from_supervisor(
                work_id,
                reason=(
                    "Global Supervisor selected RETRY from the deterministic "
                    "Progress Ledger."
                ),
            )
        ),
        invariant_guard=lambda workspace: blocking_capability_workspace_invariant_codes(
            workspace=workspace,
            change_store=work_runtime.changes.store,
        ),
    )
    existing_objective_resume = ExistingObjectiveResumeController(
        projector=supervisor_projector,
        change_store=work_runtime.changes.store,
        cutover=supervisor_cutover,
    )
    return GiccApplyRuntime(
        store=store,
        world=world,
        coordinator=coordinator,
        dispatcher=dispatcher,
        telemetry=telemetry,
        objective_status=OwnerObjectiveStatusResolver(
            goals=store,
            changes=work_runtime.changes.store,
        ),
        replan_controller=ReplanController(
            store=store,
            planner=planner,
        ),
        change_store=work_runtime.changes.store,
        monitor_processor=monitor_processor,
        monitor_bus=DEFAULT_MONITOR_OBSERVATION_BUS,
        capability_runtime=capability_runtime,
        supervisor_cutover=supervisor_cutover,
        existing_objective_resume=existing_objective_resume,
    )
