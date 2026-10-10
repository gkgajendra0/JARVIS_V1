from __future__ import annotations

import asyncio

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
    _SessionToolBundle,
)
from jarvis.voice.runtime import VoiceRuntimeState
from jarvis.work.models import WorkState
from jarvis.work.runtime import WorkRuntime
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def submit(self, work_id, *, priority):
        del priority
        return work_id


def _complete(work: SQLiteWorkStore, work_id: str) -> None:
    item = work.require(work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(WorkState.COMPLETED),
        expected_version=running.version,
    )


def test_pending_change_gate_suppresses_fresh_gicc_goal_tools(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Build TV control", "session", "turn")
    research = store.list_stages(change.change_id)[0]
    _complete(work, research.work_id)
    architecture = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom"},
    )
    coordinator.reconcile(change.change_id)
    GateService(store, verify_owner=lambda *_: False).present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )

    runtime = object.__new__(WorkRuntime)
    runtime.changes = coordinator

    conversation = ConversationSession(session_id="owner-session")
    conversation.start()
    action_calls: list[str] = []
    read_calls: list[str] = []
    read_tool = object()

    def gicc_action_tools(_conversation: ConversationSession) -> list:
        action_calls.append("called")
        return [object()]

    def gicc_read_tools(_conversation: ConversationSession) -> list:
        read_calls.append("called")
        return [read_tool]

    bundle = _SessionToolBundle(
        None,
        lambda: conversation,
        memory_runtime=None,
        memory_query_coordinator=None,
        research_service=None,
        capability_runtime=None,
        work_runtime=runtime,
        gicc_action_tool_factory=gicc_action_tools,
        gicc_read_tool_factory=gicc_read_tools,
        allow_direct_capability_acquisition=True,
    )

    tools = bundle.tools

    assert action_calls == []
    assert read_calls == ["called"]
    assert read_tool in tools


def test_bound_change_gate_before_owner_turn_fails_closed_without_exception(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Build generic capability", "session", "turn")
    research = store.list_stages(change.change_id)[0]
    _complete(work, research.work_id)
    architecture = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom"},
    )
    coordinator.reconcile(change.change_id)
    gate = GateService(store, verify_owner=lambda *_: False).present(
        change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )

    runtime = object.__new__(WorkRuntime)
    runtime.changes = coordinator

    conversation = ConversationSession(session_id="owner-session")
    conversation.start()

    from jarvis.voice.work_tools import WorkAgentTools

    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_change_gate_id=gate.gate_id,
        allow_capability_acquisition=False,
    )

    import asyncio

    result = asyncio.run(tools.decide_bound_change_gate(None))  # type: ignore[arg-type]

    assert result["ok"] is False
    assert result["status"] == "awaiting_owner_turn"
    assert GateService(store, verify_owner=lambda *_: False).pending_gate_ids() == (
        gate.gate_id,
    )


