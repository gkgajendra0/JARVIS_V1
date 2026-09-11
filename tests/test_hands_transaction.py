from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.hands.planner import HandsRouteGroup
from jarvis.voice.hands_transaction import (
    HandsGoalSuperseded,
    LeaseAwareCapabilityRuntime,
    LeaseAwareHandsPlanner,
)


class RecordingPlanner:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self, *, after_route=None) -> None:
        self.after_route = after_route
        self.candidate_history: list[tuple[str, ...]] = []

    async def route(self, *, goal, recent_user_turns, route_groups):
        del goal, recent_user_turns, route_groups
        if self.after_route is not None:
            self.after_route()
        return ("app_ui",)

    async def next_action(
        self,
        *,
        goal,
        recent_user_turns,
        candidate_operations,
        observations,
    ):
        del goal, recent_user_turns, observations
        self.candidate_history.append(
            tuple(item.operation for item in candidate_operations)
        )
        return SimpleNamespace(goal_complete=False)


class ResultRuntime:
    def __init__(self, result: CapabilityResult) -> None:
        self.result = result
        self.calls = 0

    def execute_operation(self, **kwargs):
        del kwargs
        self.calls += 1
        return self.result


def _route_groups() -> tuple[HandsRouteGroup, ...]:
    return (
        HandsRouteGroup(
            key="app_ui",
            description="Structured application UI",
            operations=(SimpleNamespace(operation="execute_windows_plan"),),
        ),
        HandsRouteGroup(
            key="visual_fallback",
            description="Visual desktop fallback",
            operations=(SimpleNamespace(operation="execute_visual_desktop_task"),),
        ),
    )


@pytest.mark.asyncio
async def test_hybrid_desktop_hides_visual_until_first_structured_observation() -> None:
    planner = RecordingPlanner()
    wrapped = LeaseAwareHandsPlanner(planner, lambda: True)
    groups = _route_groups()

    selected = await wrapped.route(
        goal="Play my Bhakti playlist in Apple Music",
        recent_user_turns=(),
        route_groups=groups,
    )
    assert selected == ("app_ui", "visual_fallback")

    candidates = tuple(item for group in groups for item in group.operations)
    await wrapped.next_action(
        goal="Play my Bhakti playlist in Apple Music",
        recent_user_turns=(),
        candidate_operations=candidates,
        observations=(),
    )
    assert planner.candidate_history[-1] == ("execute_windows_plan",)

    await wrapped.next_action(
        goal="Play my Bhakti playlist in Apple Music",
        recent_user_turns=(),
        candidate_operations=candidates,
        observations=(
            {
                "operation": "execute_windows_plan",
                "ok": True,
                "verified": False,
            },
        ),
    )
    assert planner.candidate_history[-1] == (
        "execute_windows_plan",
        "execute_visual_desktop_task",
    )


@pytest.mark.asyncio
async def test_planner_discards_route_if_new_user_turn_arrives_during_cloud_call() -> (
    None
):
    current = {"value": True}

    def supersede() -> None:
        current["value"] = False

    wrapped = LeaseAwareHandsPlanner(
        RecordingPlanner(after_route=supersede),
        lambda: current["value"],
    )

    with pytest.raises(HandsGoalSuperseded, match="accepting the Hands route"):
        await wrapped.route(
            goal="Open Calculator",
            recent_user_turns=(),
            route_groups=_route_groups(),
        )


def test_capability_runtime_never_starts_action_after_turn_is_superseded() -> None:
    result = CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="test:desktop",
        operation="execute_windows_plan",
        data={"verification_passed": True},
    )
    runtime = ResultRuntime(result)
    wrapped = LeaseAwareCapabilityRuntime(runtime, lambda: False)  # type: ignore[arg-type]

    with pytest.raises(HandsGoalSuperseded, match="starting a local Hands action"):
        wrapped.execute_operation(operation="execute_windows_plan")

    assert runtime.calls == 0


def test_successful_structured_read_becomes_verified_observation() -> None:
    result = CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        data={
            "steps": [
                {
                    "action": "inspect",
                    "payload": {"tree": [{"name": "Library"}]},
                }
            ],
            "verification_passed": False,
        },
    )
    runtime = ResultRuntime(result)
    wrapped = LeaseAwareCapabilityRuntime(runtime, lambda: True)  # type: ignore[arg-type]

    observed = wrapped.execute_operation(operation="execute_windows_plan")

    assert observed.data["verification_passed"] is True
    assert observed.data["verification_basis"] == "successful_read_observation"


def test_unverified_structured_mutation_stays_unverified() -> None:
    result = CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        data={
            "steps": [{"action": "click", "payload": {"exit_code": 0}}],
            "verification_passed": False,
        },
    )
    runtime = ResultRuntime(result)
    wrapped = LeaseAwareCapabilityRuntime(runtime, lambda: True)  # type: ignore[arg-type]

    observed = wrapped.execute_operation(operation="execute_windows_plan")

    assert observed.data["verification_passed"] is False
    assert "verification_basis" not in observed.data
