from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.hands.provider_adapters import OpenAIStructuredOutputClient
from jarvis.voice.hands_fast_path import execute_fast_hint
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in normalization-only construction")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in normalization-only construction")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in normalization-only construction")

    def close(self) -> None:
        pass


class FakePlanner:
    provider_name = "test"
    model_name = "test-model"


class RecordingRuntime:
    def __init__(self, result: CapabilityResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def execute_operation(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _orchestrator() -> VoiceHandsOrchestrator:
    runtime = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )
    return VoiceHandsOrchestrator(runtime, FakePlanner())


@pytest.mark.asyncio
async def test_grounded_reversible_voice_hint_executes_without_hands_planner() -> None:
    orchestrator = _orchestrator()
    runtime = RecordingRuntime(
        CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="system:audio",
            operation="set_master_volume",
            data={"percent": 30.0, "verification_passed": True},
        )
    )
    orchestrator._runtime = runtime  # type: ignore[assignment]  # noqa: SLF001

    result = await execute_fast_hint(
        orchestrator,
        session_id="session-1",
        goal="Jarvis, set my volume to 30 percent.",
        recent_user_turns=(),
        operation_hint="set_master_volume",
        parameters={"percent": 30},
    )

    assert result is not None
    assert result["ok"] is True
    assert result["completion_mode"] == "voice_fast_hint"
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["operation"] == "set_master_volume"
    assert runtime.calls[0]["parameters"] == {"percent": 30.0}


@pytest.mark.asyncio
async def test_high_risk_voice_hint_cannot_enter_fast_path() -> None:
    orchestrator = _orchestrator()
    runtime = RecordingRuntime(
        CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="software:winget",
            operation="install_package",
            data={"verification_passed": True},
        )
    )
    orchestrator._runtime = runtime  # type: ignore[assignment]  # noqa: SLF001

    result = await execute_fast_hint(
        orchestrator,
        session_id="session-1",
        goal="Install Microsoft.PowerToys",
        recent_user_turns=(),
        operation_hint="install_package",
        parameters={"package_id": "Microsoft.PowerToys"},
    )

    assert result is None
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_ungrounded_fast_hint_falls_back_before_execution() -> None:
    orchestrator = _orchestrator()
    runtime = RecordingRuntime(
        CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="system:audio",
            operation="set_master_volume",
            data={"verification_passed": True},
        )
    )
    orchestrator._runtime = runtime  # type: ignore[assignment]  # noqa: SLF001

    result = await execute_fast_hint(
        orchestrator,
        session_id="session-1",
        goal="Jarvis, set my volume to 30 percent.",
        recent_user_turns=(),
        operation_hint="set_master_volume",
        parameters={"percent": 80},
    )

    assert result is None
    assert runtime.calls == []


class ParsedResponse(BaseModel):
    value: int


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=ParsedResponse(value=1))


@pytest.mark.asyncio
async def test_openai_hands_planning_pins_low_reasoning_effort() -> None:
    responses = FakeResponses()
    adapter = OpenAIStructuredOutputClient(
        client=SimpleNamespace(responses=responses),
        model="gpt-5.6-terra",
    )

    parsed = await adapter.parse(
        system_prompt="route",
        input_payload={"goal": "pause music"},
        response_model=ParsedResponse,
    )

    assert parsed.value == 1
    assert responses.kwargs is not None
    assert responses.kwargs["reasoning"] == {"effort": "low"}
