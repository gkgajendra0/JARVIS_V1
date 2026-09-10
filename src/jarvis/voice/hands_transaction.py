"""Turn-safe transactional wrappers for voice-driven JARVIS Hands.

Realtime voice providers may call tools before their final transcript is available and
may overlap tool calls across adjacent user turns. This module binds Hands planning and
execution to one canonical voice-generation lease without interrupting an atomic local
mutation that has already begun.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.capabilities.models import CapabilityResult
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.hands.orchestrator import HandsOrchestrationError
from jarvis.hands.planner import HandsRouteGroup

_UIA_OBSERVATION_ACTIONS = frozenset(
    {"inspect", "search", "get_value", "verify_value", "wait_for"}
)
_UIA_MUTATION_ACTIONS = frozenset(
    {"launch", "focus", "click", "invoke", "send_text", "set_value"}
)
_VISUAL_OPERATION = "execute_visual_desktop_task"
_STRUCTURED_UI_OPERATION = "execute_windows_plan"


class HandsGoalSuperseded(HandsOrchestrationError):
    """Raised when newer user speech invalidates an in-flight Hands goal."""


def _require_current(is_current: Callable[[], bool], *, stage: str) -> None:
    if not is_current():
        raise HandsGoalSuperseded(
            f"Hands goal was superseded by a newer USER utterance before {stage}"
        )


def _step_succeeded(step: dict[str, Any]) -> bool:
    payload = step.get("payload")
    if not isinstance(payload, dict):
        return True
    exit_code = payload.get("exit_code")
    return not isinstance(exit_code, int) or exit_code == 0


def _with_verification(
    result: CapabilityResult,
    *,
    basis: str,
) -> CapabilityResult:
    data = dict(result.data)
    data["verification_passed"] = True
    data["verification_basis"] = basis
    return CapabilityResult(
        status=result.status,
        capability_key=result.capability_key,
        operation=result.operation,
        data=data,
        reason=result.reason,
        elapsed_ms=result.elapsed_ms,
        truncated=result.truncated,
        provenance=result.provenance,
    )


def _normalize_read_observation(result: CapabilityResult) -> CapabilityResult:
    """Promote successful UIA observation into bounded verification evidence.

    A purely observational plan is verified by the observation itself. A mutating UIA
    micro-plan is only promoted when at least one successful observation follows its
    final mutation in the same local plan. The semantic planner still decides whether
    that evidence proves the USER goal; this merely avoids another redundant UIA round
    trip solely to establish that post-action state was actually observed.
    """

    if result.operation != _STRUCTURED_UI_OPERATION or not result.ok:
        return result
    if bool(result.data.get("verification_passed")):
        return result
    steps = result.data.get("steps")
    if not isinstance(steps, list) or not steps:
        return result
    typed_steps = [step for step in steps if isinstance(step, dict)]
    if len(typed_steps) != len(steps) or not all(
        _step_succeeded(step) for step in typed_steps
    ):
        return result

    actions = [str(step.get("action", "")).casefold() for step in typed_steps]
    if actions and all(action in _UIA_OBSERVATION_ACTIONS for action in actions):
        return _with_verification(result, basis="successful_read_observation")

    mutation_indexes = [
        index for index, action in enumerate(actions) if action in _UIA_MUTATION_ACTIONS
    ]
    if not mutation_indexes:
        return result
    trailing_actions = actions[mutation_indexes[-1] + 1 :]
    if trailing_actions and all(
        action in _UIA_OBSERVATION_ACTIONS for action in trailing_actions
    ):
        return _with_verification(result, basis="post_mutation_observation")
    return result


class LeaseAwareHandsPlanner:
    """Check a voice-turn lease and enforce structured-first desktop recovery."""

    def __init__(self, planner: Any, is_current: Callable[[], bool]) -> None:
        self._planner = planner
        self._is_current = is_current
        self._hybrid_app_ui = False
        self._selected_operation_names: frozenset[str] | None = None

    @property
    def provider_name(self) -> str:
        return self._planner.provider_name

    @property
    def model_name(self) -> str:
        return self._planner.model_name

    async def route(
        self,
        *,
        goal: str,
        recent_user_turns: tuple[str, ...],
        route_groups: tuple[HandsRouteGroup, ...],
    ) -> tuple[str, ...]:
        _require_current(self._is_current, stage="Hands routing")
        selected = await self._planner.route(
            goal=goal,
            recent_user_turns=recent_user_turns,
            route_groups=route_groups,
        )
        _require_current(self._is_current, stage="accepting the Hands route")

        by_key = {group.key: group for group in route_groups}
        available_keys = set(by_key)
        self._hybrid_app_ui = (
            "app_ui" in selected and "visual_fallback" in available_keys
        )

        selected_for_operations = list(selected)
        if self._hybrid_app_ui and "visual_fallback" not in selected_for_operations:
            selected_for_operations.append("visual_fallback")
        selected_operation_names: set[str] = set()
        for key in selected_for_operations:
            group = by_key.get(key)
            if group is None:
                continue
            selected_operation_names.update(
                operation.operation for operation in group.operations
            )
        self._selected_operation_names = frozenset(selected_operation_names)

        if not self._hybrid_app_ui or "visual_fallback" in selected:
            return selected

        # Make the generic visual substrate reachable for this goal, but next_action
        # withholds it until JARVIS has obtained at least one live UIA observation.
        return (*selected, "visual_fallback")

    async def next_action(
        self,
        *,
        goal: str,
        recent_user_turns: tuple[str, ...],
        candidate_operations,
        observations: tuple[dict[str, Any], ...],
    ):
        _require_current(self._is_current, stage="Hands planning")

        visible_candidates = candidate_operations
        if self._selected_operation_names is not None:
            visible_candidates = tuple(
                item
                for item in visible_candidates
                if item.operation in self._selected_operation_names
            )
        if self._hybrid_app_ui:
            has_structured_observation = any(
                str(item.get("operation", "")) == _STRUCTURED_UI_OPERATION
                for item in observations
            )
            if not has_structured_observation:
                visible_candidates = tuple(
                    item
                    for item in visible_candidates
                    if item.operation != _VISUAL_OPERATION
                )

        if not visible_candidates:
            raise HandsOrchestrationError(
                "Hands routing produced no explicitly selected executable operations"
            )

        decision = await self._planner.next_action(
            goal=goal,
            recent_user_turns=recent_user_turns,
            candidate_operations=visible_candidates,
            observations=observations,
        )
        _require_current(self._is_current, stage="accepting the Hands plan")
        return decision


class LeaseAwareCapabilityRuntime(CapabilityRuntime):
    """Delegate to the canonical runtime with a last-moment turn lease check.

    Atomic execution is intentionally not cancelled once it has started. A new user
    utterance prevents the next action from starting; this avoids half-completed local
    mutations while still stopping stale multi-step goals promptly.
    """

    def __init__(
        self,
        runtime: CapabilityRuntime,
        is_current: Callable[[], bool],
    ) -> None:
        # Do not call CapabilityRuntime.__init__: this object is a narrow delegating
        # transaction view over the already-configured canonical runtime.
        self._runtime = runtime
        self._is_current = is_current

    @property
    def catalog(self):
        return self._runtime.catalog

    @property
    def hands_registry(self):
        return self._runtime.hands_registry

    @property
    def hands_planner(self):
        return self._runtime.hands_planner

    def refresh_catalog(self):
        return self._runtime.refresh_catalog()

    def capability_for_operation(self, operation: str) -> str | None:
        return self._runtime.capability_for_operation(operation)

    def execute_operation(self, **kwargs):
        _require_current(self._is_current, stage="starting a local Hands action")
        result = self._runtime.execute_operation(**kwargs)
        return _normalize_read_observation(result)
