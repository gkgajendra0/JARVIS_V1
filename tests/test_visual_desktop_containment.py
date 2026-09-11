from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.authority.risk import RiskClassifier
from jarvis.authority.types import RiskClass
from jarvis.capabilities.models import CapabilityRequest
from jarvis.capabilities.visual_desktop import GovernedVisualDesktopExecutor
from jarvis.capabilities.window_scoped_computer import WindowScopedComputerExecutor
from jarvis.capabilities.windows_native import WindowSnapshot
from jarvis.computer.executor import ComputerExecutorError
from jarvis.computer.models import ActionExecutionResult, ComputerAction, ScreenFrame
from jarvis.config import JarvisConfig
from jarvis.machine_config import save_machine_settings


class FakeRegionalExecutor:
    def __init__(self) -> None:
        self.captures: list[dict[str, int]] = []
        self.actions: list[ComputerAction] = []

    def capture_region(self, *, left: int, top: int, width: int, height: int) -> ScreenFrame:
        self.captures.append(
            {"left": left, "top": top, "width": width, "height": height}
        )
        return ScreenFrame(
            png_bytes=b"png",
            left=left,
            top=top,
            width=width,
            height=height,
        )

    def execute(self, action: ComputerAction) -> ActionExecutionResult:
        self.actions.append(action)
        return ActionExecutionResult(ok=True, detail=f"executed:{action.name}")


def snapshot(
    *,
    hwnd: int = 42,
    rect: tuple[int, int, int, int] = (100, 200, 900, 800),
    foreground: bool = True,
) -> WindowSnapshot:
    return WindowSnapshot(
        hwnd=hwnd,
        title="Notepad",
        process="notepad.exe",
        rect=rect,
        visible=True,
        iconic=False,
        zoomed=False,
        foreground=foreground,
    )


class FakeWindowBackend:
    def __init__(self, states: list[WindowSnapshot]) -> None:
        self.states = list(states)
        self.last = states[-1]
        self.focus_calls = 0

    def snapshot(self, app: str) -> WindowSnapshot:
        assert app == "Notepad"
        if self.states:
            self.last = self.states.pop(0)
        return self.last

    def focus(self, app: str) -> WindowSnapshot:
        assert app == "Notepad"
        self.focus_calls += 1
        current = self.snapshot(app)
        self.last = WindowSnapshot(
            hwnd=current.hwnd,
            title=current.title,
            process=current.process,
            rect=current.rect,
            visible=current.visible,
            iconic=current.iconic,
            zoomed=current.zoomed,
            foreground=True,
        )
        return self.last


def test_window_scoped_capture_exposes_only_target_window_rectangle() -> None:
    local = FakeRegionalExecutor()
    windows = FakeWindowBackend([snapshot(foreground=False), snapshot()])
    executor = WindowScopedComputerExecutor(
        "Notepad",
        executor=local,
        window_backend=windows,  # type: ignore[arg-type]
    )

    frame = executor.capture_screen()

    assert windows.focus_calls == 1
    assert local.captures == [
        {"left": 100, "top": 200, "width": 800, "height": 600}
    ]
    assert (frame.left, frame.top, frame.width, frame.height) == (100, 200, 800, 600)


def test_window_scoped_input_rejects_coordinate_outside_authorized_window() -> None:
    local = FakeRegionalExecutor()
    windows = FakeWindowBackend([snapshot(), snapshot()])
    executor = WindowScopedComputerExecutor(
        "Notepad",
        executor=local,
        window_backend=windows,  # type: ignore[arg-type]
    )
    executor.capture_screen()

    with pytest.raises(ComputerExecutorError, match="outside the authorized"):
        executor.execute(ComputerAction("click", {"x": 99, "y": 300}))

    assert local.actions == []


def test_window_scoped_input_rejects_stale_geometry_after_window_moves() -> None:
    local = FakeRegionalExecutor()
    windows = FakeWindowBackend(
        [
            snapshot(),
            snapshot(rect=(120, 220, 920, 820)),
        ]
    )
    executor = WindowScopedComputerExecutor(
        "Notepad",
        executor=local,
        window_backend=windows,  # type: ignore[arg-type]
    )
    executor.capture_screen()

    with pytest.raises(ComputerExecutorError, match="moved or resized"):
        executor.execute(ComputerAction("click", {"x": 300, "y": 400}))

    assert local.actions == []


def test_window_scoped_keyboard_blocks_global_app_switch_shortcuts() -> None:
    local = FakeRegionalExecutor()
    windows = FakeWindowBackend([snapshot(), snapshot()])
    executor = WindowScopedComputerExecutor(
        "Notepad",
        executor=local,
        window_backend=windows,  # type: ignore[arg-type]
    )
    executor.capture_screen()

    with pytest.raises(ComputerExecutorError, match="switch applications"):
        executor.execute(ComputerAction("hotkey", {"keys": ["alt", "tab"]}))

    assert local.actions == []


def visual_request(task: str, *, app: str = "Notepad") -> CapabilityRequest:
    return CapabilityRequest(
        session_id="session-1",
        capability_key="visual:desktop.control",
        operation="execute_visual_desktop_task",
        parameters={"app": app, "task": task},
    )


def test_visual_fallback_allows_normal_persistent_external_app_work() -> None:
    executor = GovernedVisualDesktopExecutor(provider_name="openai")

    prepared = executor.prepare(
        visual_request("Save this document, export a PDF, then send it to my teammate")
    )

    assert prepared.attributes.persistent_write is True
    assert prepared.attributes.external_side_effect is True
    assessment = RiskClassifier().classify(prepared.attributes)
    assert assessment.risk_class is RiskClass.PERSISTENT_OR_EXTERNAL
    assert prepared.target["strategy"] == "window_scoped_visual_fallback"


@pytest.mark.parametrize(
    "task",
    (
        "Delete this file permanently",
        "Open PowerShell and run this command",
        "Change the security permission",
        "Install this application",
        "Paste my password into the form",
    ),
)
def test_visual_fallback_rejects_critical_or_destructive_intents(task: str) -> None:
    executor = GovernedVisualDesktopExecutor(provider_name="openai")

    with pytest.raises(ValueError, match="critical/destructive scope"):
        executor.prepare(visual_request(task))


def test_visual_fallback_routes_browser_apps_to_dedicated_browser_capability() -> None:
    executor = GovernedVisualDesktopExecutor(provider_name="openai")

    with pytest.raises(ValueError, match="Playwright"):
        executor.prepare(visual_request("Open my dashboard", app="Google Chrome"))


def test_visual_opt_in_round_trips_through_machine_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    save_machine_settings({"JARVIS_VISUAL_COMPUTER_USE_ENABLED": "true"})

    config = JarvisConfig.from_environment()

    assert config.visual_computer_use_enabled is True
