"""Named-topic resumption must inherit normal voice read consent and retirement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import (
    EvidenceStrength,
    GroundedStateValue,
    TopicSnapshot,
)
from jarvis.memory.types import Sensitivity
from jarvis.voice.personal_context import PersonalContextSession


def field(source_id, value):
    return GroundedStateValue(
        value=value,
        evidence=value,
        source_turn_id=source_id,
        accepted_at=datetime(2026, 10, 29, tzinfo=UTC),
        sensitivity=Sensitivity.STANDARD,
        evidence_strength=EvidenceStrength.LITERAL,
    )


class OwnerAuthority:
    def __init__(self):
        self.valid = True
        self.prompt_count = 0
        self.invalidated = False

    def authorize_personal_context(self, **kwargs):
        self.prompt_count += 1
        assert kwargs["operation"] == "read"
        assert kwargs["question"] == "Continue Nepal trip"
        return object()

    def consume_personal_context(self, permit):
        if not self.valid:
            raise PermissionError("revoked")

    def validate_personal_context(self, permit):
        if not self.valid:
            raise PermissionError("revoked")

    def invalidate_personal_context(self, session_id):
        self.invalidated = True


class TopicStore:
    def __init__(self, *, present=True):
        self.present = present
        self.revision = "revision-1"
        self.revoke_on_read = None

    async def read_named_snapshot(
        self, conversation, turn, *, title, authorize_read
    ):
        assert title == "Nepal trip"
        assert authorize_read() is True
        if self.revoke_on_read is not None:
            self.revoke_on_read()
        if not self.present:
            return None
        return TopicSnapshot(
            title="Nepal trip",
            goal=field("source-goal", "plan Nepal trip"),
            constraints=(("permits", field("source-permits", "sorted")),),
            steps=(("route", field("source-route", "plan route")),),
        )

    async def current_fingerprint(self, title):
        assert title == "Nepal trip"
        return self.revision


def personal_session(authority, store, *, question="Continue Nepal trip"):
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, question)
    closed = []
    session = PersonalContextSession(
        conversation=conversation,
        retrieval=object(),
        authority=authority,
        retire=lambda: closed.append(True),
        topic_checkpoints=store,
    )
    return session, closed


@pytest.mark.asyncio
async def test_named_topic_uses_fresh_owner_consent_and_protected_response():
    authority = OwnerAuthority()
    store = TopicStore()
    personal, closed = personal_session(authority, store)
    try:
        result = await personal.resume_topic("Nepal trip")
        assert result["status"] == "selected"
        assert any("sorted" in fact["text"] for fact in result["facts"])
        assert authority.prompt_count == 1
        assert personal.protected
        assert await personal.allow_audio() is True
        personal.playback_finished()
        personal.response_finished()
        await asyncio.sleep(0)
        assert closed
    finally:
        personal.close()


@pytest.mark.asyncio
async def test_revoked_permit_during_checkpoint_read_releases_no_content():
    authority = OwnerAuthority()
    store = TopicStore()
    store.revoke_on_read = lambda: setattr(authority, "valid", False)
    personal, closed = personal_session(authority, store)
    try:
        result = await personal.resume_topic("Nepal trip")
        assert result == {"status": "denied"}
        assert closed
    finally:
        personal.close()


@pytest.mark.asyncio
async def test_changed_checkpoint_revision_blocks_audio():
    authority = OwnerAuthority()
    store = TopicStore()
    personal, closed = personal_session(authority, store)
    try:
        assert (await personal.resume_topic("Nepal trip"))["status"] == "selected"
        store.revision = "revision-2-after-forget"
        assert await personal.allow_audio() is False
        assert closed
    finally:
        personal.close()


@pytest.mark.asyncio
async def test_no_checkpoint_cannot_invent_trip_context():
    authority = OwnerAuthority()
    store = TopicStore(present=False)
    personal, _ = personal_session(authority, store)
    try:
        result = await personal.resume_topic("Nepal trip")
        assert result == {"status": "no_match", "facts": []}
        assert authority.prompt_count == 1
    finally:
        personal.close()


@pytest.mark.asyncio
async async def test_no_new_topic_tool_unless_explicitly_configured():
    authority = OwnerAuthority()
    session, _ = personal_session(authority, TopicStore())
    session._topic_checkpoints = None
    assert not session.supports_topic_resume
    session.close()


@pytest.mark.asyncio
async def test_revision_changed_during_read_rejects_stale_snapshot():
    authority = OwnerAuthority()
    store = TopicStore()
    store.revoke_on_read = lambda: setattr(store, "revision", "new-version")
    personal, closed = personal_session(authority, store)
    try:
        result = await personal.resume_topic("Nepal trip")
        assert result == {"status": "denied"}
        assert closed
    finally:
        personal.close()
