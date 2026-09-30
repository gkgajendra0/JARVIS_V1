from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice import work_tools as work_tools_module
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.runtime import WorkRuntime


def _conversation_with_owner_turn(text: str) -> ConversationSession:
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return conversation


@pytest.mark.asyncio
async def test_bound_owner_input_rejects_different_work_id() -> None:
    runtime = object.__new__(WorkRuntime)
    conversation = _conversation_with_owner_turn("VIDAA")
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_owner_input_work_id="work-tv",
    )

    result = await tools.continue_background_work(
        None,  # type: ignore[arg-type]
        work_id="work-other",
    )

    assert result == {
        "ok": False,
        "status": "owner_input_target_mismatch",
        "work_id": "work-other",
        "bound_work_id": "work-tv",
    }


@pytest.mark.asyncio
async def test_bound_owner_input_uses_exact_work_and_signals_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object.__new__(WorkRuntime)
    calls: list[tuple[str | None, str]] = []
    waiting = SimpleNamespace(work_id="work-tv")

    def submit_owner_input(work_id: str | None, response: str):
        calls.append((work_id, response))
        return waiting

    runtime.submit_owner_input = submit_owner_input  # type: ignore[method-assign]
    monkeypatch.setattr(
        work_tools_module,
        "_public_work",
        lambda item, _runtime: {"work_id": item.work_id},
    )

    submitted: list[str] = []
    conversation = _conversation_with_owner_turn("It's wider.")
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_owner_input_work_id="work-tv",
        on_bound_owner_input_submitted=lambda item: submitted.append(item.work_id),
    )

    result = await tools.continue_background_work(None)  # type: ignore[arg-type]

    assert calls == [("work-tv", "It's wider.")]
    assert submitted == ["work-tv"]
    assert result["ok"] is True
    assert result["status"] == "owner_input_submitted"
    assert result["work_id"] == "work-tv"
    assert result["canonical_user_turn_id"] == conversation.turns[-1].turn_id


@pytest.mark.asyncio
async def test_owner_input_interaction_builds_exact_bound_conversation() -> None:
    runtime = object.__new__(WorkRuntime)
    controller = object.__new__(
        __import__(
            "jarvis.voice.canonical_active_speaker_runtime",
            fromlist=["CanonicalActiveSpeakerRuntimeController"],
        ).CanonicalActiveSpeakerRuntimeController
    )
    controller._work_runtime = runtime
    controller._shutdown = __import__("asyncio").Event()
    controller._timeout_handle = None
    controller._active_end = None
    controller._state = __import__(
        "jarvis.voice.runtime",
        fromlist=["VoiceRuntimeState"],
    ).VoiceRuntimeState.IDLE

    captured: dict[str, object] = {}

    async def fake_run_one_session_owned(**kwargs) -> None:
        captured.update(kwargs)
        conversation = ConversationSession()
        conversation.start()
        tool_factory = kwargs["session_tool_factory"]
        tools = tool_factory(conversation)
        assert len(tools) == 1
        tool = tools[0]
        bound_instance = getattr(tool, "_instance")
        assert bound_instance._bound_owner_input_work_id == "work-tv"
        assert callable(bound_instance._on_bound_owner_input_submitted)

    controller._run_one_session_owned = fake_run_one_session_owned

    answered = await controller._run_owner_input_interaction(
        work_id="work-tv",
        question="Which platform: VIDAA, Roku, or Android TV?",
    )

    assert answered is False
    assert captured["initial_prompt_label"] == "owner input prompt"
    assert "does not need to say the wake word" in str(captured["initial_instructions"])
    assert "VIDAA, Roku, or Android TV" in str(captured["initial_instructions"])
    assert callable(captured["completion_predicate"])
    assert captured["completion_label"] == "owner input for work-tv"
