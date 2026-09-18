from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.self_awareness_reads import SelfAwarenessReadExecutor
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState
from jarvis.voice.capability_tools import LocalReadAgentTools, SelfAwarenessAgentTools


class FakeAuthority:
    def authorize(self, prepared):
        del prepared
        return object()

    def consume(self, authorized) -> None:
        del authorized

    def audit_result(self, *, session_id, authorized, result) -> None:
        del session_id, authorized, result

    def close(self) -> None:
        pass


def _toolsets(tmp_path: Path, user_text: str):
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)
    runtime = CapabilityRuntime(
        executors=(executor,),
        resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
        authority=FakeAuthority(),
    )
    conversation = ConversationSession(session_id="session-1")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, user_text)
    return (
        awareness,
        SelfAwarenessAgentTools(runtime, conversation),
        LocalReadAgentTools(runtime, conversation),
    )

@pytest.mark.asyncio
async def test_voice_can_read_deterministic_self_health(tmp_path: Path) -> None:
    awareness, tools, _ = _toolsets(tmp_path, "Jarvis, what is your health status?")
    awareness.observe(
        component_id="runtime.provider",
        source="test_probe",
        state=HealthState.DEGRADED,
        reason_code="provider_unavailable",
        summary="Provider unavailable",
        ttl_seconds=60.0,
    )

    result = await tools.inspect_self_awareness(operation="get_system_health")

    assert result["ok"] is True
    assert result["capability"] == "local:self_awareness.read"
    states = {
        item["component_id"]: item["state"]
        for item in result["data"]["components"]  # type: ignore[index]
    }
    assert states["runtime.provider"] == "degraded"
    awareness.close()

@pytest.mark.asyncio
async def test_self_awareness_execution_does_not_depend_on_keyword_matching(
    tmp_path: Path,
) -> None:
    awareness, tools, _ = _toolsets(
        tmp_path,
        "If the thing that lets you think online disappears, what else stops working?",
    )

    result = await tools.inspect_self_awareness(
        operation="get_component_details",
        component_id="runtime.provider",
    )

    assert result["ok"] is True
    assert "runtime.voice" in result["data"]["affected_components"]  # type: ignore[index]
    awareness.close()

@pytest.mark.asyncio
async def test_voice_can_request_component_implementation_details(
    tmp_path: Path,
) -> None:
    awareness, tools, _ = _toolsets(
        tmp_path,
        "Jarvis, where is your provider component code implemented?",
    )

    result = await tools.inspect_self_awareness(
        operation="get_component_details",
        component_id="runtime.provider",
    )

    assert result["ok"] is True
    assert "src/jarvis/ai_provider.py" in result["data"]["source_paths"]  # type: ignore[index]
    awareness.close()


def test_voice_tool_bundle_exposes_self_health_tool_only_when_available(
    tmp_path: Path,
) -> None:
    awareness, self_tools, combined_tools = _toolsets(tmp_path, "Jarvis health status")

    assert [tool.id for tool in self_tools.tools] == ["inspect_self"]
    assert [tool.id for tool in combined_tools.tools] == [
        "inspect_self",
        "use_computer",
    ]
    awareness.close()
