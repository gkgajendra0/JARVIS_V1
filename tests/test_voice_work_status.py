from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationSession
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.runtime import WorkRuntime
from jarvis.work.store import SQLiteWorkStore


@pytest.mark.asyncio
async def test_active_work_status_surfaces_recent_failure_when_none_remains_active(
    tmp_path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    older = WorkItem(
        request="Older completed task",
        work_type=WorkType.RESEARCH,
        source_session_id="session-old",
        source_turn_id="turn-old",
    )
    store.create(older)
    older_running = older.transition(WorkState.RUNNING, status_detail="working")
    older_running = store.save(older_running, expected_version=older.version)
    older_completed = older_running.transition(
        WorkState.COMPLETED,
        status_detail="done",
        result={"ok": True},
    )
    store.save(older_completed, expected_version=older_running.version)

    item = WorkItem(
        request="Acquire TV media control",
        work_type=WorkType.RESEARCH,
        source_session_id="session-tv",
        source_turn_id="turn-tv",
    )
    store.create(item)
    running = item.transition(
        WorkState.RUNNING,
        status_detail="acquiring capability",
    )
    running = store.save(running, expected_version=item.version)
    failed = running.transition(
        WorkState.FAILED,
        status_detail="ChatGPT Plan allowance is temporarily unavailable",
    )
    failed = store.save(failed, expected_version=running.version)

    runtime = object.__new__(WorkRuntime)
    runtime.store = store
    runtime.orchestrator = SimpleNamespace(list_active=lambda *, limit: ())

    conversation = ConversationSession()
    conversation.start()
    tools = WorkAgentTools(runtime, conversation)

    result = await tools.list_background_work(None)  # type: ignore[arg-type]

    assert result["ok"] is True
    assert result["work"] == []
    recent = result["recent_terminal_work"]
    assert isinstance(recent, dict)
    assert recent["work_id"] == failed.work_id
    assert recent["state"] == "failed"
    assert recent["status"] == "ChatGPT Plan allowance is temporarily unavailable"
    assert "no work is currently active" in str(result["truth_note"])
