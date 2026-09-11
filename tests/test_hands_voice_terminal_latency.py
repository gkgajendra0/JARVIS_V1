from __future__ import annotations

from collections import deque

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.hands.contracts import PlannedAction, PlannerTurn
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator


class PassAuthority:
    def authorize(self, prepared):
        return object()

    def consume(self, authorized) -> None:
        pass

    def audit_result(self, *, session_id, authorized, result) -> None:
        pass

    def close(self) -> None:
        pass


class RecordingExecutor:
    capability_key = "test:hands-latency"
    operations = ("set_master_volume",)

    def __init__(self) -> None:
        self.calls = []
        self.descriptor = CapabilityDescriptor.create(
            capability_id="hands-latency",
            source_id="test",
            kind=CapabilityKind.NATIVE_API,
            name="Hands latency test executor",
            description="Test-only verified local execution.",
            operations=self.operations,
            execution_enabled=True,
        )

    def prepare(self, request):
        self.calls.append(request)
        return PreparedCapability(
            request=request,
            target={"operation": request.operation},
            parameters=dict(request.parameters),
            material_summary="Set master volume",
            attributes=ActionAttributes(),
            execution_payload=dict(request.parameters),
        )

    def execute(self, prepared):
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={
                "percent": float(prepared.request.parameters["percent"]),
                "verification_passed": True,
            },
            provenance=("test",),
        )


class CountingPlanner:
    provider_name = "test"
    model_name = "semantic-test"

    def __init__(self) -> None:
        self._turns = deque(
            [
                PlannerTurn(
                    action=PlannedAction(
                        operation="set_master_volume",
                        parameters={"percent": 30},
                        evidence="Set my volume to 30 percent",
                    )
                ),
                PlannerTurn(goal_complete=True),
            ]
        )
        self.next_action_calls = 0

    async def route(self, *, goal, recent_user_turns, route_groups):
        del goal, recent_user_turns, route_groups
        return ("audio",)

    async def next_action(
        self,
        *,
        goal,
        recent_user_turns,
        candidate_operations,
        observations,
    ):
        del goal, recent_user_turns, candidate_operations, observations
        self.next_action_calls += 1
        return self._turns.popleft()


def _runtime(executor: RecordingExecutor) -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(executor,),
        resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
        authority=PassAuthority(),
    )


@pytest.mark.asyncio
async def test_verified_single_route_action_skips_completion_planner_round_trip() -> (
    None
):
    executor = RecordingExecutor()
    planner = CountingPlanner()
    orchestrator = VoiceHandsOrchestrator(_runtime(executor), planner)

    result = await orchestrator.execute_goal(
        session_id="latency-single-step",
        goal="Set my volume to 30 percent.",
    )

    assert result["ok"] is True
    assert result["completed_steps"] == 1
    assert result["completion_mode"] == "deterministic_verified_terminal"
    assert planner.next_action_calls == 1
    assert len(executor.calls) == 1
    assert executor.calls[0].parameters == {"percent": 30.0}
