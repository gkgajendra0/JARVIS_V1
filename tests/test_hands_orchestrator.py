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
from jarvis.hands.app_catalog import AppCatalogError, InstalledApp
from jarvis.hands.contracts import PlannedAction, PlannerTurn
from jarvis.hands.entities import EntityResolutionError
from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator


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
    capability_key = "test:hands"

    def __init__(
        self,
        operations: tuple[str, ...],
        *,
        statuses: dict[str, CapabilityStatus] | None = None,
    ) -> None:
        self.operations = operations
        self.calls = []
        self._statuses = statuses or {}
        self.descriptor = CapabilityDescriptor.create(
            capability_id="hands",
            source_id="test",
            kind=CapabilityKind.NATIVE_API,
            name="Test Hands executor",
            description="Test-only governed semantic executor.",
            operations=operations,
            execution_enabled=True,
        )

    def prepare(self, request):
        self.calls.append(request)
        return PreparedCapability(
            request=request,
            target={"operation": request.operation},
            parameters=dict(request.parameters),
            material_summary=f"Test {request.operation}",
            attributes=ActionAttributes(),
            execution_payload=dict(request.parameters),
        )

    def execute(self, prepared):
        status = self._statuses.get(
            prepared.request.operation, CapabilityStatus.SUCCEEDED
        )
        return CapabilityResult(
            status=status,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={"verification_passed": status is CapabilityStatus.SUCCEEDED},
            reason=None if status is CapabilityStatus.SUCCEEDED else "test unavailable",
            provenance=("test",),
        )


class FakeCatalog:
    def __init__(self) -> None:
        self._entries = (
            InstalledApp("Apple Music", "app.apple.music"),
            InstalledApp("Calculator", "app.calculator"),
        )

    def entries(self):
        return self._entries

    def resolve(self, query: str):
        normalized = " ".join(query.casefold().split())
        for app in self._entries:
            name = app.display_name.casefold()
            if normalized == name or name.startswith(normalized + " "):
                return app
        raise AppCatalogError(f"not found: {query}")

    def launch(self, app):
        raise AssertionError("orchestrator unit tests use a recording executor")


class ScriptedPlanner:
    provider_name = "test"
    model_name = "semantic-test"

    def __init__(self, route: tuple[str, ...], turns: list[PlannerTurn]) -> None:
        self._route = route
        self._turns = deque(turns)
        self.route_group_keys = ()
        self.candidate_history = []
        self.observation_history = []

    async def route(self, *, goal, recent_user_turns, route_groups):
        self.route_group_keys = tuple(group.key for group in route_groups)
        return self._route

    async def next_action(
        self,
        *,
        goal,
        recent_user_turns,
        candidate_operations,
        observations,
    ):
        self.candidate_history.append(
            tuple(item.operation for item in candidate_operations)
        )
        self.observation_history.append(observations)
        return self._turns.popleft()


def runtime_for(executor: RecordingExecutor) -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(executor,),
        resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
        authority=PassAuthority(),
    )


@pytest.mark.asyncio
async def test_apple_music_style_goal_resolves_entity_and_runs_act_observe_loop() -> (
    None
):
    executor = RecordingExecutor(("open_app", "execute_windows_plan"))
    planner = ScriptedPlanner(
        ("app_ui",),
        [
            PlannerTurn(
                action=PlannedAction(
                    operation="open_app",
                    parameters={"app": "Apple Music application"},
                    evidence="Open Apple Music",
                )
            ),
            PlannerTurn(
                action=PlannedAction(
                    operation="execute_windows_plan",
                    parameters={
                        "app": "Apple Music",
                        "plan": [
                            {"action": "search", "query": "Bhakti"},
                            {"action": "click", "selector": "Bhakti"},
                        ],
                    },
                    evidence="play Bhakti playlist",
                )
            ),
            PlannerTurn(goal_complete=True),
        ],
    )
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )

    result = await orchestrator.execute_goal(
        session_id="apple-music-goal",
        goal="Open Apple Music and play Bhakti playlist song.",
    )

    assert result["ok"] is True
    assert result["completed_steps"] == 2
    assert [call.operation for call in executor.calls] == [
        "open_app",
        "execute_windows_plan",
    ]
    assert executor.calls[0].parameters == {"app": "Apple Music"}
    assert executor.calls[1].parameters["app"] == "Apple Music"
    assert executor.calls[1].parameters["task"] == (
        "Open Apple Music and play Bhakti playlist song."
    )
    assert result["entity_trace"][0]["app_id"] == "app.apple.music"
    assert len(planner.observation_history[-1]) == 2


@pytest.mark.asyncio
async def test_orchestrator_rejects_model_target_substitution_before_execution() -> (
    None
):
    executor = RecordingExecutor(("open_app",))
    planner = ScriptedPlanner(
        ("app_lifecycle",),
        [
            PlannerTurn(
                action=PlannedAction(
                    operation="open_app",
                    parameters={"app": "Calculator"},
                    evidence="Open Apple Music",
                )
            )
        ],
    )
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )

    with pytest.raises(EntityResolutionError, match="conflicts"):
        await orchestrator.execute_goal(
            session_id="substitution",
            goal="Open Apple Music",
        )
    assert executor.calls == []


@pytest.mark.asyncio
async def test_display_route_does_not_expose_power_mutations_to_planner() -> None:
    executor = RecordingExecutor(("set_display_brightness", "restart_workstation"))
    planner = ScriptedPlanner(
        ("display",),
        [
            PlannerTurn(
                action=PlannedAction(
                    operation="set_display_brightness",
                    parameters={"percent": 30},
                    evidence="brightness to 30 percent",
                )
            ),
            PlannerTurn(goal_complete=True),
        ],
    )
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )

    result = await orchestrator.execute_goal(
        session_id="display-isolation",
        goal="Set the display brightness to 30 percent.",
    )

    assert result["ok"] is True
    assert "set_display_brightness" in planner.candidate_history[0]
    assert "restart_workstation" not in planner.candidate_history[0]


@pytest.mark.asyncio
async def test_development_read_route_does_not_expose_commit_or_push() -> None:
    executor = RecordingExecutor(("git_status", "git_commit", "git_push_current"))
    planner = ScriptedPlanner(
        ("development_read",),
        [
            PlannerTurn(
                action=PlannedAction(
                    operation="git_status",
                    parameters={"repo": "jarvis"},
                    evidence="Jarvis repository status",
                )
            ),
            PlannerTurn(goal_complete=True),
        ],
    )
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )

    result = await orchestrator.execute_goal(
        session_id="git-read-isolation",
        goal="Tell me the Jarvis repository status.",
    )

    assert result["ok"] is True
    assert planner.candidate_history[0] == ("git_status",)


@pytest.mark.asyncio
async def test_planner_cannot_claim_completion_immediately_after_failed_action() -> (
    None
):
    executor = RecordingExecutor(
        ("open_app",), statuses={"open_app": CapabilityStatus.UNAVAILABLE}
    )
    planner = ScriptedPlanner(
        ("app_lifecycle",),
        [
            PlannerTurn(
                action=PlannedAction(
                    operation="open_app",
                    parameters={"app": "Apple Music"},
                    evidence="Open Apple Music",
                )
            ),
            PlannerTurn(goal_complete=True),
        ],
    )
    orchestrator = HandsOrchestrator(
        runtime_for(executor), planner, app_catalog=FakeCatalog()
    )

    with pytest.raises(HandsOrchestrationError, match="successful latest execution"):
        await orchestrator.execute_goal(
            session_id="false-completion",
            goal="Open Apple Music",
        )
