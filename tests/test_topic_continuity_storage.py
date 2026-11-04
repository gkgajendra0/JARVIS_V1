"""Continuation reads retain provenance and require a separate trusted lease."""

import sqlite3
from contextlib import contextmanager

import pytest
import pytest_asyncio

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_checkpoint import EncryptedTopicCheckpointStore
from jarvis.memory.conversation_semantics import (
    SemanticAction,
    SemanticContextEngine,
    SemanticProposal,
)
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.worker import SerialConnectionWorker


@pytest_asyncio.fixture
async def checkpoint(tmp_path):
    path = tmp_path / "fixture.db"
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner().apply(connection)
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="topic-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="topic-read"
    )
    store = EncryptedTopicCheckpointStore(writer=writer, reader=reader)
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    state = SemanticContextEngine()
    state.apply(
        conversation,
        turn,
        [
            SemanticProposal(
                SemanticAction.TOPIC, turn.text, 0, len(turn.text), value="Nepal trip"
            )
        ],
        epoch=state.epoch,
    )
    await store.save(
        conversation,
        turn,
        state.snapshot(),
        authorize_write=lambda: True,
        admit_snapshot=lambda *_: True,
        expected_plan_epoch=0,
    )
    try:
        yield store, state.snapshot()
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_continuation_read_requires_live_lease_without_weakening_named_read(
    checkpoint,
):
    store, _ = checkpoint
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "My vehicle is a Jimny")
    with pytest.raises(PermissionError, match="does not name"):
        await store.read_named_snapshot(
            conversation, turn, title="Nepal trip", authorize_read=lambda: True
        )
    with pytest.raises(PermissionError):
        await store.read_continuation_snapshot(
            conversation,
            turn,
            title="Nepal trip",
            authorize_read=lambda: True,
            authorize_continuation=lambda: False,
        )
    snapshot = await store.read_continuation_snapshot(
        conversation,
        turn,
        title="Nepal trip",
        authorize_read=lambda: True,
        authorize_continuation=lambda: True,
    )
    assert snapshot.title == "Nepal trip"


@pytest.mark.asyncio
async def test_restored_snapshot_can_receive_new_grounded_updates(checkpoint):
    _, snapshot = checkpoint
    conversation = ConversationSession()
    conversation.start()
    state = SemanticContextEngine()
    state.restore(snapshot, epoch=state.epoch, authorize_restore=lambda: True)
    turn = conversation.accept_turn(ConversationRole.USER, "My vehicle is a Jimny")
    state.apply(
        conversation,
        turn,
        [
            SemanticProposal(
                SemanticAction.CONSTRAINT,
                turn.text,
                0,
                len(turn.text),
                value="Jimny",
                key="vehicle",
            )
        ],
        epoch=state.epoch,
    )
    assert state.snapshot().title == "Nepal trip"
    assert dict(state.snapshot().constraints)["vehicle"].value == "Jimny"
    with pytest.raises(PermissionError):
        SemanticContextEngine().restore(
            snapshot, epoch=0, authorize_restore=lambda: False
        )


@pytest.mark.asyncio
async def test_checkpoint_commit_runs_inside_caller_authority_scope(checkpoint):
    store, snapshot = checkpoint
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    active = []

    @contextmanager
    def scope():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    def admitted(*_):
        # Worker callbacks must execute under the delegated commit lock.
        import threading

        return threading.current_thread() is threading.main_thread() or bool(active)

    assert await store.save(
        conversation,
        turn,
        snapshot,
        authorize_write=lambda: True,
        admit_snapshot=admitted,
        expected_plan_epoch=0,
        commit_scope=scope,
    )
    assert not active
