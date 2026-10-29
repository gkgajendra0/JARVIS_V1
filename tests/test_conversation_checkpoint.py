"""Checkpoint tests use SQLite only as a fixture; production opens SQLCipher."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_checkpoint import (
    CheckpointRejected,
    EncryptedTopicCheckpointStore,
)
from jarvis.memory.conversation_semantics import (
    EvidenceStrength,
    GroundedStateValue,
    TopicSnapshot,
)
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.types import Sensitivity
from jarvis.memory.worker import SerialConnectionWorker

START = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)


def accepted(conversation, number, text):
    if not conversation.turns:
        conversation.start()
    raw = conversation.accept_turn(ConversationRole.USER, text)
    turn = replace(raw, accepted_at=START + timedelta(seconds=number))
    conversation._turns[-1] = turn
    return turn


def state_value(turn, text, sensitivity=Sensitivity.STANDARD):
    return GroundedStateValue(
        value=text,
        evidence=turn.text,
        source_turn_id=turn.turn_id,
        accepted_at=turn.accepted_at,
        sensitivity=sensitivity,
        evidence_strength=EvidenceStrength.LITERAL,
    )


def checkpoint(turn, *, budget="unrestricted", sensitivity=Sensitivity.STANDARD):
    return TopicSnapshot(
        title="Nepal trip",
        goal=state_value(turn, "plan Nepal route"),
        constraints=(("budget", state_value(turn, budget, sensitivity)),),
        steps=(("route", state_value(turn, "plan route")),),
    )


async def new_store(tmp_path):
    path = tmp_path / "checkpoint.db"
    with sqlite3.connect(path) as connection:
        assert MemoryMigrationRunner().apply(connection) == 4
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="checkpoint-test-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="checkpoint-test-read"
    )
    return EncryptedTopicCheckpointStore(writer=writer, reader=reader), writer, reader


@pytest.mark.asyncio
async def test_encrypted_worker_checkpoint_survives_new_reader_and_named_resume(
    tmp_path,
):
    store, writer, reader = await new_store(tmp_path)
    try:
        first = ConversationSession()
        source = accepted(first, 1, "Let's plan Nepal trip")
        assert await store.save(
            first, source, checkpoint(source), authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0
        )
        await writer.close()
        await reader.close()

        # A new process opens independent connections to the same persistent file.
        store, writer, reader = await new_store_existing(tmp_path)
        current = ConversationSession()
        question = accepted(current, 50, "Continue Nepal route planning")
        restored = await store.read_named(
            current,
            question,
            title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert restored is not None
        assert restored["constraints"]["budget"] == "unrestricted"
        assert restored["steps"]["route"]["completed"] is False
        assert "evidence" not in str(restored).casefold()
    finally:
        await writer.close()
        await reader.close()


async def new_store_existing(tmp_path):
    path = tmp_path / "checkpoint.db"
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="checkpoint-reopened-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="checkpoint-reopened-read"
    )
    return EncryptedTopicCheckpointStore(writer=writer, reader=reader), writer, reader


@pytest.mark.asyncio
async def test_protected_checkpoint_requires_named_topic_and_fresh_permit(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        assert await store.save(
            conversation, source, checkpoint(source), authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0
        )
        no_topic = accepted(conversation, 2, "Hey Jarvis, continue")
        with pytest.raises(CheckpointRejected, match="does not name"):
            await store.read_named(
                conversation,
                no_topic,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
        named = accepted(conversation, 3, "Continue Nepal trip")
        with pytest.raises(CheckpointRejected, match="permit denied"):
            await store.read_named(
                conversation,
                named,
                title="Nepal trip",
                authorize_read=lambda: False,
            )
        assert await store.read_named(
            conversation, named,
            title="Nepal trip", authorize_read=lambda: True,
        )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_named_forget_tombstones_stale_save_and_allows_newer_plan(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        original = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation,
            original,
            checkpoint(original),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        forget = accepted(conversation, 3, "Forget Nepal trip")
        assert await store.forget(
            conversation,
            forget,
            title="Nepal trip",
            authorize_forget=lambda: True,
        )
        query = accepted(conversation, 4, "Resume Nepal trip")
        assert (
            await store.read_named(
                conversation,
                query,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
            is None
        )
        # New accepted turn but stale speech timestamp: must not resurrect.
        stale = accepted(conversation, 2, "Nepal trip")
        with pytest.raises(CheckpointRejected, match="(older than forget|plan epoch changed)"):
            await store.save(
                conversation, stale, checkpoint(stale),
                authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
        newer = accepted(conversation, 5, "New Nepal trip plan")
        assert await store.save(
            conversation,
            newer,
            checkpoint(newer, budget="flexible"),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        named = accepted(conversation, 6, "Continue Nepal trip")
        result = await store.read_named(
            conversation,
            named,
            title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert result["constraints"]["budget"] == "flexible"
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_suppression_purges_old_checkpoints_and_reenable_cannot_resurrect(
    tmp_path,
):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        initial = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation,
            initial,
            checkpoint(initial),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        suppress = accepted(conversation, 2, "Stop remembering my plans")
        await store.purge_for_suppression(
            conversation, suppress, authorize_suppression=lambda: True
        )
        stale = accepted(conversation, 1, "Nepal trip")
        with pytest.raises(CheckpointRejected, match="older than forget"):
            await store.save(
                conversation, stale, checkpoint(stale),
                authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
        named = accepted(conversation, 3, "Nepal trip")
        assert (
            await store.read_named(
                conversation,
                named,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
            is None
        )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_denied_write_and_restricted_payload_never_commit(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        with pytest.raises(CheckpointRejected, match="permit denied"):
            await store.save(
                conversation, source, checkpoint(source),
                authorize_write=lambda: False, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
        with pytest.raises(CheckpointRejected, match="restricted"):
            await store.save(
                conversation,
                source,
                checkpoint(source, sensitivity=Sensitivity.LOCAL_ONLY),
                authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
        request = accepted(conversation, 2, "Continue Nepal trip")
        assert (
            await store.read_named(
                conversation,
                request,
                title="Nepal trip",
                authorize_read=lambda: True,
            )
            is None
        )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_negated_forget_is_not_a_delete_request(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, source, checkpoint(source),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        negated = accepted(conversation, 2, "Do not forget Nepal trip")
        with pytest.raises(CheckpointRejected, match="explicit positive"):
            await store.forget(
                conversation,
                negated,
                title="Nepal trip",
                authorize_forget=lambda: True,
            )
        question = accepted(conversation, 3, "Continue Nepal trip")
        assert await store.read_named(
            conversation, question, title="Nepal trip",
            authorize_read=lambda: True,
        )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_write_revoked_inside_transaction_leaves_no_checkpoint(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        calls = [0]

        def permit():
            calls[0] += 1
            return calls[0] < 3

        with pytest.raises(CheckpointRejected, match="permit denied"):
            await store.save(
                conversation, source, checkpoint(source), authorize_write=permit, admit_snapshot=lambda *_: True, expected_plan_epoch=0
            )
        request = accepted(conversation, 2, "Continue Nepal trip")
        result = await store.read_named(
            conversation,
            request,
            title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert result is None
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_read_revoked_after_database_fetch_releases_no_payload(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, source, checkpoint(source),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        question = accepted(conversation, 2, "Continue Nepal trip")
        calls = [0]

        def permit():
            calls[0] += 1
            return calls[0] < 3

        with pytest.raises(CheckpointRejected, match="permit denied"):
            await store.read_named(
                conversation, question, title="Nepal trip", authorize_read=permit
            )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_old_forget_cannot_erase_newer_checkpoint(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, first, checkpoint(first), authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0
        )
        updated = accepted(conversation, 5, "New Nepal trip details")
        await store.save(
            conversation,
            updated,
            checkpoint(updated, budget="flexible"),
            authorize_write=lambda: True, admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        late_forget = accepted(conversation, 3, "Forget Nepal trip")
        assert not await store.forget(
            conversation,
            late_forget,
            title="Nepal trip",
            authorize_forget=lambda: True,
        )
        question = accepted(conversation, 6, "Continue Nepal trip")
        result = await store.read_named(
            conversation,
            question,
            title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert result["constraints"]["budget"] == "flexible"
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_untrusted_sensitivity_label_cannot_bypass_privacy_admission(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        turn = accepted(conversation, 1, "Nepal trip: private account 123")
        proposed = checkpoint(turn, budget="private account 123")
        calls = [0]

        def trusted_admission(snapshot, source):
            calls[0] += 1
            assert source is turn
            assert snapshot is proposed
            return False

        with pytest.raises(CheckpointRejected, match="source admission denied"):
            await store.save(
                conversation,
                turn,
                proposed,
                authorize_write=lambda: True,
                admit_snapshot=trusted_admission, expected_plan_epoch=0,
            )
        assert calls[0] >= 1
        question = accepted(conversation, 2, "Continue Nepal trip")
        result = await store.read_named(
            conversation, question, title="Nepal trip",
            authorize_read=lambda: True,
        )
        assert result is None
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_revoked_privacy_admission_inside_transaction_rolls_back(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        turn = accepted(conversation, 1, "Nepal trip")
        checks = [0]

        def admission(_snapshot, _turn):
            checks[0] += 1
            return checks[0] < 3

        with pytest.raises(CheckpointRejected, match="source admission denied"):
            await store.save(
                conversation,
                turn,
                checkpoint(turn),
                authorize_write=lambda: True,
                admit_snapshot=admission, expected_plan_epoch=0,
            )
        assert checks[0] == 3
        question = accepted(conversation, 2, "Continue Nepal trip")
        assert await store.read_named(
            conversation, question, title="Nepal trip",
            authorize_read=lambda: True,
        ) is None
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_private_labeled_field_is_not_persisted_with_lost_field_provenance(
    tmp_path,
):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        turn = accepted(conversation, 1, "Nepal trip")
        with pytest.raises(CheckpointRejected, match="restricted"):
            await store.save(
                conversation,
                turn,
                checkpoint(turn, sensitivity=Sensitivity.PRIVATE),
                authorize_write=lambda: True,
                admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
        request = accepted(conversation, 2, "Continue Nepal trip")
        assert (
            await store.read_named_snapshot(
                conversation, request,
                title="Nepal trip", authorize_read=lambda: True,
            )
            is None
        )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_unique_short_topic_hint_resolves_without_listing_topics(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, source, checkpoint(source),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        named = accepted(conversation, 2, "Continue Nepal")
        assert await store.resolve_named_topic(
            conversation, named, topic_hint="Nepal",
            authorize_read=lambda: True,
        ) == "nepal trip"
        unnamed = accepted(conversation, 3, "Okay continue")
        with pytest.raises(CheckpointRejected, match="absent"):
            await store.resolve_named_topic(
                conversation, unnamed, topic_hint="Nepal",
                authorize_read=lambda: True,
            )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_two_matching_topics_fail_closed_without_guessing(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, first, checkpoint(first),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        second = accepted(conversation, 2, "Nepal hotel")
        await store.save(
            conversation, second,
            replace(checkpoint(second), title="Nepal hotel"),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        query = accepted(conversation, 3, "Continue Nepal")
        with pytest.raises(CheckpointRejected, match="ambiguous named topic"):
            await store.resolve_named_topic(
                conversation, query, topic_hint="Nepal",
                authorize_read=lambda: True,
            )
    finally:
        await writer.close()
        await reader.close()



@pytest.mark.asyncio
async def test_suppressed_plan_category_denies_read_and_fingerprint_without_leak(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, first, checkpoint(first),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )

        def suppress_without_purge(connection):
            # Simulate a checkpoint surviving from an older database version.
            connection.execute(
                "INSERT INTO personal_learning_suppression "
                "(category,epoch,suppressed,updated_at) VALUES ('plan',1,1,'test')"
            )
            connection.commit()

        await writer.run(suppress_without_purge)
        named = accepted(conversation, 2, "Continue Nepal trip")
        with pytest.raises(CheckpointRejected, match="suppressed"):
            await store.read_named(
                conversation, named, title="Nepal trip",
                authorize_read=lambda: True,
            )
        assert await store.current_fingerprint("Nepal trip") is None
        new_plan = accepted(conversation, 3, "New Nepal trip")
        with pytest.raises(CheckpointRejected, match="suppressed"):
            await store.save(
                conversation, new_plan, checkpoint(new_plan),
                authorize_write=lambda: True,
                admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_suppression_blocks_stale_save_even_after_reenabled(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, first, checkpoint(first),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        disabled = accepted(conversation, 5, "Don't remember my plans")
        await store.purge_for_suppression(
            conversation, disabled, authorize_suppression=lambda: True,
        )

        def reenable(connection):
            connection.execute(
                "UPDATE personal_learning_suppression "
                "SET suppressed=0,epoch=epoch+1 WHERE category='plan'"
            )
            connection.commit()

        # Even after the feature is re-enabled, the tombstone blocks older work.
        await writer.run(reenable)
        late = accepted(conversation, 3, "Nepal trip")
        with pytest.raises(CheckpointRejected, match="older than forget"):
            await store.save(
                conversation, late, checkpoint(late),
                authorize_write=lambda: True,
                admit_snapshot=lambda *_: True, expected_plan_epoch=0,
            )
    finally:
        await writer.close()
        await reader.close()



@pytest.mark.asyncio
async def test_generic_topic_hint_cannot_trigger_private_topic_resolution(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        source = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, source, checkpoint(source),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True, expected_plan_epoch=0,
        )
        generic = accepted(conversation, 2, "Continue my trip")
        with pytest.raises(CheckpointRejected, match="not distinctive"):
            await store.resolve_named_topic(
                conversation, generic, topic_hint="trip",
                authorize_read=lambda: True,
            )
        with pytest.raises(CheckpointRejected, match="not distinctive"):
            await store.resolve_named_topic(
                conversation, generic, topic_hint="my",
                authorize_read=lambda: True,
            )
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_reenabled_plan_epoch_rejects_late_old_proposal_even_with_future_time(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        # This turn has a future timestamp relative to the suppression record,
        # so source-time ordering alone would not catch stale inference.
        old_turn = accepted(conversation, 10, "Nepal trip")

        def disabled_then_reenabled(connection):
            connection.execute(
                "INSERT INTO personal_learning_suppression "
                "(category,epoch,suppressed,updated_at) "
                "VALUES ('plan',2,0,'reenabled')"
            )
            connection.execute(
                "INSERT INTO conversation_topic_tombstone VALUES "
                "('*',?,?)",
                ((START + timedelta(seconds=5)).isoformat(timespec="microseconds"),
                 "suppress-turn"),
            )
            connection.commit()

        await writer.run(disabled_then_reenabled)
        with pytest.raises(CheckpointRejected, match="plan epoch changed"):
            await store.save(
                conversation, old_turn, checkpoint(old_turn),
                authorize_write=lambda: True,
                admit_snapshot=lambda *_: True,
                expected_plan_epoch=0,
            )
        question = accepted(conversation, 11, "Continue Nepal trip")
        assert await store.read_named(
            conversation, question, title="Nepal trip",
            authorize_read=lambda: True,
        ) is None
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_async_prior_accepted_turn_can_save_after_next_user_turn(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        later = accepted(conversation, 2, "And the budget is flexible")
        assert await store.save(
            conversation,
            first,
            checkpoint(first),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True,
            expected_plan_epoch=0,
        )
        # Reads remain bound to the CURRENT accepted user request.
        with pytest.raises(CheckpointRejected, match="canonical owner USER"):
            await store.read_named(
                conversation, first,
                title="Nepal trip", authorize_read=lambda: True,
            )
        query = accepted(conversation, 3, "Continue Nepal trip")
        restored = await store.read_named(
            conversation, query,
            title="Nepal trip", authorize_read=lambda: True,
        )
        assert restored["constraints"]["budget"] == "unrestricted"
        assert later is not query
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_async_forget_from_accepted_turn_survives_following_chatter(tmp_path):
    store, writer, reader = await new_store(tmp_path)
    try:
        conversation = ConversationSession()
        first = accepted(conversation, 1, "Nepal trip")
        await store.save(
            conversation, first, checkpoint(first),
            authorize_write=lambda: True,
            admit_snapshot=lambda *_: True,
            expected_plan_epoch=0,
        )
        forget = accepted(conversation, 3, "Forget Nepal trip")
        accepted(conversation, 4, "Thank you")
        assert await store.forget(
            conversation, forget, title="Nepal trip",
            authorize_forget=lambda: True,
        )
        query = accepted(conversation, 5, "Continue Nepal trip")
        assert await store.read_named(
            conversation, query, title="Nepal trip",
            authorize_read=lambda: True,
        ) is None
    finally:
        await writer.close()
        await reader.close()
