from __future__ import annotations

import asyncio

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.candidate_runtime import MemoryCandidateSessionRuntime
from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)


def _proposal() -> MemoryExtractionProposal:
    return MemoryExtractionProposal(
        intent=MemoryExtractionIntent.CANDIDATE,
        candidate_type=MemoryCandidateType.FACT,
        durable_candidate=True,
        subject="owner",
        predicate="home_city",
        value="Indore",
        temporal_hint=None,
        sensitivity=MemoryExtractionSensitivity.NORMAL,
        confidence=0.9,
    )


class FakeExtractor:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self, *, blocked: bool = False) -> None:
        self.calls: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked = blocked

    async def extract(self, *, text: str) -> MemoryExtractionProposal:
        self.calls.append(text)
        self.started.set()
        if self.blocked:
            await self.release.wait()
        return _proposal()


def _conversation() -> ConversationSession:
    conversation = ConversationSession(session_id="session-1")
    conversation.start()
    return conversation


@pytest.mark.asyncio
async def test_runtime_processes_user_turn_in_background_and_quarantines_only() -> None:
    conversation = _conversation()
    turn = conversation.accept_turn(ConversationRole.USER, "My home city is Indore.")
    extractor = FakeExtractor()
    runtime = MemoryCandidateSessionRuntime(
        conversation=conversation,
        extractor=extractor,
    )

    runtime.observe_turn(turn)
    assert runtime.pending_task_count == 1

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert extractor.calls == ["My home city is Indore."]
    assert len(runtime.quarantine.snapshot()) == 1
    assert runtime.pending_task_count == 0

    runtime.close()

    assert runtime.closed is True
    assert runtime.quarantine.disposed is True
    assert runtime.quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_runtime_ignores_assistant_turns() -> None:
    conversation = _conversation()
    turn = conversation.accept_turn(ConversationRole.ASSISTANT, "Hello.")
    extractor = FakeExtractor()
    runtime = MemoryCandidateSessionRuntime(
        conversation=conversation,
        extractor=extractor,
    )

    runtime.observe_turn(turn)
    await asyncio.sleep(0)

    assert extractor.calls == []
    assert runtime.pending_task_count == 0
    assert runtime.quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_close_cancels_inflight_extraction_and_physically_drops_quarantine() -> (
    None
):
    conversation = _conversation()
    turn = conversation.accept_turn(ConversationRole.USER, "My home city is Indore.")
    extractor = FakeExtractor(blocked=True)
    runtime = MemoryCandidateSessionRuntime(
        conversation=conversation,
        extractor=extractor,
    )

    runtime.observe_turn(turn)
    await extractor.started.wait()
    assert runtime.pending_task_count == 1

    runtime.close()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert runtime.closed is True
    assert runtime.quarantine.disposed is True
    assert runtime.quarantine.snapshot() == ()
    assert runtime.pending_task_count == 0


@pytest.mark.asyncio
async def test_closed_runtime_never_schedules_new_extraction() -> None:
    conversation = _conversation()
    turn = conversation.accept_turn(ConversationRole.USER, "My home city is Indore.")
    extractor = FakeExtractor()
    runtime = MemoryCandidateSessionRuntime(
        conversation=conversation,
        extractor=extractor,
    )
    runtime.close()

    runtime.observe_turn(turn)
    await asyncio.sleep(0)

    assert extractor.calls == []
    assert runtime.pending_task_count == 0
    assert runtime.quarantine.snapshot() == ()
