"""Asynchronous semantic ingestion: no voice blocking and no revoked-state writes."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import (
    SemanticAction,
    SemanticContextEngine,
    SemanticProposal,
)
from jarvis.memory.semantic_pipeline import SemanticTurnPipeline


def topic_proposal(text: str) -> list[SemanticProposal]:
    return [
        SemanticProposal(
            action=SemanticAction.TOPIC,
            quote=text,
            start=0,
            end=len(text),
            value=text,
        )
    ]


@pytest.mark.asyncio
async def test_authorized_transient_pipeline_consumes_accepted_turn() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    binding = "owner-grant-generation-1"

    async def producer(turn):
        return topic_proposal(turn.text)

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: binding,
    )
    pipeline.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert pipeline.submit(turn)
    await pipeline.drain()
    assert state.active_topic == "Nepal trip"
    assert pipeline.status.applied == 1
    await pipeline.close()
    assert state.active_topic is None


@pytest.mark.asyncio
async def test_revocation_drops_inflight_model_result() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    started = asyncio.Event()
    proceed = asyncio.Event()
    auth = ["grant-1"]

    async def producer(turn):
        started.set()
        await proceed.wait()
        return topic_proposal(turn.text)

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: auth[0],
    )
    pipeline.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert pipeline.submit(turn)
    await asyncio.wait_for(started.wait(), timeout=2)
    pipeline.invalidate()
    auth[0] = None
    proceed.set()
    await pipeline.drain()
    assert state.snapshot() is None
    assert pipeline.status.dropped >= 1
    await pipeline.close()


@pytest.mark.asyncio
async def test_binding_rotation_invalidates_old_work() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    started = asyncio.Event()
    proceed = asyncio.Event()
    auth = ["grant-1"]

    async def producer(turn):
        if turn.text == "Nepal trip":
            started.set()
            await proceed.wait()
        return topic_proposal(turn.text)

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: auth[0],
    )
    pipeline.start()
    first = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert pipeline.submit(first)
    await asyncio.wait_for(started.wait(), timeout=2)
    auth[0] = "grant-2"
    next_turn = conversation.accept_turn(ConversationRole.USER, "Interview prep")
    assert pipeline.submit(next_turn)
    proceed.set()
    await pipeline.drain()
    assert state.active_topic == "Interview prep"
    assert pipeline.status.dropped >= 1
    await pipeline.close()


@pytest.mark.asyncio
async def test_assistant_turn_and_missing_grant_never_produce() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    calls = []

    async def producer(turn):
        calls.append(turn.turn_id)
        return topic_proposal(turn.text)

    auth = [None]
    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: auth[0],
    )
    pipeline.start()
    assistant = conversation.accept_turn(ConversationRole.ASSISTANT, "Nepal trip")
    assert not pipeline.submit(assistant)
    user = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert not pipeline.submit(user)
    await pipeline.drain()
    assert calls == []
    assert state.snapshot() is None
    await pipeline.close()


@pytest.mark.asyncio
async def test_slow_producer_times_out_without_blocking_submit() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()

    async def producer(turn):
        await asyncio.sleep(1)
        return topic_proposal(turn.text)

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: "grant-1",
        timeout_seconds=0.01,
    )
    pipeline.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert pipeline.submit(turn)
    await pipeline.drain()
    assert state.active_topic is None
    assert pipeline.status.failures == 1
    await pipeline.close()


@pytest.mark.asyncio
async def test_bounded_queue_drops_excess_work_without_blocking_voice() -> None:
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def producer(turn):
        started.set()
        await proceed.wait()
        return topic_proposal(turn.text)

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: "grant-1",
        max_pending=1,
    )
    pipeline.start()
    first = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    assert pipeline.submit(first)
    await asyncio.wait_for(started.wait(), timeout=2)
    second = conversation.accept_turn(ConversationRole.USER, "Interview prep")
    third = conversation.accept_turn(ConversationRole.USER, "Other topic")
    assert pipeline.submit(second)
    assert not pipeline.submit(third)
    proceed.set()
    await pipeline.drain()
    assert state.active_topic == "Interview prep"
    assert pipeline.status.dropped == 1
    await pipeline.close()
