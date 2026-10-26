import asyncio
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import LearningBatch, LearningResolutionBatch


def runtime(learning, extractor):
    from jarvis.memory.learning_reconciliation import LearningReconciler
    from jarvis.memory.learning_runtime import PersonalLearningRuntime

    resolver = SimpleNamespace(resolve=lambda *args: None)

    async def resolve(*args):
        return LearningResolutionBatch()

    resolver.resolve = resolve
    return PersonalLearningRuntime(
        learning.authority,
        learning.service,
        extractor,
        resolver,
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=lambda: 100,
    )


class Extractor:
    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def extract(self, source):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return LearningBatch()


def conversation():
    c = ConversationSession()
    c.start()
    return c


@pytest.mark.asyncio
async def test_queue_bounded_single_flight_callback_nonblocking_and_retirement(
    learning,
):
    e = Extractor()
    r = runtime(learning, e)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        t = c.accept_turn(ConversationRole.USER, "I own a City")
        assert observe(t) is None
        await asyncio.wait_for(e.entered.wait(), 1)
        c.close()
        assert e.calls == 1
        # Provider/conversation retirement does not cancel an accepted process receipt.
        e.release.set()
        await r.drain()
        assert r.status().processed == 1
        c = conversation()
        observe = r.bind(c, learning.grant)
        e.release.clear()
        e.entered.clear()
        for i in range(40):
            observe(c.accept_turn(ConversationRole.USER, f"I own vehicle {i}"))
        assert r.status().queued == 32
        assert r.status().dropped >= 8
        await asyncio.wait_for(e.entered.wait(), 1)
        assert e.calls == 2
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_veto_no_call_and_timeout_no_retry(learning, monkeypatch):
    import jarvis.memory.learning_runtime as module

    monkeypatch.setattr(module, "INFERENCE_TIMEOUT", 0.01)
    e = Extractor()
    r = runtime(learning, e)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        observe(
            c.accept_turn(ConversationRole.USER, "don't remember this: I own a City")
        )
        await asyncio.sleep(0)
        assert e.calls == 0
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        await r.drain()
        assert e.calls == 1 and r.status().reason == "timeout"
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_forget_invalidation_cancels_pending_and_no_late_write(learning):
    e = Extractor()
    r = runtime(learning, e)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        await e.entered.wait()
        r.invalidate_sources(category="owned_item.vehicle")
        e.release.set()
        await r.drain()
        assert await learning.count() == 0
        assert not r._pending
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_full_worker_commits_after_wake_closes_and_rejects_expired_queue(
    learning, clock
):
    from jarvis.memory.learning_contracts import (
        EvidenceSpan,
        LearningCandidate,
        LearningResolution,
    )

    class Facts:
        async def extract(self, source):
            return LearningBatch(
                candidates=[
                    LearningCandidate(
                        category="owned_item",
                        kind="vehicle",
                        intent="new",
                        label="City",
                        value="City",
                        state="owned",
                        evidence=[
                            EvidenceSpan(turn_id=source.turn_id, start=8, end=12)
                        ],
                    )
                ]
            )

    class Resolve:
        async def resolve(self, *args):
            return LearningResolutionBatch(
                resolutions=[LearningResolution(candidate_index=0, decision="new")]
            )

    r = runtime(learning, Facts())
    r.clock = clock
    r.resolver = Resolve()
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        t = c.accept_turn(ConversationRole.USER, "I own a City")
        observe(t)
        c.close()
        await r.drain()
        assert await learning.count() == 1 and r.status().committed == 1
        clock.advance(10)
        observe(t)
        assert learning.authority._grants[learning.grant].last_input == 100
        c = conversation()
        observe = r.bind(c, learning.grant)
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        clock.advance(31)
        await r.drain()
        assert await learning.count() == 1
        observe(c.accept_turn(ConversationRole.USER, "x" * 8001))
        assert r.status().reason == "source_denied"
    finally:
        await r.close()
