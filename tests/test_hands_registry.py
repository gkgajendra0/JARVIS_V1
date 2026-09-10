from __future__ import annotations

from jarvis.capabilities.browser_playwright import BrowserPlanExecutor
from jarvis.capabilities.development_git import DevelopmentGitExecutor
from jarvis.capabilities.document_edits import DocumentEditExecutor
from jarvis.capabilities.local_reads import LocalProjectReadExecutor
from jarvis.capabilities.local_writes import LocalFileWriteExecutor
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.software_management import SoftwareManagementExecutor
from jarvis.capabilities.system_reads import SystemReadExecutor
from jarvis.capabilities.windows_control import (
    VisualDesktopControlExecutor,
    WindowsStructuredControlExecutor,
)
from jarvis.capabilities.windows_devices import (
    BluetoothControlExecutor,
    DisplayControlExecutor,
    PowerSessionExecutor,
)
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    SystemAudioExecutor,
    WindowManagementExecutor,
)
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


def test_registry_covers_every_builtin_executor_operation() -> None:
    registry = HandsCapabilityRegistry.default()
    executor_types = (
        LocalProjectReadExecutor,
        SystemReadExecutor,
        SystemAudioExecutor,
        MediaPlaybackExecutor,
        ClipboardExecutor,
        WindowManagementExecutor,
        AppLifecycleExecutor,
        WindowsStructuredControlExecutor,
        VisualDesktopControlExecutor,
        LocalFileWriteExecutor,
        DocumentEditExecutor,
        BrowserPlanExecutor,
        DisplayControlExecutor,
        BluetoothControlExecutor,
        PowerSessionExecutor,
        SoftwareManagementExecutor,
        DevelopmentGitExecutor,
    )
    executor_operations = {
        operation
        for executor_type in executor_types
        for operation in executor_type.operations
    }
    registry_operations = {item.operation for item in registry.operations}

    assert executor_operations <= registry_operations


def test_new_hands_domains_are_registered() -> None:
    registry = HandsCapabilityRegistry.default()

    assert registry.require("execute_browser_plan").domain is HandsDomain.BROWSER
    assert registry.require("set_display_brightness").domain is HandsDomain.DEVICES
    assert registry.require("install_package").domain is HandsDomain.SOFTWARE
    assert registry.require("git_status").domain is HandsDomain.DEVELOPMENT
    assert registry.require("create_docx").domain is HandsDomain.DOCUMENTS
    assert registry.require("create_text_file").domain is HandsDomain.FILES_WRITE


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