def test_live_work_tool_refresh_keeps_exact_approval_and_replay_context(
    tmp_path,
) -> None:
    """Enumerating the live tool bundle cannot erase a pending gate binding."""
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Build owner capability", "source", "turn")
    research = store.list_stages(change.change_id)[0]
    _complete(work, research.work_id)
    architecture = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"strategy": "build_custom"},
    )
    coordinator.reconcile(change.change_id)
    gate = GateService(store, verify_owner=lambda *_: False).present(
        change.change_id, GateKind.ARCHITECTURE, architecture.artifact_id
    )

    runtime = object.__new__(WorkRuntime)
    runtime.changes = coordinator
    conversation = ConversationSession(session_id="owner-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "What is my task status?")
    active_session = [conversation]
    bundle = _SessionToolBundle(
        None,
        lambda: active_session[0],
        memory_runtime=None,
        memory_query_coordinator=None,
        research_service=None,
        capability_runtime=None,
        work_runtime=runtime,
        allow_direct_capability_acquisition=True,
    )

    _ = bundle.tools
    bound = bundle._session_work_tools
    assert bound is not None
    assert bound._bind_contextual_change_gate_from_status()
    assert bound._contextual_change_gate_id == gate.gate_id
    bound._last_gate_decision_attempt_turn_id = "seen-turn"

    # LiveKit can request a new exposed tool list between the status and reply.
    refreshed = bundle.tools
    assert bundle._session_work_tools is bound
    assert bound._contextual_change_gate_id == gate.gate_id
    assert bound._last_gate_decision_attempt_turn_id == "seen-turn"
    assert bound.start_capability_acquisition not in refreshed

    # Gate visibility must change dynamically without replacing the instance.
    assert bound.start_capability_acquisition in bound.tools_for(
        allow_capability_acquisition=True,
    )
    assert bound.start_capability_acquisition not in bound.tools_for(
        allow_capability_acquisition=False,
    )

    # The next wake session must never inherit the previous session's binding.
    next_session = ConversationSession(session_id="next-session")
    next_session.start()
    active_session[0] = next_session
    _ = bundle.tools
    assert bundle._session_work_tools is not bound
    assert bundle._session_work_tools is not None
    assert bundle._session_work_tools._contextual_change_gate_id is None


@pytest.mark.asyncio
async def test_proactive_gate_tool_factory_does_not_reset_same_turn_replay_guard(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound approval remains one-shot even when the voice tools are re-enumerated."""
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Capability approval", "source", "turn")
    research = store.list_stages(change.change_id)[0]
    _complete(work, research.work_id)
    architecture = store.add_artifact(
        change.change_id, kind="architecture", payload={"strategy": "build_custom"}
    )
    coordinator.reconcile(change.change_id)
    gate = GateService(store, verify_owner=lambda *_: False).present(
        change.change_id, GateKind.ARCHITECTURE, architecture.artifact_id
    )
    runtime = object.__new__(WorkRuntime)
    runtime.changes = coordinator

    controller = object.__new__(CanonicalActiveSpeakerRuntimeController)
    controller._work_runtime = runtime
    controller._shutdown = asyncio.Event()
    controller._state = VoiceRuntimeState.IDLE
    controller._active_end = None
    monkeypatch.setattr(controller, "_cancel_timeout", lambda: None)

    async def fake_session_runner(*, session_tool_factory, **kwargs) -> None:
        del kwargs
        conversation = ConversationSession(session_id="approval-session")
        conversation.start()
        first = session_tool_factory(conversation)
        second = session_tool_factory(conversation)
        assert first == second
        next_conversation = ConversationSession(session_id="other-session")
        next_conversation.start()
        assert session_tool_factory(next_conversation) != first

    monkeypatch.setattr(controller, "_run_one_session_owned", fake_session_runner)
    assert not await controller._run_change_gate_interaction(
        gate_id=gate.gate_id,
        question="Please review this architecture",
    )


@pytest.mark.asyncio
async def test_approval_tool_failure_does_not_forge_engineering_signoff(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verifier/runtime exception leaves the exact pending gate undecided."""
    from jarvis.voice.work_tools import WorkAgentTools

    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    coordinator = ChangeCoordinator(store, RecordingBackend())
    change = coordinator.start("Verify approval failure", "source", "turn")
    research = store.list_stages(change.change_id)[0]
    _complete(work, research.work_id)
    architecture = store.add_artifact(
        change.change_id, kind="architecture", payload={"strategy": "build_custom"}
    )
    coordinator.reconcile(change.change_id)
    gate = GateService(store, verify_owner=lambda *_: False).present(
        change.change_id, GateKind.ARCHITECTURE, architecture.artifact_id
    )
    runtime = object.__new__(WorkRuntime)
    runtime.changes = coordinator
    conversation = ConversationSession(session_id="approval-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Yes, I approve.")
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_change_gate_id=gate.gate_id,
        allow_capability_acquisition=False,
    )

    class BrokenVerifier:
        def decide_latest(self, *args, **kwargs):
            del args, kwargs
            raise RuntimeError("synthetic owner verification failure")

    monkeypatch.setattr(tools, "_change_service", lambda: BrokenVerifier())
    result = await tools.decide_bound_change_gate(None)
    assert result["ok"] is False
    assert result["status"] == "approval_processing_error"
    assert result["retry_requires_new_owner_turn"] is True
    assert "approved" not in result
    assert gate.gate_id in GateService(
        store, verify_owner=lambda *_: False
    ).pending_gate_ids()

    # A second call on the same canonical owner utterance cannot retry approval.
    replay = await tools.decide_bound_change_gate(None)
    assert replay["status"] == "approval_already_attempted_for_turn"
