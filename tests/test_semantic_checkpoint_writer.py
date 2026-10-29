"""Guarded semantic pipeline writes and forgets through canonical SQLCipher workers."""

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
from jarvis.memory.semantic_checkpoint_writer import SemanticCheckpointWriter
from jarvis.memory.semantic_pipeline import SemanticTurnPipeline
from jarvis.memory.worker import SerialConnectionWorker


def proposals_for(turn):
    text = turn.text
    def propose(action, value="", key=""):
        return SemanticProposal(
            action=action,
            quote=text,
            start=0,
            end=len(text),
            value=value,
            key=key,
        )
    if text == "Nepal trip":
        return [propose(SemanticAction.TOPIC, "Nepal trip")]
    if text == "Permits are sorted":
        return [propose(SemanticAction.CONSTRAINT, "sorted", "permits")]
    if text == "Plan the route":
        return [propose(SemanticAction.PENDING_STEP, "plan route", "route")]
    if text == "Forget Nepal trip":
        return [propose(SemanticAction.FORGET_TOPIC)]
    return []


@pytest.mark.asyncio
async def test_authorized_semantic_checkpoint_write_read_and_forget(tmp_path):
    path = tmp_path / "semantic-checkpoint.db"
    with sqlite3.connect(path) as conn:
        assert MemoryMigrationRunner().apply(conn) == 4
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="semantic-write-flow"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="semantic-read-flow"
    )
    store = EncryptedTopicCheckpointStore(writer=writer, reader=reader)
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    grant = ["valid"]

    async def producer(turn):
        return proposals_for(turn)

    checkpoint = SemanticCheckpointWriter(
        conversation=conversation,
        store=store,
        authorize_write=lambda turn: grant[0] == "valid",
        authorize_forget=lambda turn: grant[0] == "valid",
        admit_snapshot=lambda snapshot, turn: snapshot.title == "Nepal trip",
    )
    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: grant[0] if grant[0] == "valid" else None,
        on_applied=checkpoint,
        accepted_plan_epoch=lambda _turn: 0,
    )
    pipeline.start()
    try:
        for text in ("Nepal trip", "Permits are sorted", "Plan the route"):
            turn = conversation.accept_turn(ConversationRole.USER, text)
            assert pipeline.submit(turn)
            await pipeline.drain()
        query = conversation.accept_turn(
            ConversationRole.USER, "Continue Nepal trip"
        )
        snapshot = await store.read_named_snapshot(
            conversation, query, title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert snapshot is not None
        assert dict(snapshot.constraints)["permits"].value == "sorted"
        assert dict(snapshot.steps)["route"].value == "plan route"

        forget = conversation.accept_turn(
            ConversationRole.USER, "Forget Nepal trip"
        )
        assert pipeline.submit(forget)
        await pipeline.drain()
        assert state.snapshot() is None
        query = conversation.accept_turn(
            ConversationRole.USER, "Continue Nepal trip"
        )
        assert await store.read_named(
            conversation, query,
            title="Nepal trip", authorize_read=lambda: True,
        ) is None
    finally:
        await pipeline.close()
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_denied_snapshot_admission_never_creates_checkpoint(tmp_path):
    path = tmp_path / "denied-checkpoint.db"
    with sqlite3.connect(path) as conn:
        assert MemoryMigrationRunner().apply(conn) == 4
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="semantic-denied-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="semantic-denied-read"
    )
    store = EncryptedTopicCheckpointStore(writer=writer, reader=reader)
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()

    async def producer(turn):
        return proposals_for(turn)

    checkpoint = SemanticCheckpointWriter(
        conversation=conversation,
        store=store,
        authorize_write=lambda turn: True,
        authorize_forget=lambda turn: True,
        admit_snapshot=lambda *_: False,
    )
    pipeline = SemanticTurnPipeline(
        conversation=conversation,
        state=state,
        producer=producer,
        authorization_binding=lambda: "owner-grant",
        on_applied=checkpoint,
        accepted_plan_epoch=lambda _turn: 0,
    )
    pipeline.start()
    try:
        turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
        assert pipeline.submit(turn)
        await pipeline.drain()
        assert pipeline.status.failures == 1
        # Denied durable persistence revokes the associated transient context.
        assert state.snapshot() is None
        query = conversation.accept_turn(
            ConversationRole.USER, "Continue Nepal trip"
        )
        assert await store.read_named(
            conversation, query, title="Nepal trip",
            authorize_read=lambda: True,
        ) is None
    finally:
        await pipeline.close()
        await writer.close()
        await reader.close()



@pytest.mark.asyncio
async def test_stale_forget_hook_must_not_claim_newer_checkpoint_was_deleted(tmp_path):
    from dataclasses import replace
    from datetime import timedelta

    path = tmp_path / "forget-race.db"
    with sqlite3.connect(path) as connection:
        assert MemoryMigrationRunner().apply(connection) == 4
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="forget-race-writer"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="forget-race-reader"
    )
    store = EncryptedTopicCheckpointStore(writer=writer, reader=reader)
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    checkpoint_writer = SemanticCheckpointWriter(
        conversation=conversation,
        store=store,
        authorize_write=lambda _turn: True,
        authorize_forget=lambda _turn: True,
        admit_snapshot=lambda *_: True,
    )
    try:
        started = conversation.accept_turn(
            ConversationRole.USER, "Nepal trip"
        )
        state.apply(
            conversation,
            started,
            proposals_for(started),
            epoch=state.epoch,
        )
        snapshot = state.snapshot()
        assert snapshot is not None
        await store.save(
            conversation,
            started,
            snapshot,
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True,
            expected_plan_epoch=0,
        )
        forgot = conversation.accept_turn(
            ConversationRole.USER, "Forget Nepal trip"
        )
        # ASR/transcript delivery was delayed; this accepted source is older
        # than the checkpoint already written for the current topic.
        stale = replace(
            forgot, accepted_at=started.accepted_at - timedelta(seconds=1)
        )
        conversation._turns[-1] = stale
        with pytest.raises(PermissionError, match="newer checkpoint survived"):
            await checkpoint_writer(
                stale,
                tuple(proposals_for(stale)),
                snapshot,
                None,
                0,
            )
        assert await store.current_fingerprint("Nepal trip") is not None
    finally:
        await writer.close()
        await reader.close()
