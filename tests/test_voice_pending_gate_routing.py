from __future__ import annotations

from jarvis.conversation import ConversationSession
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.voice.canonical_active_speaker_runtime import _SessionToolBundle
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
