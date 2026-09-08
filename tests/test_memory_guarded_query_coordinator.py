from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis.memory.answer_type_guard import (
    ALLOW_TYPES,
    MemoryAnswerType,
    MemoryAnswerTypeDecision,
)
from jarvis.memory.evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
)
from jarvis.memory.guarded_query_coordinator import GuardedMemoryQueryCoordinator
from jarvis.memory.query_coordinator import MemoryQueryCoordinator


@dataclass
class StaticGuard:
    decision: MemoryAnswerTypeDecision | None = None
    error: Exception | None = None
    calls: int = 0

    @property
    def model_name(self) -> str:
        return "static-guard"

    async def evaluate(self, text: str) -> MemoryAnswerTypeDecision:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.decision is None:
            raise AssertionError("test guard decision is missing")
        return self.decision


class FakeCoordinator(MemoryQueryCoordinator):
    def __init__(self, decision: MemoryEvidenceDecision) -> None:
        self.decision = decision
        self.calls = 0
        self.texts: list[str] = []

    async def resolve(self, text: str, *, eligibility=None) -> MemoryEvidenceDecision:
        self.calls += 1
        self.texts.append(text)
        return self.decision


def _guard_decision(answer_type: MemoryAnswerType) -> MemoryAnswerTypeDecision:
    return MemoryAnswerTypeDecision(
        answer_type=answer_type,
        allow=answer_type in ALLOW_TYPES,
        top_probability=0.6,
        reason_code=(
            "answer_type_allows_exact_value_release"
            if answer_type in ALLOW_TYPES
            else "answer_type_vetoes_exact_value_release"
        ),
    )


def _abstain(reason: str = "core_abstain") -> MemoryEvidenceDecision:
    return MemoryEvidenceDecision(
        disposition=MemoryEvidenceDisposition.ABSTAIN,
        reason_code=reason,
    )


@pytest.mark.asyncio
async def test_current_value_allow_reaches_deterministic_core() -> None:
    core = FakeCoordinator(_abstain("core_policy_decision"))
    guard = StaticGuard(_guard_decision(MemoryAnswerType.CURRENT_VALUE))
    coordinator = GuardedMemoryQueryCoordinator(
        coordinator=core,
        answer_type_guard=guard,
    )

    decision = await coordinator.resolve("Aquila archive destination kya hai?")

    assert guard.calls == 1
    assert core.calls == 1
    assert core.texts == ["Aquila archive destination kya hai?"]
    assert decision.reason_code == "core_policy_decision"


@pytest.mark.asyncio
async def test_comparison_allow_reaches_deterministic_core() -> None:
    core = FakeCoordinator(_abstain("core_policy_decision"))
    guard = StaticGuard(_guard_decision(MemoryAnswerType.CURRENT_VALUE_COMPARISON))
    coordinator = GuardedMemoryQueryCoordinator(
        coordinator=core,
        answer_type_guard=guard,
    )

    await coordinator.resolve("Is vault-A the archive destination?")

    assert core.calls == 1


@pytest.mark.asyncio
async def test_semantic_veto_never_calls_deterministic_core() -> None:
    core = FakeCoordinator(_abstain())
    guard = StaticGuard(_guard_decision(MemoryAnswerType.REASON_EXPLANATION))
    coordinator = GuardedMemoryQueryCoordinator(
        coordinator=core,
        answer_type_guard=guard,
    )

    decision = await coordinator.resolve("Why was vault-A chosen?")

    assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert decision.reason_code == "answer_type_veto_reason_explanation"
    assert core.calls == 0


@pytest.mark.asyncio
async def test_guard_failure_abstains_without_calling_core() -> None:
    core = FakeCoordinator(_abstain())
    guard = StaticGuard(error=RuntimeError("model unavailable"))
    coordinator = GuardedMemoryQueryCoordinator(
        coordinator=core,
        answer_type_guard=guard,
    )

    decision = await coordinator.resolve("What is the current archive destination?")

    assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert decision.reason_code == "answer_type_guard_unavailable"
    assert core.calls == 0


def test_answer_type_decision_rejects_policy_mismatch() -> None:
    with pytest.raises(ValueError, match="allow must match"):
        MemoryAnswerTypeDecision(
            answer_type=MemoryAnswerType.PROVENANCE_ACTOR,
            allow=True,
            top_probability=0.5,
            reason_code="bad",
        )
