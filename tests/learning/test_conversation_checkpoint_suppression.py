"""Plan suppression must atomically erase conversational checkpoints.

The fixture uses SQLite to inspect transaction semantics. Production uses the
same canonical SQLCipher worker and migration, never a plaintext fallback.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, timedelta
from uuid import uuid4

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import AcceptedLearningSource
from jarvis.memory.learning_controls import suppression_binding
from jarvis.memory.types import AuthorityClass, MemorySourceClass


@pytest.mark.asyncio
async def test_plan_suppression_tombstones_checkpoints_in_same_transaction(learning):
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Don't remember my plans")
    source = AcceptedLearningSource.from_turn(
        "runtime", conversation, turn, now=101, current_only=True
    )
    learning.authority.register_source(learning.grant, source.receipt_id, source=source)
    old_time = (
        (turn.accepted_at - timedelta(seconds=5))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
    )

    def seed_old(connection):
        connection.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            ("nepal trip", "old-turn", old_time, '{"title":"Nepal trip"}'),
        )
        connection.commit()

    await learning.writer.run(seed_old)
    # Even a checkpoint carrying a later source timestamp must be erased
    # when the owner disables all plan learning.
    future_time = (
        (turn.accepted_at + timedelta(seconds=5))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
    )

    def seed_future(connection):
        connection.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            (
                "nepal hotel",
                "queued-future-turn",
                future_time,
                '{"title":"Nepal hotel"}',
            ),
        )
        connection.commit()

    await learning.writer.run(seed_future)
    categories = ("plan",)
    permit = learning.authority.issue_child(
        learning.grant, suppression_binding(source, categories)
    )
    await learning.service.suppress_learning_categories(source, categories, permit)
    saved = await learning.reader.run(
        lambda conn: conn.execute(
            "SELECT count(*) FROM conversation_topic_checkpoint"
        ).fetchone()[0]
    )
    assert saved == 0
    tombstone = await learning.reader.run(
        lambda conn: conn.execute(
            "SELECT forgotten_at,source_turn_id FROM "
            "conversation_topic_tombstone WHERE topic_key='*'"
        ).fetchone()
    )
    assert tombstone == (
        turn.accepted_at.astimezone(UTC).isoformat(timespec="microseconds"),
        turn.turn_id,
    )
    # Re-enabling cannot resurrect previously deleted checkpoint contents.
    owner_explicit = replace(
        learning.plan.mutations[0].source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.reenable_learning_category(
        "plan",
        owner_explicit,
        learning.authority.authorize_reenable_category("plan"),
    )
    assert (
        await learning.reader.run(
            lambda conn: conn.execute(
                "SELECT count(*) FROM conversation_topic_checkpoint"
            ).fetchone()[0]
        )
        == 0
    )


@pytest.mark.asyncio
async def test_legacy_plan_fact_forget_invalidates_any_checkpoint_replay(learning):
    # Existing canonical forgetting can target a plan fact without knowing
    # which conversation checkpoint contains it. Fail closed by erasing all
    # checkpoints atomically with the legacy plan-fact deletion.
    first = learning.plan.mutations[0]
    await learning.service.admit_learning(learning.plan, learning.new_permit())

    def mark_as_plan_and_seed(connection):
        connection.execute(
            "UPDATE personal_learning_receipt SET category='plan' "
            "WHERE target_id=(SELECT assertion_id FROM current_semantic_assertion "
            "WHERE predicate=?)",
            (first.predicate,),
        )
        connection.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            (
                "nepal trip",
                "source-turn",
                "2026-01-01T00:00:00.000000+00:00",
                '{"title":"Nepal trip"}',
            ),
        )
        connection.commit()

    await learning.writer.run(mark_as_plan_and_seed)
    explicit = replace(
        first.source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.forget_exact(predicate=first.predicate, source=explicit)

    remaining = await learning.reader.run(
        lambda connection: connection.execute(
            "SELECT count(*) FROM conversation_topic_checkpoint"
        ).fetchone()[0]
    )
    assert remaining == 0
    tombstone = await learning.reader.run(
        lambda connection: connection.execute(
            "SELECT source_turn_id FROM conversation_topic_tombstone "
            "WHERE topic_key='*'"
        ).fetchone()
    )
    assert tombstone == (explicit.source_id,)
    suppression = await learning.service.learning_suppression()
    assert "plan" in suppression.suppressed


@pytest.mark.asyncio
async def test_runtime_caches_authoritative_plan_epoch_for_nonblocking_voice(learning):
    from jarvis.memory.runtime import MemoryRuntime

    runtime = MemoryRuntime(
        learning.service, writer=learning.writer, reader=learning.reader
    )
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Don't remember my plans")
    with pytest.raises(PermissionError, match="unavailable"):
        runtime.accepted_plan_epoch(turn)
    await runtime.start()
    assert runtime.accepted_plan_epoch(turn) == 0

    source = AcceptedLearningSource.from_turn(
        "runtime", conversation, turn, now=101, current_only=True
    )
    learning.authority.register_source(learning.grant, source.receipt_id, source=source)
    permit = learning.authority.issue_child(
        learning.grant, suppression_binding(source, ("plan",))
    )
    await learning.service.suppress_learning_categories(source, ("plan",), permit)
    assert runtime.accepted_plan_epoch(turn) == 1

    explicit = replace(
        learning.plan.mutations[0].source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.reenable_learning_category(
        "plan",
        explicit,
        learning.authority.authorize_reenable_category("plan"),
    )
    assert runtime.accepted_plan_epoch(turn) == 2


@pytest.mark.asyncio
async def test_legacy_plan_correction_invalidates_old_checkpoint_and_epoch(learning):
    from jarvis.memory.runtime import MemoryRuntime

    runtime = MemoryRuntime(
        learning.service, writer=learning.writer, reader=learning.reader
    )
    await runtime.start()
    old = learning.plan.mutations[0]
    await learning.service.admit_learning(learning.plan, learning.new_permit())

    def seed_plan_receipt_and_checkpoint(connection):
        connection.execute(
            "UPDATE personal_learning_receipt SET category='plan' "
            "WHERE target_id=(SELECT assertion_id FROM current_semantic_assertion "
            "WHERE predicate=?)",
            (old.predicate,),
        )
        connection.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            (
                "nepal trip",
                "old-user-turn",
                "2026-01-01T00:00:00.000000+00:00",
                '{"title":"Nepal trip"}',
            ),
        )
        connection.commit()

    await learning.writer.run(seed_plan_receipt_and_checkpoint)
    owner = replace(
        old.source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.correct_text(
        predicate=old.predicate,
        value="updated owner plan",
        source=owner,
    )
    assert runtime._plan_epoch == 1
    assert (
        await learning.reader.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM conversation_topic_checkpoint"
            ).fetchone()[0]
        )
        == 0
    )
    snapshot = await learning.service.learning_suppression()
    assert snapshot.epochs["plan"] == 1
    assert "plan" not in snapshot.suppressed
    tombstone = await learning.reader.run(
        lambda connection: connection.execute(
            "SELECT source_turn_id FROM conversation_topic_tombstone "
            "WHERE topic_key='*'"
        ).fetchone()
    )
    assert tombstone == (owner.source_id,)
