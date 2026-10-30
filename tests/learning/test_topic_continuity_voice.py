"""The voice tool must return actual stored context before a protected answer."""

import asyncio
from types import SimpleNamespace

import pytest
from test_topic_continuity import coordinator, patch, wake

from jarvis.conversation import ConversationRole
from jarvis.voice.personal_context import (
    PersonalContextAgentTools,
    PersonalContextSession,
)


def personal(learning, service, conversation):
    session = PersonalContextSession(
        conversation=conversation,
        retrieval=object(),
        authority=SimpleNamespace(invalidate_personal_context=lambda _: None),
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
        topic_checkpoints=service.store,
        topic_continuity=service,
    )
    if conversation.turns and conversation.turns[-1].role is ConversationRole.USER:
        session.observe_turn(conversation.turns[-1])
    return session


@pytest.mark.asyncio
async def test_blocking_voice_tool_returns_nepal_and_jimny_across_sleep(
    learning, clock
):
    service = coordinator(learning, clock)
    for text, proposals in [
        (
            "I am planning a Nepal trip",
            [patch("I am planning a Nepal trip", "topic", "Nepal trip")],
        ),
        (
            "My vehicle is a Jimny",
            [patch("My vehicle is a Jimny", "constraint", "Jimny", "vehicle")],
        ),
    ]:
        conversation = wake()
        conversation.accept_turn(ConversationRole.USER, text)
        session = personal(learning, service, conversation)
        try:
            result = await session.prepare_topic(
                {"topic_hint": "", "proposals": proposals}
            )
            assert result["status"] == "ready"
            assert result["context"]["title"] == "Nepal trip"
            assert await session.allow_audio()
        finally:
            session.close()
            conversation.close()
    assert result["context"]["constraints"]["vehicle"] == "Jimny"


@pytest.mark.asyncio
async def test_tool_waits_for_current_transcript_not_previous_turn(learning, clock):
    service = coordinator(learning, clock)
    conversation = wake()
    session = personal(learning, service, conversation)
    conversation.begin_user_activity()
    text = "Nepal trip"
    task = asyncio.create_task(
        session.prepare_topic(
            {"topic_hint": "", "proposals": [patch(text, "topic", text)]}
        )
    )
    await asyncio.sleep(0)
    assert not task.done()
    turn = conversation.accept_turn(ConversationRole.USER, text)
    session.observe_turn(turn)
    try:
        assert (await task)["context"]["title"] == "Nepal trip"
    finally:
        session.close()


@pytest.mark.asyncio
async def test_topic_revision_change_blocks_voice_audio(learning, clock):
    service = coordinator(learning, clock)
    conversation = wake()
    text = "Nepal trip"
    conversation.accept_turn(ConversationRole.USER, text)
    session = personal(learning, service, conversation)
    try:
        assert (
            await session.prepare_topic(
                {"topic_hint": "", "proposals": [patch(text, "topic", text)]}
            )
        )["status"] == "ready"
        await learning.writer.run(
            lambda c: (
                c.execute("DELETE FROM conversation_topic_checkpoint"),
                c.commit(),
            )
        )
        assert not await session.allow_audio()
    finally:
        session.close()


@pytest.mark.asyncio
async def test_real_voice_agent_exposes_blocking_topic_tool_only_when_configured(
    learning, clock
):
    from jarvis.voice.agent import JarvisVoiceAgent

    service = coordinator(learning, clock)
    session = personal(learning, service, wake())
    try:
        tools = PersonalContextAgentTools(session).tools
        assert "prepare_conversation_topic" in {t.id for t in tools}
        agent = JarvisVoiceAgent(tools=tools, personal_learning_mode="apply")
        assert "prepare_conversation_topic" in agent.instructions
    finally:
        session.close()


