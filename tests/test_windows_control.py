from __future__ import annotations

from typing import Any

import pytest

from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.windows_control import (
    VisualDesktopControlExecutor,
    WindowsStructuredControlExecutor,
)
from jarvis.computer.structured_windows import StructuredCommandResult


class FakeUi:
    def __init__(self, *, existing: bool = False, final_text: str = "hello") -> None:
        self.existing = existing
        self.final_text = final_text
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _result(self, operation: str, payload: dict[str, Any] | None = None):
        return StructuredCommandResult(
            operation=operation,
            elapsed_ms=1.0,
            payload=payload or {"exit_code": 0},
        )

    def status(self, app: str, *, check: bool = True):
        self.calls.append(("status", (app,), {"check": check}))
        return self._result(
            "status",
            {"exit_code": 0 if self.existing else 1},
        )

    def wait_until_running(self, app: str, *, timeout_seconds: float = 6.0):
        self.calls.append(
            ("wait_until_running", (app,), {"timeout_seconds": timeout_seconds})
        )
        self.existing = True
        return self._result("wait_until_running")

    def inspect(self, app: str, *, selector=None, depth=6, interactive=False):
        self.calls.append(
            (
                "inspect",
                (app,),
                {"selector": selector, "depth": depth, "interactive": interactive},
            )
        )
        return self._result("inspect", {"exit_code": 0, "tree": []})

    def search(self, app: str, query: str, *, max_results: int = 10):
        self.calls.append(
            ("search", (app, query), {"max_results": max_results})
        )
        return self._result("search", {"exit_code": 0, "results": []})

    def get_value(self, app: str, selector: str):
        self.calls.append(("get_value", (app, selector), {}))
        return self._result(
            "get_value",
            {"exit_code": 0, "value": self.final_text},
        )

    def focus(self, app: str, selector: str):
        self.calls.append(("focus", (app, selector), {}))
        return self._result("focus")

    def click(self, app: str, selector: str, *, double=False, right=False):
        self.calls.append(
            ("click", (app, selector), {"double": double, "right": right})
        )
        return self._result("click")

    def invoke(self, app: str, selector: str):
        self.calls.append(("invoke", (app, selector), {}))
        return self._result("invoke")

    def send_text(self, app: str, text: str, *, target_selector=None):
        self.calls.append(
            ("send_text", (app, text), {"target_selector": target_selector})
        )
        self.final_text = text
        return self._result("send_text")

    def set_value(self, app: str, selector: str, value: str):
        self.calls.append(("set_value", (app, selector, value), {}))
        self.final_text = value
        return self._result("set_value")

    def wait_for(self, app: str, selector: str, *, timeout_seconds=5.0, gone=False):
        self.calls.append(
            (
                "wait_for",
                (app, selector),
                {"timeout_seconds": timeout_seconds, "gone": gone},
            )
        )
        return self._result("wait_for")


class FakeLauncher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def launch(self, app: str):
        self.calls.append(app)
        return StructuredCommandResult(
            operation="launch",
            elapsed_ms=1.0,
            payload={"exit_code": 0, "app": app, "pid": 123},
        )


def request(parameters: dict[str, object]) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="hands-test",
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        parameters=parameters,
    )


def test_structured_hands_launch_type_and_verify() -> None:
    ui = FakeUi()
    launcher = FakeLauncher()
    executor = WindowsStructuredControlExecutor(
        backend_factory=lambda: ui,
        launcher_factory=lambda: launcher,
        execution_enabled=True,
    )
    prepared = executor.prepare(
        request(
            {
                "app": "notepad",
                "task": "Open Notepad and type hello",
                "allow_existing_app": False,
                "plan": [
                    {"action": "launch"},
                    {"action": "wait_until_running"},
                    {
                        "action": "send_text",
                        "selector": "Text editor",
                        "text": "hello",
                    },
                    {
                        "action": "verify_value",
                        "selector": "Text editor",
                        "expected": "hello",
                    },
                ],
            }
        )
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["verification_passed"] is True
    assert launcher.calls == ["notepad"]
    assert ("send_text", ("notepad", "hello"), {"target_selector": "Text editor"}) in ui.calls


def test_structured_hands_verification_mismatch_fails() -> None:
    ui = FakeUi(final_text="wrong")
    launcher = FakeLauncher()
    executor = WindowsStructuredControlExecutor(
        backend_factory=lambda: ui,
        launcher_factory=lambda: launcher,
        execution_enabled=True,
    )
    prepared = executor.prepare(
        request(
            {
                "app": "notepad",
                "task": "Open Notepad and verify expected content",
                "allow_existing_app": False,
                "plan": [
                    {"action": "launch"},
                    {"action": "wait_until_running"},
                    {
                        "action": "verify_value",
                        "selector": "Text editor",
                        "expected": "expected",
                    },
                ],
            }
        )
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.FAILED
    assert result.data["verification_passed"] is False
    assert "verification" in (result.reason or "")


def test_structured_hands_existing_app_requires_explicit_authorization() -> None:
    ui = FakeUi(existing=True)
    executor = WindowsStructuredControlExecutor(
        backend_factory=lambda: ui,
        launcher_factory=FakeLauncher,
        execution_enabled=True,
    )
    prepared = executor.prepare(
        request(
            {
                "app": "notepad",
                "task": "Open Notepad and type hello",
                "allow_existing_app": False,
                "plan": [
                    {"action": "launch"},
                    {
                        "action": "send_text",
                        "selector": "Text editor",
                        "text": "hello",
                    },
                ],
            }
        )
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.FAILED
    assert "already running" in (result.reason or "")
    assert not any(call[0] == "send_text" for call in ui.calls)


def test_structured_hands_rejects_unapproved_app() -> None:
    executor = WindowsStructuredControlExecutor(execution_enabled=True)

    with pytest.raises(ValueError, match="not approved"):
        executor.prepare(
            request(
                {
                    "app": "powershell",
                    "task": "Open PowerShell",
                    "plan": [{"action": "launch"}],
                }
            )
        )


def test_structured_hands_rejects_arbitrary_primitive() -> None:
    executor = WindowsStructuredControlExecutor(execution_enabled=True)

    with pytest.raises(ValueError, match="unsupported structured desktop action"):
        executor.prepare(
            request(
                {
                    "app": "notepad",
                    "task": "Open Notepad",
                    "plan": [{"action": "run_command", "text": "whoami"}],
                }
            )
        )


@pytest.mark.parametrize(
    "task",
    [
        "Open Chrome and visit example.com",
        "Open Notepad and save file",
        "Open Notepad and paste my API key",
        "Open terminal and run a command",
    ],
)
def test_visual_fallback_rejects_out_of_scope_tasks(task: str) -> None:
    executor = VisualDesktopControlExecutor(provider_name="gemini", enabled=True)
    request_value = CapabilityRequest(
        session_id="hands-test",
        capability_key="visual:desktop.control",
        operation="execute_visual_desktop_task",
        parameters={"app": "notepad", "task": task},
    )

    with pytest.raises(ValueError):
        executor.prepare(request_value)
