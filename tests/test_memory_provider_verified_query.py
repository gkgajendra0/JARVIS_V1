from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
    TrustedMemoryEvidence,
)
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.release_guard import MemoryReleaseAnswerType, MemoryReleaseJudgement
from jarvis.memory.retrieval import RetrievalEligibility
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)


def _record() -> SemanticAssertionRecord:
    now = datetime.now(UTC)
    return SemanticAssertionRecord(
        assertion_id="a1",
        subject_scope="owner",
        subject="self",
        predicate="current car",
        value_type=ValueType.TEXT,
        value="Jimny",
        normalized_text="current car Jimny",
        source_id="s1",
        valid_from=now,
        valid_to=None,
        system_from=now,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=Sensitivity.STANDARD,
        created_at=now,
        updated_at=now,
    )


class _Core(MemoryQueryCoordinator):
    def __init__(self, decision: MemoryEvidenceDecision):
        self.decision = decision
        self.eligibility = None

    async def resolve(self, text, *, eligibility=None):
        self.eligibility = eligibility
        return self.decision


class _Guard:
    provider_name = "gemini"
    model_name = "gemini-test"

    def __init__(self, judgement=None, *, error: Exception | None = None):
        self.judgement = judgement
        self.error = error
        self.calls = []

    async def evaluate(self, *, text, evidence):
        self.calls.append((text, evidence))
        if self.error is not None:
            raise self.error
        return self.judgement


def _released() -> MemoryEvidenceDecision:
    record = _record()
    evidence = TrustedMemoryEvidence(assertion=record, reason_code="core")
    return MemoryEvidenceDecision(
        disposition=MemoryEvidenceDisposition.RELEASE,
        reason_code="core",
        evidence=evidence,
    )


@pytest.mark.asyncio
async def test_provider_verified_query_releases_only_after_second_allow() -> None:
    core = _Core(_released())
    guard = _Guard(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
            directly_supported=True,
        )
    )
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=guard,
    )
    result = await coordinator.resolve("What car do I have?")
    assert result.disposition is MemoryEvidenceDisposition.RELEASE
    assert result.evidence is not None
    assert result.evidence.assertion.value == "Jimny"
    assert core.eligibility == RetrievalEligibility.cloud_context()
    assert len(guard.calls) == 1


@pytest.mark.asyncio
async def test_provider_verified_query_vetoes_reason_question() -> None:
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=_Core(_released()),
        release_guard=_Guard(
            MemoryReleaseJudgement(
                answer_type=MemoryReleaseAnswerType.REASON_EXPLANATION,
                directly_supported=False,
            )
        ),
    )
    result = await coordinator.resolve("Why did I buy Jimny?")
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert result.reason_code == "provider_memory_release_veto_reason_explanation"


@pytest.mark.asyncio
async def test_provider_verified_query_fails_closed_on_verifier_error() -> None:
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=_Core(_released()),
        release_guard=_Guard(error=RuntimeError("provider down")),
    )
    result = await coordinator.resolve("What car do I have?")
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert result.reason_code == "provider_memory_release_guard_unavailable"


@pytest.mark.asyncio
async def test_provider_verified_query_refuses_local_only_eligibility_before_core() -> (
    None
):
    core = _Core(_released())
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=_Guard(
            MemoryReleaseJudgement(
                answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
                directly_supported=True,
            )
        ),
    )
    result = await coordinator.resolve(
        "What car do I have?",
        eligibility=RetrievalEligibility.local(),
    )
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert (
        result.reason_code == "provider_semantic_recall_requires_cloud_safe_eligibility"
    )
    assert core.eligibility is None
