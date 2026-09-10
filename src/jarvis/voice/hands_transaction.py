"""Turn-safe transactional wrappers for voice-driven JARVIS Hands.

Realtime voice providers may call tools before their final transcript is available and
may overlap tool calls across adjacent user turns.  This module binds Hands planning and
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

_UIA_OBSERVATION_ACTIONS = frozenset({"inspect", "search", "get_value", "verify_value"})


class HandsGoalSuperseded(HandsOrchestrationError):
    """Raised when newer user speech invalidates an in-flight Hands goal."""


def _require_current(is_current: Callable[[], bool], *, stage: str) -> None:
    if not is_current():
        raise HandsGoalSuperseded(
            f"Hands goal was superseded by a newer USER utterance before {stage}"
        )


def _normalize_read_observation(result: CapabilityResult) -> CapabilityResult:
    """Mark a successful UIA read plan as verified evidence, never a mutation.

    The structured Windows executor intentionally reports mutation verification only
    when it ran an explicit verify step.  For a purely observational plan, however,
    successful inspect/search/get-value output *is* the requested evidence.  Promoting
    only all-read plans keeps mutation truth strict while letting generic UI questions
    complete from live accessibility state.
    """

    if result.operation != "execute_windows_plan" or not result.ok:
        return result
    if bool(result.data.get("verification_passed")):
        return result
    steps = result.data.get("steps")
    if not isinstance(steps, list) or not steps:
        return result
    actions = {
        str(step.get("action", "")).casefold()
        for step in steps
        if isinstance(step, dict)
    }
    if not actions or not actions.issubset(_UIA_OBSERVATION_ACTIONS):
        return result
    data = dict(result.data)
    data["verification_passed"] = True
    data["verification_basis"] = "successful_read_observation"
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


class LeaseAwareHandsPlanner:
    """Check a voice-turn lease at every cloud-planning boundary."""

    def __init__(self, planner: Any, is_current: Callable[[], bool]) -> None:
        self._planner = planner
        self._is_current = is_current

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

        # Desktop GUI work is a hybrid substrate. Keep screenshot computer-use
        # available to the planner whenever app UI was selected and the visual
        # executor is actually enabled, while still preferring UIA in planner policy.
        available_keys = {group.key for group in route_groups}
        expanded = list(selected)
        if (
            "app_ui" in selected
            and "visual_fallback" in available_keys
            and "visual_fallback" not in expanded
        ):
            expanded.append("visual_fallback")
        return tuple(expanded)

    async def next_action(
        self,
        *,
        goal: str,
        recent_user_turns: tuple[str, ...],
        candidate_operations,
        observations: tuple[dict[str, Any], ...],
    ):
        _require_current(self._is_current, stage="Hands planning")
        decision = await self._planner.next_action(
            goal=goal,
            recent_user_turns=recent_user_turns,
            candidate_operations=candidate_operations,
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
