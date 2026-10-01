"""Development GICC APPLY composition over existing governed JARVIS subsystems."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.config import JarvisConfig
from jarvis.hands.provider_adapters import (
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.voice.generic_grounded_hands import GenericGroundedVoiceHandsOrchestrator
from jarvis.voice.hands_fast_path import FAST_PATH_OPERATIONS, execute_fast_hint
from jarvis.work.runtime import WorkRuntime

from .capability_graph import CapabilityGraphResolver
from .composition import GoalIntelligenceCoordinator
from .execution import GoalPlanDispatcher
from .information import InformationResolver
from .interpretation import GoalInterpreter, build_goal_interpreter
from .models import GoalState, OwnerGoalV2, PlanGraphV1, PlanNodeV1, WorldEntityRefV1
from .phase9 import Phase9GoalBridge
from .planning import GoalPlanner
from .requirements import RequirementDeriver
from .service import GoalOrchestrator, SpecialistActionDispatch
from .store import GoalStore, build_default_goal_store
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink
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
            status=(
                CapabilityStatus.SUCCEEDED
                if ok
                else CapabilityStatus.FAILED
            ),
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
    reconcile_interval_seconds: float = 1.0
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._reconcile_loop(),
            name="jarvis-gicc-capability-continuation",
        )

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def reconcile_once(self) -> int:
        waiting = tuple(
            goal
            for goal in self.store.list_active_goals(limit=100)
            if goal.state is GoalState.WAITING_CAPABILITY
        )
        if not waiting:
            return 0
        self.capability_runtime.refresh_catalog()
        advanced = 0
        for goal in waiting:
            before = goal.state
            result = await self.coordinator.continue_goal(goal.goal_id)
            if result.goal is not None and result.goal.state is not before:
                advanced += 1
                LOGGER.info(
                    "GICC capability continuation advanced | goal_id=%s "
                    "from_state=%s to_state=%s disposition=%s",
                    goal.goal_id,
                    before.value,
                    result.goal.state.value,
                    result.disposition.value,
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
        planner=GoalPlanner(client=reasoning_client),
        telemetry=telemetry,
    )
    orchestrator = GoalOrchestrator(
        goal_store=store,
        capability_runtime=capability_runtime,
        specialist_action_dispatcher=HandsPlanActionDispatcher(capability_runtime),
        information_resolver=information_resolver,
        phase9_bridge=phase9_bridge,
        telemetry=telemetry,
    )
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=orchestrator,
    )
    return GiccApplyRuntime(
        store=store,
        world=world,
        coordinator=coordinator,
        dispatcher=dispatcher,
        telemetry=telemetry,
        capability_runtime=capability_runtime,
    )
