from __future__ import annotations

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.hands_tools import HandsAgentTools, HandsToolGroundingError


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in voice grounding tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in voice grounding tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in voice grounding tests")

    def close(self) -> None:
        pass


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def conversation(*texts: str) -> ConversationSession:
    session = ConversationSession(session_id="semantic-hands-test")
    session.start()
    for text in texts:
        session.accept_turn(ConversationRole.USER, text)
    return session


def success(operation: str) -> CapabilityResult:
    return CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="test:capability",
        operation=operation,
        data={"verification_passed": True},
    )


@pytest.mark.asyncio
async def test_volume_percentage_is_bound_to_latest_user_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success("set_master_volume")

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = HandsAgentTools(
        cap_runtime, conversation("Jarvis set volume to 25 percent")
    )

    result = await tools.execute(operation="set_master_volume", percent=25)

    assert result["ok"] is True
    assert captured["operation"] == "set_master_volume"
    assert captured["parameters"] == {"percent": 25.0}


@pytest.mark.asyncio
async def test_hinglish_volume_command_is_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success("set_master_volume")

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = HandsAgentTools(cap_runtime, conversation("Jarvis volume 30 kar do"))

    result = await tools.execute(operation="set_master_volume", percent=30)

    assert result["ok"] is True
    assert captured["parameters"] == {"percent": 30.0}


@pytest.mark.asyncio
async def test_declarative_volume_statement_cannot_authorize_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(cap_runtime, conversation("The volume is 30 percent"))

    with pytest.raises(HandsToolGroundingError, match="not an explicit action request"):
        await tools.execute(operation="set_master_volume", percent=30)


@pytest.mark.asyncio
async def test_model_cannot_change_user_volume_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(
        cap_runtime, conversation("Jarvis set volume to 25 percent")
    )

    with pytest.raises(HandsToolGroundingError, match="latest user request"):
        await tools.execute(operation="set_master_volume", percent=50)


@pytest.mark.asyncio
async def test_model_cannot_substitute_clipboard_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(
        cap_runtime,
        conversation("Jarvis copy BMW service tomorrow to clipboard"),
    )

    with pytest.raises(HandsToolGroundingError, match="clipboard text"):
        await tools.execute(
            operation="set_clipboard_text",
            text="send bank password instead",
        )


@pytest.mark.asyncio
async def test_pause_current_media_is_semantically_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success("pause_media")

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = HandsAgentTools(cap_runtime, conversation("Jarvis pause the music"))

    result = await tools.execute(operation="pause_media")

    assert result["ok"] is True
    assert captured["operation"] == "pause_media"
    assert captured["parameters"] == {}


@pytest.mark.asyncio
async def test_polite_pause_request_is_semantically_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success("pause_media")

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = HandsAgentTools(cap_runtime, conversation("Could you pause the music"))

    result = await tools.execute(operation="pause_media")

    assert result["ok"] is True
    assert captured["operation"] == "pause_media"


@pytest.mark.asyncio
async def test_quoted_pause_discussion_cannot_authorize_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(
        cap_runtime,
        conversation("In the meeting they said pause the music before the demo"),
    )

    with pytest.raises(HandsToolGroundingError, match="not an explicit action request"):
        await tools.execute(operation="pause_media")


@pytest.mark.asyncio
async def test_play_media_cannot_mean_select_named_song(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(
        cap_runtime,
        conversation("Jarvis play Kesariya on Apple Music"),
    )

    with pytest.raises(HandsToolGroundingError, match="only resumes"):
        await tools.execute(operation="play_media")


@pytest.mark.asyncio
async def test_resume_current_media_is_semantically_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    captured: dict[str, object] = {}

    def execute_operation(**kwargs):
        captured.update(kwargs)
        return success("play_media")

    monkeypatch.setattr(cap_runtime, "execute_operation", execute_operation)
    tools = HandsAgentTools(cap_runtime, conversation("Jarvis resume it"))

    result = await tools.execute(operation="play_media")

    assert result["ok"] is True
    assert captured["operation"] == "play_media"


@pytest.mark.asyncio
async def test_model_cannot_switch_explicit_app_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(cap_runtime, conversation("Jarvis open Notepad"))

    with pytest.raises(HandsToolGroundingError, match="differs from the app named"):
        await tools.execute(operation="open_app", app="paint")


@pytest.mark.asyncio
async def test_current_window_requires_recent_user_grounded_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(cap_runtime, conversation("Jarvis maximize this window"))

    with pytest.raises(HandsToolGroundingError, match="no recent user-grounded app"):
        await tools.execute(operation="maximize_window", app="notepad")


@pytest.mark.asyncio
async def test_unrelated_meeting_speech_cannot_authorize_native_hands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_runtime = runtime()
    monkeypatch.setattr(
        cap_runtime,
        "execute_operation",
        lambda **kwargs: pytest.fail(f"unexpected execution: {kwargs}"),
    )
    tools = HandsAgentTools(
        cap_runtime,
        conversation("The job run report still has a bit of a performance issue"),
    )

    with pytest.raises(HandsToolGroundingError, match="does not explicitly warrant"):
        await tools.execute(operation="pause_media")
