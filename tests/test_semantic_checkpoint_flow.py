"""Simulated semantic-to-encrypted-checkpoint continuation, not a voice test."""

from __future__ import annotations

import sqlite3

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_checkpoint import EncryptedTopicCheckpointStore
from jarvis.memory.conversation_semantics import (
    SemanticAction,
    SemanticContextEngine,
    SemanticProposal,
)
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.semantic_pipeline import SemanticTurnPipeline
from jarvis.memory.worker import SerialConnectionWorker


@pytest.mark.asyncio
async def test_nepal_state_restarts_resumes_only_on_topic_and_forgets(tmp_path):
    location = tmp_path / "encrypted-worker-fixture.sqlite"
    with sqlite3.connect(location) as setup:
        assert MemoryMigrationRunner().apply(setup) == 4

    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(location), thread_name="checkpoint-flow-writer"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(location), thread_name="checkpoint-flow-reader"
    )
    storage = EncryptedTopicCheckpointStore(writer=writer, reader=reader)
    conversation = ConversationSession()
    conversation.start()
    engine = SemanticContextEngine()

    def patch(turn, action, *, key="", value=""):
        return SemanticProposal(
            action=action,
            quote=turn.text,
            start=0,
            end=len(turn.text),
            key=key,
            value=value,
        )

    async def proposals(turn):
        if "discuss my Nepal trip" in turn.text:
            return [patch(turn, SemanticAction.TOPIC, value="Nepal trip")]
        if "permits and documents" in turn.text:
            return [
                patch(turn, SemanticAction.CONSTRAINT, key="permits", value="sorted"),
                patch(turn, SemanticAction.CONSTRAINT, key="documents", value="sorted"),
            ]
        if "Budget" in turn.text:
            return [
                patch(
                    turn,
                    SemanticAction.CONSTRAINT,
                    key="budget",
                    value="unrestricted",
                )
            ]
        if "route" in turn.text:
            return [
                patch(
                    turn,
                    SemanticAction.PENDING_STEP,
                    key="route",
                    value="plan Nepal route",
                )
            ]
        return []

    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=engine,
        producer=proposals,
        authorization_binding=lambda: "active-owner-test-epoch",
    )
    pipeline.start()
    try:
        for sentence in [
            "Let's discuss my Nepal trip",
            "My permits and documents are sorted",
            "Budget isn't a constraint",
            "Now plan the route",
        ]:
            accepted = conversation.accept_turn(ConversationRole.USER, sentence)
            assert pipeline.submit(accepted)
            await pipeline.drain()

        topic = engine.snapshot()
        assert topic is not None
        assert dict(topic.constraints)["permits"].value == "sorted"
        assert dict(topic.constraints)["budget"].value == "unrestricted"
        assert not dict(topic.steps)["route"].completed
        assert await storage.save(
            conversation, accepted, topic, authorize_write=lambda: True, admit_snapshot=lambda *_: True
        )

        await pipeline.close()
        conversation.close()

        resumed = ConversationSession()
        resumed.start()
        unscoped = resumed.accept_turn(ConversationRole.USER, "Okay continue")
        with pytest.raises(PermissionError, match="does not name"):
            await storage.read_named(
                resumed,
                unscoped,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
        named = resumed.accept_turn(
            ConversationRole.USER, "Continue with my Nepal trip"
        )
        checkpoint = await storage.read_named(
            resumed,
            named,
            title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert checkpoint is not None
        assert checkpoint["constraints"] == {
            "budget": "unrestricted",
            "documents": "sorted",
            "permits": "sorted",
        }
        assert checkpoint["steps"]["route"]["completed"] is False

        forgotten = resumed.accept_turn(ConversationRole.USER, "Forget Nepal trip")
        assert await storage.forget(
            resumed,
            forgotten,
            title="Nepal trip",
            authorize_forget=lambda: True,
        )
        after_forget = resumed.accept_turn(ConversationRole.USER, "Continue Nepal trip")
        assert (
            await storage.read_named(
                resumed,
                after_forget,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
            is None
        )

    finally:
        await pipeline.close()
        await writer.close()
        await reader.close()
