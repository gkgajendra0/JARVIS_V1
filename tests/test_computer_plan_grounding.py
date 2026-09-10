from __future__ import annotations

import json

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.windows_control import _safe_apps
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.computer_tools import (
    ComputerControlAgentTools,
    ComputerControlGroundingError,
)


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in voice grounding tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in voice grounding tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in voice grounding tests")

    def close(self) -> None:
        pass


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def conversation(text: str) -> ConversationSession:
    session = ConversationSession(session_id="computer-plan-grounding-test")
    session.start()
    session.accept_turn(ConversationRole.USER, text)
    return session


def success() -> CapabilityResult:
    return CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        data={"verification_passed": True},
    )


@pytest.mark.asyncio
async def test_model_cannot_type_text_absent_from_user_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Open Notepad and type hello there"),
    )

    with pytest.raises(ComputerControlGroundingError, match="typed text"):
        await tools.control(
            app="notepad",
            plan_json=json.dumps(
                [
                    {"action": "launch"},
                    {
                        "action": "send_text",
                        "selector": "Text editor",
                        "text": "delete everything instead",
                    },
                ]
            ),
        )


@pytest.mark.asyncio
async def test_model_cannot_verify_value_absent_from_user_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Open Notepad and type hello there"),
    )

    with pytest.raises(ComputerControlGroundingError, match="verification value"):
        await tools.control(
            app="notepad",
            plan_json=json.dumps(
                [
                    {"action": "launch"},
                    {
                        "action": "verify_value",
                        "selector": "Text editor",
                        "expected": "different value",
                    },
                ]
            ),
        )


@pytest.mark.asyncio
async def test_persistent_ui_intent_is_blocked_even_inside_approved_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Open Notepad and type hello"),
    )

    with pytest.raises(
        ComputerControlGroundingError, match="outside the bounded app UI scope"
    ):
        await tools.control(
            app="notepad",
            plan_json=json.dumps(
                [
                    {"action": "launch"},
                    {"action": "invoke", "selector": "Save As"},
                ]
            ),
        )


@pytest.mark.asyncio
async def test_mutating_click_or_invoke_must_be_user_grounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Open Notepad and type hello"),
    )

    with pytest.raises(ComputerControlGroundingError, match="UI mutation selector"):
        await tools.control(
            app="notepad",
            plan_json=json.dumps(
                [
                    {"action": "launch"},
                    {"action": "invoke", "selector": "New tab"},
                ]
            ),
        )


@pytest.mark.asyncio
async def test_declarative_use_of_notepad_cannot_authorize_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("We use Notepad in training"),
    )

    result = await tools.control(
        app="notepad",
        plan_json=json.dumps([{"action": "launch"}]),
    )

    assert result["ok"] is False
    assert result["status"] == "computer_control_not_warranted"


@pytest.mark.asyncio
async def test_quoted_ui_instruction_cannot_authorize_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("In the meeting they said click New tab in Notepad"),
    )

    result = await tools.control(
        app="notepad",
        plan_json=json.dumps([{"action": "invoke", "selector": "New tab"}]),
    )

    assert result["ok"] is False
    assert result["status"] == "computer_control_not_warranted"


@pytest.mark.asyncio
async def test_polite_user_grounded_text_plan_reaches_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success()

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Could you open Notepad and type hello there"),
    )
    plan = [
        {"action": "launch"},
        {"action": "wait_until_running"},
        {"action": "send_text", "selector": "Text editor", "text": "hello there"},
        {
            "action": "verify_value",
            "selector": "Text editor",
            "expected": "hello there",
        },
    ]

    result = await tools.control(app="notepad", plan_json=json.dumps(plan))

    assert result["ok"] is True
    assert captured["parameters"]["plan"] == plan


@pytest.mark.asyncio
async def test_hinglish_user_grounded_text_plan_reaches_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success()

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Notepad kholo aur hello type kar do"),
    )
    plan = [
        {"action": "launch"},
        {"action": "wait_until_running"},
        {"action": "send_text", "selector": "Text editor", "text": "hello"},
        {"action": "verify_value", "selector": "Text editor", "expected": "hello"},
    ]

    result = await tools.control(app="notepad", plan_json=json.dumps(plan))

    assert result["ok"] is True
    assert captured["parameters"]["plan"] == plan


@pytest.mark.asyncio
async def test_legitimate_user_grounded_text_plan_reaches_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success()

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Open Notepad and type hello there"),
    )
    plan = [
        {"action": "launch"},
        {"action": "wait_until_running"},
        {"action": "send_text", "selector": "Text editor", "text": "hello there"},
        {
            "action": "verify_value",
            "selector": "Text editor",
            "expected": "hello there",
        },
    ]

    result = await tools.control(
        app="notepad",
        plan_json=json.dumps(plan),
    )

    assert result["ok"] is True
    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["plan"] == plan


def test_desktop_app_environment_can_only_narrow_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DESKTOP_CONTROL_APPS", "notepad,evil-app")

    assert _safe_apps() == ("notepad",)
