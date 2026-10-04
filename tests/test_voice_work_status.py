from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice import work_tools as work_tools_module
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


@pytest.mark.asyncio
async def test_status_reports_active_parent_change_after_child_work_completed(
    tmp_path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = WorkItem(
        request="Acquire TV media control",
        work_type=WorkType.RESEARCH,
        source_session_id="session-tv",
        source_turn_id="turn-tv",
    )
    store.create(item)
    running = store.save(
        item.transition(WorkState.RUNNING, status_detail="researching"),
        expected_version=item.version,
    )
    completed = store.save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="research complete",
            result={"ok": True},
        ),
        expected_version=running.version,
    )

    change = SimpleNamespace(
        change_id="change_tv",
        state=SimpleNamespace(value="waiting_owner_approval"),
        request="Acquire TV media control",
    )
    stage = SimpleNamespace(stage_key="research", work_id=completed.work_id)
    change_store = SimpleNamespace(
        active_ids=lambda: ("change_tv",),
        require=lambda change_id: change,
        list_stages=lambda change_id: (stage,),
        work=store,
    )

    runtime = object.__new__(WorkRuntime)
    runtime.store = store
    runtime.orchestrator = SimpleNamespace(list_active=lambda *, limit: ())
    runtime.changes = SimpleNamespace(store=change_store)
    runtime._owner_work_focus_id = None

    conversation = ConversationSession()
    conversation.start()
    tools = WorkAgentTools(runtime, conversation)

    result = await tools.list_background_work(None)  # type: ignore[arg-type]

    assert result["work"] == []
    assert "recent_terminal_work" not in result
    changes = result["active_engineering_changes"]
    assert isinstance(changes, list)
    assert changes == [
        {
            "change_id": "change_tv",
            "state": "waiting_owner_approval",
            "request": "Acquire TV media control",
            "pending_owner_approval": True,
            "stages": [
                {
                    "stage": "research",
                    "work_id": completed.work_id,
                    "work_state": "completed",
                }
            ],
        }
    ]
    assert "parent engineering work is still active" in str(result["truth_note"])


@pytest.mark.asyncio
async def test_status_focus_survives_new_voice_session_and_binds_deictic_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")

    older = WorkItem(
        request="Older TV capability attempt",
        work_type=WorkType.RESEARCH,
        source_session_id="session-old",
        source_turn_id="turn-old",
    )
    store.create(older)
    older_running = older.transition(WorkState.RUNNING, status_detail="working")
    older_running = store.save(older_running, expected_version=older.version)
    older_failed = older_running.transition(
        WorkState.FAILED,
        status_detail="older failure",
    )
    store.save(older_failed, expected_version=older_running.version)

    target = WorkItem(
        request="I want to watch Transporter on my TV.",
        work_type=WorkType.RESEARCH,
        source_session_id="session-target",
        source_turn_id="turn-target",
    )
    store.create(target)
    target_running = target.transition(WorkState.RUNNING, status_detail="researching")
    target_running = store.save(target_running, expected_version=target.version)
    target_failed = target_running.transition(
        WorkState.FAILED,
        status_detail="ChatGPT Plan allowance exhausted",
    )
    target_failed = store.save(target_failed, expected_version=target_running.version)

    runtime = object.__new__(WorkRuntime)
    runtime.store = store
    runtime.orchestrator = SimpleNamespace(list_active=lambda *, limit: ())
    runtime._owner_work_focus_id = None

    first_conversation = ConversationSession()
    first_conversation.start()
    first_tools = WorkAgentTools(runtime, first_conversation)

    status = await first_tools.list_background_work(None)  # type: ignore[arg-type]

    assert status["recent_terminal_work"]["work_id"] == target_failed.work_id
    assert runtime.owner_work_focus_id == target_failed.work_id

    calls: list[str | None] = []

    def retry_failed_work(
        work_id,
        *,
        owner_request,
        source_session_id,
        source_turn_id,
    ):
        del owner_request, source_session_id, source_turn_id
        calls.append(work_id)
        return target_failed

    runtime.retry_failed_work = retry_failed_work  # type: ignore[method-assign]
    monkeypatch.setattr(
        work_tools_module,
        "_public_work",
        lambda item, _runtime: {
            "work_id": item.work_id,
            "state": "retrying",
        },
    )

    second_conversation = ConversationSession()
    second_conversation.start()
    second_conversation.accept_turn(
        ConversationRole.USER,
        "Retry that same TV capability task.",
    )
    second_tools = WorkAgentTools(runtime, second_conversation)

    result = await second_tools.retry_failed_background_work(
        None,  # type: ignore[arg-type]
    )

    assert calls == [target_failed.work_id]
    assert result["ok"] is True
    assert result["work_id"] == target_failed.work_id


@pytest.mark.asyncio
async def test_deictic_retry_rejects_model_supplied_id_that_conflicts_with_focus(
    tmp_path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    focused = WorkItem(
        request="Fresh TV capability task",
        work_type=WorkType.RESEARCH,
        source_session_id="session-focused",
        source_turn_id="turn-focused",
    )
    store.create(focused)
    focused_running = focused.transition(WorkState.RUNNING, status_detail="working")
    focused_running = store.save(focused_running, expected_version=focused.version)
    focused_failed = focused_running.transition(
        WorkState.FAILED,
        status_detail="failed",
    )
    store.save(focused_failed, expected_version=focused_running.version)

    stale = WorkItem(
        request="Older TV task",
        work_type=WorkType.RESEARCH,
        source_session_id="session-stale",
        source_turn_id="turn-stale",
    )
    store.create(stale)
    stale_running = stale.transition(WorkState.RUNNING, status_detail="working")
    stale_running = store.save(stale_running, expected_version=stale.version)
    stale_failed = stale_running.transition(WorkState.FAILED, status_detail="failed")
    store.save(stale_failed, expected_version=stale_running.version)

    runtime = object.__new__(WorkRuntime)
    runtime.store = store
    runtime._owner_work_focus_id = focused.work_id

    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(
        ConversationRole.USER,
        "Retry that same task.",
    )
    tools = WorkAgentTools(runtime, conversation)

    result = await tools.retry_failed_background_work(
        None,  # type: ignore[arg-type]
        work_id=stale.work_id,
    )

    assert result == {
        "ok": False,
        "status": "work_reference_target_mismatch",
        "work_id": stale.work_id,
        "focused_work_id": focused.work_id,
        "reason": (
            "the requested retry target conflicts with the canonical task "
            "most recently surfaced to the owner"
        ),
    }