@pytest.mark.asyncio
async def test_new_activity_never_uses_a_previous_turn_without_activity_metadata(
    learning, clock
):
    service = coordinator(learning, clock)
    conversation = wake()
    conversation.accept_turn(ConversationRole.USER, "Old request")
    conversation.begin_user_activity()
    session = personal(learning, service, conversation)
    text = "Nepal trip"
    task = asyncio.create_task(
        session.prepare_topic(
            {"topic_hint": "", "proposals": [patch(text, "topic", text)]}
        )
    )
    await asyncio.sleep(0.05)
    try:
        assert not task.done()
        turn = conversation.accept_turn(ConversationRole.USER, text)
        session.observe_turn(turn)
        assert (await task)["status"] == "ready"
    finally:
        session.close()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_topic_tool_result_crosses_provider_guard_only_while_authorized(
    learning, clock, authority_parts
):
    import json

    from livekit.agents import llm
    from tests.gemini_fallback.live_helpers import ProviderModel

    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )

    service = coordinator(learning, clock)
    # A first wake saves the trip. Its personal response session is retired.
    first = wake()
    first.accept_turn(ConversationRole.USER, "Nepal trip")
    first_personal = personal(learning, service, first)
    await first_personal.prepare_topic(
        {"topic_hint": "", "proposals": [patch("Nepal trip", "topic", "Nepal trip")]}
    )
    first_personal.close()
    first.close()
    second = wake()
    text = "My vehicle is a Jimny"
    second.accept_turn(ConversationRole.USER, text)
    session = personal(learning, service, second)
    provider = ProviderModel()
    state = GeminiTransportState(
        epoch=0, current_epoch=lambda: 0, authorize=session.validate_transport_restore
    )
    transport = GuardedGeminiRealtimeModel(provider, state).session()
    try:
        result = await session.prepare_topic(
            {
                "topic_hint": "",
                "proposals": [patch(text, "constraint", "Jimny", "vehicle")],
            }
        )
        context = llm.ChatContext.empty()
        context.items.append(
            llm.FunctionCall(
                call_id="topic-1", name="prepare_conversation_topic", arguments="{}"
            )
        )
        context.items.append(
            llm.FunctionCallOutput(
                call_id="topic-1",
                name="prepare_conversation_topic",
                output=json.dumps(result),
                is_error=False,
            )
        )
        await transport.update_chat_ctx(context)
        outputs = [
            item.output
            for item in provider.sessions[0].chat_ctx.items
            if item.type == "function_call_output"
        ]
        payload = json.loads(outputs[0])
        assert payload["context"]["title"] == "Nepal trip"
        assert payload["context"]["constraints"]["vehicle"] == "Jimny"
        authority_parts.windows.lock_unlock()
        with pytest.raises(llm.RealtimeError):
            await transport.update_chat_ctx(context)
        assert not await session.allow_audio()
    finally:
        session.close()
        await transport.aclose()


@pytest.mark.asyncio
async def test_queued_old_tool_does_not_rebind_to_new_canonical_request(
    learning, clock
):
    service = coordinator(learning, clock)
    from test_topic_continuity import update

    await update(
        service, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    conversation = wake()
    conversation.begin_user_activity()
    conversation.accept_turn(ConversationRole.USER, "Continue Nepal trip")
    session = personal(learning, service, conversation)
    await session._context_lock.acquire()
    task = asyncio.create_task(
        session.prepare_topic({"topic_hint": "Nepal", "proposals": []})
    )
    await asyncio.sleep(0.05)
    conversation.begin_user_activity()
    newer = conversation.accept_turn(
        ConversationRole.USER, "Do not continue Nepal trip"
    )
    session.observe_turn(newer)
    session._context_lock.release()
    try:
        assert await task == {"status": "denied"}
    finally:
        session.close()


@pytest.mark.asyncio
async def test_suppression_reenable_cannot_reauthorize_a_previously_accepted_source(
    learning, clock
):
    service = coordinator(learning, clock)
    epoch = [0]
    service._epoch = lambda _: epoch[0]
    conversation = wake()
    text = "Nepal trip"
    turn = conversation.accept_turn(ConversationRole.USER, text)
    session = personal(learning, service, conversation)
    session.observe_turn(turn)
    epoch[0] = 2
    await learning.writer.run(
        lambda c: (
            c.execute(
                "INSERT INTO personal_learning_suppression(category,suppressed,epoch,updated_at) VALUES ('plan',0,2,'2026-10-30T00:00:00+00:00')"
            ),
            c.commit(),
        )
    )
    try:
        result = await session.prepare_topic(
            {"topic_hint": "", "proposals": [patch(text, "topic", text)]}
        )
        assert result == {"status": "denied"}
    finally:
        session.close()
