"""Development GICC APPLY composition over existing governed JARVIS subsystems."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace

from jarvis.autonomy.existing_objective import ExistingObjectiveResumeController
from jarvis.autonomy.mode import AutonomyMode
from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)
from jarvis.autonomy.supervisor_cutover import SupervisorCutoverController
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.config import JarvisConfig
from jarvis.engineering_change import ChangeStore
from jarvis.hands.provider_adapters import (
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.voice.generic_grounded_hands import GenericGroundedVoiceHandsOrchestrator
from jarvis.voice.hands_fast_path import FAST_PATH_OPERATIONS, execute_fast_hint
from jarvis.work.models import WorkDeliveryKind
from jarvis.work.runtime import WorkRuntime

from .capability_graph import CapabilityGraphResolver
from .composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from .evaluation import ReplanController
from .execution import GoalPlanDispatcher, PlanDispatchDisposition
from .information import InformationResolver
from .interpretation import GoalInterpreter, build_goal_interpreter
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
from .phase9 import Phase9GoalBridge
from .planning import GoalPlanner
from .requirements import RequirementDeriver
from .service import GoalOrchestrator, SpecialistActionDispatch
from .status import OwnerObjectiveStatusResolver
from .store import GoalStore, build_default_goal_store
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink
from .workspace import ObjectiveWorkspaceProjector
from .world import EntityResolver, WorldRegistry

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
        return await self._advance_intake_result(result)

    async def continue_goal(self, goal_id: str) -> GoalIntakeResult:
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
            if goal.state is GoalState.WAITING_CAPABILITY:
                if not self._capability_continuation_acceptance_ready(goal):
                    continue
                await self.continue_goal(goal.goal_id)
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

    store = build_default_goal_store()
    world = WorldRegistry(store)
    world.project_current_computer(capability_runtime.catalog)

    default_media_target = str(config.default_media_target or "").strip()
    if default_media_target:
        world.register_entity(
            WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name=default_media_target,
                aliases=(
                    "my tv",
                    "my television",
                    "default media target",
                ),
                provenance_refs=("machine_config:default_media_target",),
            )
        )

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
    information_resolver = InformationResolver(store=store)
    phase9_bridge = Phase9GoalBridge(
        coordinator=work_runtime.capability_acquisition,
        change_store=work_runtime.changes.store,
        goal_store=store,
        source_revision_provider=work_runtime.current_source_revision,
    )
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=interpreter,
        entity_resolver=EntityResolver(world),
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
