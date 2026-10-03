from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice import canonical_active_speaker_runtime as canonical_runtime_module
from jarvis.voice import work_tools as work_tools_module
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.runtime import VoiceRuntimeState
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.models import WorkState
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
async def test_bound_owner_input_cancel_rejects_different_work_id() -> None:
    runtime = object.__new__(WorkRuntime)
    conversation = _conversation_with_owner_turn("Cancel this task")
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_owner_input_work_id="work-tv",
    )

    result = await tools.cancel_background_work(
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
async def test_bound_owner_input_can_cancel_exact_work_and_close_interaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object.__new__(WorkRuntime)
    cancelled = SimpleNamespace(work_id="work-tv")
    calls: list[str] = []

    runtime.orchestrator = SimpleNamespace(
        cancel=lambda work_id: calls.append(work_id) or cancelled
    )
    monkeypatch.setattr(
        work_tools_module,
        "_public_work",
        lambda item, _runtime: {"work_id": item.work_id},
    )

    resolved: list[str] = []
    conversation = _conversation_with_owner_turn("Cancel this task")
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_owner_input_work_id="work-tv",
        on_bound_owner_input_submitted=lambda item: resolved.append(item.work_id),
    )

    result = await tools.cancel_background_work(None)  # type: ignore[arg-type]

    assert calls == ["work-tv"]
    assert resolved == ["work-tv"]
    assert result == {
        "ok": True,
        "status": "cancelled",
        "work_id": "work-tv",
    }


@pytest.mark.asyncio
async def test_owner_input_resolution_closes_session_before_exact_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object.__new__(WorkRuntime)
    controller = object.__new__(CanonicalActiveSpeakerRuntimeController)
    controller._work_runtime = runtime
    controller._shutdown = asyncio.Event()
    controller._timeout_handle = None
    controller._active_end = None
    controller._state = VoiceRuntimeState.IDLE
    controller.audio = SimpleNamespace(output=object())

    class FakeBoundTools:
        def __init__(
            self,
            runtime,
            conversation,
            *,
            bound_owner_input_work_id=None,
            on_bound_owner_input_submitted=None,
            **kwargs,
        ) -> None:
            del runtime, conversation, kwargs
            assert bound_owner_input_work_id == "work-tv"
            self._callback = on_bound_owner_input_submitted

        async def continue_background_work(self, context=None):
            del context
            assert self._callback is not None
            self._callback(SimpleNamespace(state=WorkState.RUNNING))
            return {"ok": True}

        async def cancel_background_work(self, context=None):
            del context
            return {"ok": True}

        async def list_background_work(self, context=None):
            del context
            return {"ok": True, "work": []}

        async def list_recent_background_work(self, context=None):
            del context
            return {"ok": True, "work": []}

        async def get_background_work_status(self, context=None, work_id=None):
            del context, work_id
            return {"ok": True}

    monkeypatch.setattr(
        canonical_runtime_module,
        "WorkAgentTools",
        FakeBoundTools,
    )

    async def fake_run_one_session_owned(**kwargs) -> None:
        conversation = ConversationSession()
        conversation.start()
        tools = kwargs["session_tool_factory"](conversation)
        await tools[0](None)
        assert kwargs["completion_event"].is_set() is True

    spoken: list[str] = []

    async def fake_speak(output, *, instructions: str, label: str) -> None:
        del output
        spoken.append(f"{label}:{instructions}")

    controller._run_one_session_owned = fake_run_one_session_owned
    controller._speak_ephemeral_realtime_message = fake_speak

    answered = await controller._run_owner_input_interaction(
        work_id="work-tv",
        question="May I revise the capability architecture?",
    )

    assert answered is True
    assert spoken == [
        (
            "owner input acknowledgement:Say exactly: Your response was recorded. "
            "I will continue the waiting work and ask separately if another approval "
            "is required."
        )
    ]


@pytest.mark.asyncio
async def test_owner_input_spoken_prompt_redacts_internal_entity_identity() -> None:
    runtime = object.__new__(WorkRuntime)
    controller = object.__new__(CanonicalActiveSpeakerRuntimeController)
    controller._work_runtime = runtime
    controller._shutdown = asyncio.Event()
    controller._timeout_handle = None
    controller._active_end = None
    controller._state = VoiceRuntimeState.IDLE

    captured: dict[str, object] = {}

    async def fake_run_one_session_owned(**kwargs) -> None:
        captured.update(kwargs)

    controller._run_one_session_owned = fake_run_one_session_owned

    answered = await controller._run_owner_input_interaction(
        work_id="work-tv",
        question=(
            "Do you approve the target-bound adapter for entity 80185cc24a9625821018?"
        ),
    )

    assert answered is False
    instructions = str(captured["initial_instructions"])
    assert "80185cc24a9625821018" not in instructions
    assert "the target device or service" in instructions


@pytest.mark.asyncio
async def test_owner_input_interaction_builds_exact_bound_conversation() -> None:
    runtime = object.__new__(WorkRuntime)
    controller = object.__new__(CanonicalActiveSpeakerRuntimeController)
    controller._work_runtime = runtime
    controller._shutdown = asyncio.Event()
    controller._timeout_handle = None
    controller._active_end = None
    controller._state = VoiceRuntimeState.IDLE

    captured: dict[str, object] = {}

    async def fake_run_one_session_owned(**kwargs) -> None:
        captured.update(kwargs)
        conversation = ConversationSession()
        conversation.start()
        tool_factory = kwargs["session_tool_factory"]
        tools = tool_factory(conversation)
        assert len(tools) == 5
        bound_instances = [tool._instance for tool in tools]
        assert all(
            instance._bound_owner_input_work_id == "work-tv"
            for instance in bound_instances
        )
        assert all(
            callable(instance._on_bound_owner_input_submitted)
            for instance in bound_instances
        )
        tool_names = {tool.__name__ for tool in tools}
        assert {
            "continue_background_work",
            "cancel_background_work",
            "list_background_work",
            "list_recent_background_work",
            "get_background_work_status",
        } == tool_names

    controller._run_one_session_owned = fake_run_one_session_owned

    answered = await controller._run_owner_input_interaction(
        work_id="work-tv",
        question="Which platform: VIDAA, Roku, or Android TV?",
    )

    assert answered is False
    assert captured["initial_prompt_label"] == "owner input prompt"
    assert "does not need to say the wake word" in str(captured["initial_instructions"])
    assert "VIDAA, Roku, or Android TV" in str(captured["initial_instructions"])
    assert "cancel or stop this exact pending task" in str(
        captured["initial_instructions"]
    )
    assert "read-only background status tools" in str(captured["initial_instructions"])
    assert callable(captured["completion_predicate"])
    assert captured["completion_label"] == "owner input for work-tv"
