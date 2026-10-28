"""Session-long permission with real canonical storage and fake OS/Hello."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_runtime import PersonalLearningRuntime


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [424, 86400])
async def test_real_write_after_long_pause_and_new_wake(
    learning, clock, authority_parts, pause
):
    async def extract(source):
        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="owned_item",
                    kind="vehicle",
                    intent="new",
                    label="City",
                    value="City",
                    state="owned",
                    evidence=[EvidenceSpan(turn_id=source.turn_id, start=8, end=12)],
                )
            ]
        )

    async def resolve(*args):
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=clock,
    )
    old = ConversationSession()
    old.start()
    old.close()
    clock.advance(pause)
    c = ConversationSession()
    c.start()
    try:
        r.bind(c, learning.grant)(c.accept_turn(ConversationRole.USER, "I own a City"))
        await asyncio.wait_for(r.drain(), 3)
        assert await learning.count() == 1
        assert r.status().committed == 1
        assert len(authority_parts.hello.calls) == 1
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_revoked_permission_reports_unavailable_once_and_never_writes(
    learning, authority_parts, caplog
):
    extractor = SimpleNamespace(
        extract=lambda source: pytest.fail("revoked source reached provider")
    )
    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        extractor,
        SimpleNamespace(),
        SimpleNamespace(),
        clock=lambda: 100,
    )
    c = ConversationSession()
    c.start()
    authority_parts.windows.lock_unlock()
    try:
        with caplog.at_level(logging.WARNING):
            observe = r.bind(c, learning.grant)
            for _ in range(2):
                observe(c.accept_turn(ConversationRole.USER, "I own a City"))
            await asyncio.wait_for(r.drain(), 3)
        assert caplog.text.count("Automatic memory unavailable") == 1
        assert "restart Jarvis and approve Windows Hello" in caplog.text
        assert await learning.count() == 0
    finally:
        await r.close()
