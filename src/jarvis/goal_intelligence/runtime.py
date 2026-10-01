"""Development GICC APPLY composition over existing governed JARVIS subsystems."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.config import JarvisConfig
from jarvis.hands.provider_adapters import (
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.work.runtime import WorkRuntime

from .capability_graph import CapabilityGraphResolver
from .composition import GoalIntelligenceCoordinator
from .information import InformationResolver
from .interpretation import GoalInterpreter, build_goal_interpreter
from .models import WorldEntityRefV1
from .phase9 import Phase9GoalBridge
from .planning import GoalPlanner
from .requirements import RequirementDeriver
from .store import GoalStore, build_default_goal_store
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink
from .world import EntityResolver, WorldRegistry


@dataclass(frozen=True, slots=True)
class GiccApplyRuntime:
    store: GoalStore
    world: WorldRegistry
    coordinator: GoalIntelligenceCoordinator
    telemetry: GiccTelemetrySink


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
        reasoning_model=(
            config.hands_planner_model or config.work_orchestration_model
        ),
    )
    if interpreter is None:
        raise RuntimeError("GICC APPLY could not build GoalInterpreter")
    if not isinstance(interpreter, GoalInterpreter):
        raise TypeError("GICC interpreter composition returned wrong type")

    reasoning_client = _reasoning_client(config)
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=interpreter,
        entity_resolver=EntityResolver(world),
        requirement_deriver=RequirementDeriver(client=reasoning_client),
        capability_context=capability_context,
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        information_resolver=InformationResolver(store=store),
        phase9_bridge=Phase9GoalBridge(
            coordinator=work_runtime.capability_acquisition,
            change_store=work_runtime.changes.store,
            goal_store=store,
            source_revision_provider=work_runtime.current_source_revision,
        ),
        planner=GoalPlanner(client=reasoning_client),
        telemetry=telemetry,
    )
    return GiccApplyRuntime(
        store=store,
        world=world,
        coordinator=coordinator,
        telemetry=telemetry,
    )
