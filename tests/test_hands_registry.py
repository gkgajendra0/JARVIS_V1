from __future__ import annotations

from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.hands.models import (
    ExecutionSubstrate,
    HandsDomain,
    HandsWorkflowStep,
)
from jarvis.hands.registry import HandsCapabilityRegistry
from jarvis.hands.workflow import HandsWorkflowRunner


class FakeRuntime:
    def __init__(self, failing_operation: str | None = None) -> None:
        self.failing_operation = failing_operation
        self.calls: list[tuple[str, dict]] = []

    def execute_operation(self, *, session_id, operation, parameters, origin):
        del session_id, origin
        self.calls.append((operation, dict(parameters)))
        failed = operation == self.failing_operation
        return CapabilityResult(
            status=CapabilityStatus.FAILED if failed else CapabilityStatus.SUCCEEDED,
            capability_key=f"fake:{operation}",
            operation=operation,
            data={},
            reason="boom" if failed else None,
        )


def test_registry_prefers_native_for_media() -> None:
    registry = HandsCapabilityRegistry.default()

    operation = registry.require("pause_media")

    assert operation.domain is HandsDomain.MEDIA_PLAYBACK
    assert operation.preferred_substrates == (
        ExecutionSubstrate.NATIVE_API,
        ExecutionSubstrate.HUMAN,
    )


def test_registry_prefers_structured_before_visual_for_app_ui() -> None:
    operation = HandsCapabilityRegistry.default().require("execute_windows_plan")

    assert operation.domain is HandsDomain.APP_UI
    assert operation.preferred_substrates == (
        ExecutionSubstrate.STRUCTURED_AUTOMATION,
        ExecutionSubstrate.VISUAL_FALLBACK,
        ExecutionSubstrate.HUMAN,
    )


def test_workflow_executes_short_sequence_through_runtime() -> None:
    runtime = FakeRuntime()
    runner = HandsWorkflowRunner(runtime)

    result = runner.execute(
        session_id="session-1",
        steps=(
            HandsWorkflowStep("open_app", {"app": "notepad"}),
            HandsWorkflowStep("set_master_volume", {"percent": 25}),
        ),
    )

    assert result.ok is True
    assert result.completed_steps == 2
    assert runtime.calls == [
        ("open_app", {"app": "notepad"}),
        ("set_master_volume", {"percent": 25}),
    ]


def test_workflow_stops_at_first_failed_capability() -> None:
    runtime = FakeRuntime(failing_operation="pause_media")
    runner = HandsWorkflowRunner(runtime)

    result = runner.execute(
        session_id="session-1",
        steps=(
            HandsWorkflowStep("open_app", {"app": "notepad"}),
            HandsWorkflowStep("pause_media", {}),
            HandsWorkflowStep("set_master_volume", {"percent": 20}),
        ),
    )

    assert result.ok is False
    assert result.completed_steps == 1
    assert result.failed_operation == "pause_media"
    assert [call[0] for call in runtime.calls] == ["open_app", "pause_media"]
