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
    turn = conversation.accept_turn(
        ConversationRole.USER, "Don't remember my plans"
    )
    source = AcceptedLearningSource.from_turn(
        "runtime", conversation, turn, now=101, current_only=True
    )
    learning.authority.register_source(
        learning.grant, source.receipt_id, source=source
    )
    old_time = (turn.accepted_at - timedelta(seconds=5)).astimezone(UTC).isoformat(
        timespec="microseconds"
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
    future_time = (turn.accepted_at + timedelta(seconds=5)).astimezone(
        UTC
    ).isoformat(timespec="microseconds")
    def seed_future(connection):
        connection.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            ("nepal hotel", "queued-future-turn", future_time, '{"title":"Nepal hotel"}'),
        )
        connection.commit()

    await learning.writer.run(seed_future)
    categories = ("plan",)
    permit = learning.authority.issue_child(
        learning.grant, suppression_binding(source, categories)
    )
    await learning.service.suppress_learning_categories(
        source, categories, permit
    )
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
    assert await learning.reader.run(
        lambda conn: conn.execute(
            "SELECT count(*) FROM conversation_topic_checkpoint"
        ).fetchone()[0]
    ) == 0
