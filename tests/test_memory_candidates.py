from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.candidates import (
    MemoryCandidateCoordinator,
    MemoryCandidateOutcome,
    MemoryCandidatePolicy,
    MemoryCandidateQuarantine,
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.types import AuthorityClass, MemorySourceClass


class FakeExtractor:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self, proposal: MemoryExtractionProposal) -> None:
        self.proposal = proposal
        self.calls: list[str] = []

    async def extract(self, *, text: str) -> MemoryExtractionProposal:
        self.calls.append(text)
        return self.proposal


def _proposal(
    *,
    intent: MemoryExtractionIntent = MemoryExtractionIntent.CANDIDATE,
    candidate_type: MemoryCandidateType = MemoryCandidateType.FACT,
    durable_candidate: bool = True,
    subject: str | None = "owner",
    predicate: str | None = "home_city",
    value: str | None = "Indore",
    sensitivity: MemoryExtractionSensitivity = MemoryExtractionSensitivity.NORMAL,
    confidence: float = 0.9,
) -> MemoryExtractionProposal:
    return MemoryExtractionProposal(
        intent=intent,
        candidate_type=candidate_type,
        durable_candidate=durable_candidate,
        subject=subject,
        predicate=predicate,
        value=value,
        temporal_hint=None,
        sensitivity=sensitivity,
        confidence=confidence,
    )


def _conversation(text: str, *, session_id: str = "session-1") -> ConversationSession:
    conversation = ConversationSession(session_id=session_id)
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return conversation


def test_proposal_forbids_unexpected_provider_fields() -> None:
    with pytest.raises(ValidationError):
        MemoryExtractionProposal.model_validate(
            {
                "intent": "candidate",
                "candidate_type": "fact",
                "durable_candidate": True,
                "subject": "owner",
                "predicate": "home_city",
                "value": "Indore",
                "temporal_hint": None,
                "sensitivity": "normal",
                "confidence": 0.8,
                "authority_class": "owner_explicit",
            }
        )


def test_low_confidence_does_not_create_a_guessed_quarantine_threshold() -> None:
    decision = MemoryCandidatePolicy().evaluate(_proposal(confidence=0.01))
    assert decision.disposition.value == "quarantine"
    assert decision.reason_code == "structurally_eligible_candidate"


@pytest.mark.asyncio
async def test_direct_fact_is_quarantined_with_jarvis_owned_provenance() -> None:
    conversation = _conversation("My home city is Indore.")
    extractor = FakeExtractor(_proposal(confidence=0.01))
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(
        extractor=extractor,
        quarantine=quarantine,
        id_factory=lambda: "candidate-1",
        clock=lambda: datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    result = await coordinator.consider_latest_user_turn(conversation)

    assert result.outcome is MemoryCandidateOutcome.QUARANTINED
    assert extractor.calls == ["My home city is Indore."]
    assert result.candidate is not None
    assert result.candidate.candidate_id == "candidate-1"
    assert result.candidate.session_id == conversation.session_id
    assert result.candidate.source_turn_id == conversation.turns[-1].turn_id
    assert result.candidate.source_class is MemorySourceClass.OWNER_DIRECT
    assert result.candidate.authority_class is AuthorityClass.OWNER_DIRECT
    assert result.candidate.extractor_provider == "fake-provider"
    assert result.candidate.extractor_model == "fake-model"
    assert quarantine.snapshot() == (result.candidate,)


@pytest.mark.asyncio
async def test_explicit_memory_control_is_not_sent_to_implicit_extractor() -> None:
    conversation = _conversation("Remember that my home city is Indore.")
    extractor = FakeExtractor(_proposal())
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(extractor=extractor, quarantine=quarantine)

    result = await coordinator.consider_latest_user_turn(conversation)

    assert result.outcome is MemoryCandidateOutcome.SKIPPED_EXPLICIT_MEMORY_CONTROL
    assert extractor.calls == []
    assert quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_obvious_secret_is_rejected_before_provider_call() -> None:
    conversation = _conversation("My test API key is sk-abcdefghijklmnop123456.")
    extractor = FakeExtractor(_proposal())
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(extractor=extractor, quarantine=quarantine)

    result = await coordinator.consider_latest_user_turn(conversation)

    assert result.outcome is MemoryCandidateOutcome.REJECTED_SECRET
    assert result.reason_code == "local_secret_prefilter"
    assert extractor.calls == []
    assert quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_secret_proposal_is_rejected_after_extraction() -> None:
    conversation = _conversation("Here is a credential-looking value for testing.")
    extractor = FakeExtractor(
        _proposal(
            candidate_type=MemoryCandidateType.SECRET,
            durable_candidate=False,
            predicate="api_key",
            value="not-a-real-key",
            sensitivity=MemoryExtractionSensitivity.SECRET,
        )
    )
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(extractor=extractor, quarantine=quarantine)

    result = await coordinator.consider_latest_user_turn(conversation)

    assert result.outcome is MemoryCandidateOutcome.REJECTED_SECRET
    assert result.reason_code == "proposal_secret_guard"
    assert quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_transient_proposal_does_not_enter_quarantine() -> None:
    conversation = _conversation("I am tired right now.")
    extractor = FakeExtractor(
        _proposal(
            intent=MemoryExtractionIntent.TRANSIENT,
            candidate_type=MemoryCandidateType.INTERACTION_CONTEXT,
            durable_candidate=False,
            predicate="current_mood",
            value="tired",
        )
    )
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(extractor=extractor, quarantine=quarantine)

    result = await coordinator.consider_latest_user_turn(conversation)

    assert result.outcome is MemoryCandidateOutcome.REJECTED_POLICY
    assert result.reason_code == "provider_marked_non_durable"
    assert quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_quarantine_rejects_a_different_conversation_session() -> None:
    owner_conversation = _conversation("My home city is Indore.")
    extractor = FakeExtractor(_proposal())
    quarantine = MemoryCandidateQuarantine(session_id=owner_conversation.session_id)
    coordinator = MemoryCandidateCoordinator(extractor=extractor, quarantine=quarantine)
    other = _conversation("My home city is Sagar.", session_id="session-2")

    with pytest.raises(ValueError, match="does not own"):
        await coordinator.consider_latest_user_turn(other)

    assert extractor.calls == []
    assert quarantine.snapshot() == ()


@pytest.mark.asyncio
async def test_disposal_physically_drops_process_local_candidates() -> None:
    conversation = _conversation("My home city is Indore.")
    extractor = FakeExtractor(_proposal())
    quarantine = MemoryCandidateQuarantine(session_id=conversation.session_id)
    coordinator = MemoryCandidateCoordinator(
        extractor=extractor,
        quarantine=quarantine,
        id_factory=lambda: "candidate-1",
    )

    result = await coordinator.consider_latest_user_turn(conversation)
    assert result.outcome is MemoryCandidateOutcome.QUARANTINED
    assert len(quarantine.snapshot()) == 1

    quarantine.dispose()

    assert quarantine.disposed is True
    assert quarantine.snapshot() == ()
