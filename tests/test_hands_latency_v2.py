from __future__ import annotations

from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import BaseModel

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.computer.latency_provider import LowLatencyOpenAIComputerUseProvider
from jarvis.computer.models import ScreenFrame
from jarvis.conversation import ConversationSession
from jarvis.hands.planner import HandsRouteSelection
from jarvis.hands.provider_adapters import _openai_reasoning_effort
from jarvis.voice.capability_tools import LocalReadAgentTools
from jarvis.voice.hands_latency_tool import (
    FastHandsMode,
    LatencyOptimizedHandsGoalAgentTools,
    LatencyOptimizedVoiceHandsOrchestrator,
)


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in latency wiring tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in latency wiring tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in latency wiring tests")

    def close(self) -> None:
        pass


def _runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def test_production_voice_tool_uses_explicit_fast_or_planner_mode() -> None:
    modes = set(get_args(FastHandsMode))
    assert "planner" in modes
    assert "get_master_volume" in modes
    assert "set_master_volume" in modes
    assert "pause_media" in modes
    assert "open_app" in modes
    assert "" not in modes

    conversation = ConversationSession(session_id="latency-v2-tool")
    conversation.start()
    toolset = LocalReadAgentTools(_runtime(), conversation)
    assert isinstance(toolset._hands, LatencyOptimizedHandsGoalAgentTools)
    assert [tool.id for tool in toolset.tools] == ["use_computer"]


def test_verified_visual_full_goal_is_deterministic_terminal() -> None:
    assert LatencyOptimizedVoiceHandsOrchestrator._verified_terminal(
        "execute_visual_desktop_task",
        ("app_lifecycle", "app_ui", "visual_fallback"),
    )
    assert not LatencyOptimizedVoiceHandsOrchestrator._verified_terminal(
        "execute_windows_plan",
        ("app_lifecycle", "app_ui", "visual_fallback"),
    )


def test_openai_router_uses_no_reasoning_but_planning_stays_low() -> None:
    class PlannerSchema(BaseModel):
        value: int

    assert _openai_reasoning_effort(HandsRouteSelection) == "none"
    assert _openai_reasoning_effort(PlannerSchema) == "low"


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="response-1", output=[], output_text="done")


class FakeExecutor:
    def capture_screen(self) -> ScreenFrame:
        return ScreenFrame(
            png_bytes=b"test-png",
            left=0,
            top=0,
            width=100,
            height=100,
        )

    def execute(self, action):
        raise AssertionError(f"no computer action expected, got {action}")


@pytest.mark.asyncio
async def test_openai_visual_computer_use_pins_low_reasoning() -> None:
    responses = FakeResponses()
    provider = LowLatencyOpenAIComputerUseProvider(
        client=SimpleNamespace(responses=responses),
    )

    result = await provider.execute(
        "Inspect the authorized app window.",
        executor=FakeExecutor(),
        max_steps=3,
    )

    assert result.ok is True
    assert len(responses.calls) == 1
    assert responses.calls[0]["reasoning"] == {"effort": "low"}
    assert responses.calls[0]["store"] is False
