from __future__ import annotations

import json

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.computer_tools import ComputerControlAgentTools


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
    session = ConversationSession(session_id="hands-voice-test")
    session.start()
    session.accept_turn(ConversationRole.USER, text)
    return session


@pytest.mark.asyncio
async def test_meeting_chatter_cannot_authorize_computer_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    called = False

    def should_not_execute(**kwargs):
        nonlocal called
        called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(cap_runtime, "execute_operation", should_not_execute)
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("then dashboard as you and I have been talking Megan"),
    )

    result = await tools.control(
        app="notepad",
        strategy="structured",
        plan_json='[{"action":"launch"}]',
    )

    assert result["ok"] is False
    assert result["status"] == "computer_control_not_warranted"
    assert called is False


@pytest.mark.asyncio
async def test_named_app_without_control_verb_cannot_authorize(
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
        conversation("Notepad is a Windows text editor."),
    )

    result = await tools.control(
        app="notepad",
        strategy="structured",
        plan_json='[{"action":"launch"}]',
    )

    assert result["ok"] is False
    assert result["status"] == "computer_control_not_warranted"


@pytest.mark.asyncio
async def test_structured_control_binds_task_to_latest_canonical_user_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    user_text = "Open Notepad and type hello there"
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="windows:desktop.control",
            operation="execute_windows_plan",
            data={"verification_passed": True},
            provenance=("Microsoft winapp UI Automation",),
        )

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(cap_runtime, conversation(user_text))
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
        strategy="structured",
        plan_json=json.dumps(plan),
    )

    assert result["ok"] is True
    assert captured["operation"] == "execute_windows_plan"
    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["task"] == user_text
    assert parameters["app"] == "notepad"
    assert parameters["allow_existing_app"] is False
    assert parameters["plan"] == plan


@pytest.mark.asyncio
async def test_existing_app_control_requires_explicit_latest_turn_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="windows:desktop.control",
            operation="execute_windows_plan",
            data={},
        )

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(
        cap_runtime,
        conversation("Type hello in the Notepad window that is already open"),
    )

    await tools.control(
        app="notepad",
        strategy="structured",
        plan_json=json.dumps(
            [{"action": "send_text", "selector": "Text editor", "text": "hello"}]
        ),
    )

    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["allow_existing_app"] is True


@pytest.mark.asyncio
async def test_model_cannot_switch_user_named_app(
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

    result = await tools.control(
        app="calculator",
        strategy="structured",
        plan_json='[{"action":"launch"}]',
    )

    assert result["ok"] is False
    assert result["status"] == "computer_control_not_warranted"


@pytest.mark.asyncio
async def test_visual_strategy_uses_exact_user_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    user_text = "Open Paint and select the pencil tool"
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="visual:desktop.control",
            operation="execute_visual_desktop_task",
            data={},
        )

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = ComputerControlAgentTools(cap_runtime, conversation(user_text))

    result = await tools.control(app="paint", strategy="visual")

    assert result["ok"] is True
    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters == {"app": "paint", "task": user_text}
