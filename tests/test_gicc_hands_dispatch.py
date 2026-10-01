from __future__ import annotations

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.windows_native import SystemAudioExecutor
from jarvis.goal_intelligence.models import (
    GoalKind,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.runtime import HandsPlanActionDispatcher
from tests.test_capability_runtime import FakeAuthority


class FakeAudioBackend:
    def __init__(self) -> None:
        self.volume = 30.0
        self.muted = False

    def state(self):
        return {
            "device": "fake-speaker",
            "volume_percent": self.volume,
            "muted": self.muted,
        }

    def set_volume(self, percent: float) -> None:
        self.volume = float(percent)

    def set_mute(self, muted: bool) -> None:
        self.muted = bool(muted)


def _runtime() -> tuple[CapabilityRuntime, FakeAuthority]:
    executor = SystemAudioExecutor(FakeAudioBackend())
    authority = FakeAuthority()
    runtime = CapabilityRuntime(
        executors=(executor,),
        resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
        authority=authority,
    )
    runtime.refresh_catalog()
    return runtime, authority


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="gicc-hands-session",
        source_turn_id="gicc-hands-turn",
        exact_owner_request="Set my volume to 42 percent.",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="The computer volume is 42 percent.",
        completion_predicates=("volume_set",),
        created_at="2026-10-01T18:30:00+00:00",
    )


def _plan(goal: OwnerGoalV2, node: PlanNodeV1) -> PlanGraphV1:
    return PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(node,),
        edges=(),
        root_node_ids=(node.node_id,),
        completion_node_ids=(node.node_id,),
        created_at="2026-10-01T18:31:00+00:00",
    )


@pytest.mark.asyncio
async def test_gicc_hands_adapter_reuses_grounded_verified_fast_path() -> None:
    runtime, authority = _runtime()
    dispatcher = HandsPlanActionDispatcher(runtime)
    goal = _goal()
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Set the computer volume.",
        capability_key="system:audio",
        operation="set_master_volume",
        parameters={"percent": 42},
        postcondition_ref="volume_set",
    )

    assert dispatcher.handles(node) is True

    dispatched = await dispatcher.execute(
        goal=goal,
        plan=_plan(goal, node),
        node=node,
    )

    assert dispatched.route == "hands_fast_path"
    assert dispatched.result.ok is True
    assert dispatched.result.data["verification_passed"] is True
    assert authority.events == [
        "authorize:set_master_volume",
        "consume",
        "audit:succeeded",
    ]


def test_gicc_hands_adapter_requires_exact_capability_ownership() -> None:
    runtime, _ = _runtime()
    dispatcher = HandsPlanActionDispatcher(runtime)
    goal = _goal()

    wrong_capability = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Set an external media target volume.",
        capability_key="external:media-player",
        operation="set_master_volume",
        parameters={"percent": 42},
        postcondition_ref="volume_set",
    )
    acquired_external_operation = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=1,
        node_type=PlanNodeType.ACTION,
        summary="Play media on an acquired external target.",
        capability_key="package:tv-control",
        operation="play",
        parameters={"title": "Transporter"},
        postcondition_ref="playback_started",
    )

    assert dispatcher.handles(wrong_capability) is False
    assert dispatcher.handles(acquired_external_operation) is False
