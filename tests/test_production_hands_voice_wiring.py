from __future__ import annotations

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationSession
from jarvis.voice import canonical_active_speaker_runtime as active_runtime
from jarvis.voice.capability_tools import LocalReadAgentTools


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run while composing voice tools")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run while composing voice tools")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run while composing voice tools")

    def close(self) -> None:
        pass


def _runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def _conversation() -> ConversationSession:
    conversation = ConversationSession(session_id="production-hands-voice-wiring")
    conversation.start()
    return conversation


def test_local_computer_toolset_exposes_only_hands_specialist_boundary() -> None:
    toolset = LocalReadAgentTools(_runtime(), _conversation())
    assert [tool.id for tool in toolset.tools] == ["use_computer"]


def test_production_session_bundle_includes_hands_specialist_tool(monkeypatch) -> None:
    runtime = _runtime()
    conversation = _conversation()
    sentinel_hands = object()
    seen = []

    class FakeLocalReadAgentTools:
        def __init__(self, capability_runtime, session_conversation) -> None:
            seen.append((capability_runtime, session_conversation))

        @property
        def tools(self) -> list[object]:
            return [sentinel_hands]

    monkeypatch.setattr(active_runtime, "LocalReadAgentTools", FakeLocalReadAgentTools)
    bundle = active_runtime._SessionToolBundle(
        None,
        lambda: conversation,
        memory_runtime=None,
        memory_query_coordinator=None,
        research_service=None,
        capability_runtime=runtime,
    )

    assert bundle.tools == [sentinel_hands]
    assert seen == [(runtime, conversation)]
