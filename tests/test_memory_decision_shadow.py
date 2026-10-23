"""Research-only tests: these are NOT a blind memory-quality benchmark."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.decision_shadow import (
    CandidateReviewDisposition,
    CandidateShadowInput,
    ContextShadowDisposition,
    ContextShadowEvidence,
    ContextUtilitySignal,
    assess_candidate_shadow,
    assess_context_shadow,
)
from jarvis.memory.types import (
    AssertionState,
    AuthorityClass,
    MemorySourceClass,
    Sensitivity,
)


def _proposal(**changes: object) -> MemoryExtractionProposal:
    arguments = {
        "intent": MemoryExtractionIntent.CANDIDATE,
        "candidate_type": MemoryCandidateType.PREFERENCE,
        "durable_candidate": True,
        "subject": "owner",
        "predicate": "preferred_reply_style",
        "value": "concise practical examples",
        "temporal_hint": None,
        "sensitivity": MemoryExtractionSensitivity.NORMAL,
        "confidence": 0.97,
    }
    arguments.update(changes)
    return MemoryExtractionProposal.model_validate(arguments)


def _candidate(**changes: object) -> CandidateShadowInput:
    kwargs = {
        "proposal": _proposal(),
        "source_class": MemorySourceClass.OWNER_DIRECT,
        "accepted_user_turn": True,
        "current_exact_value": None,
    }
    kwargs.update(changes)
    return CandidateShadowInput(**kwargs)


def _context() -> ContextShadowEvidence:
    return ContextShadowEvidence(
        authority=AuthorityClass.OWNER_DIRECT,
        source=MemorySourceClass.OWNER_DIRECT,
        sensitivity=Sensitivity.STANDARD,
        state=AssertionState.ACTIVE,
        canonical_source_ref="canonical:utterance-1",
        memory_scope="interview_answer_style",
        current_task_scope="interview_answer_style",
        task_grounded_in_current_turn=True,
        conflicts_with_current_turn=False,
        utility_signal=ContextUtilitySignal.HELPFUL,
    )


def test_new_ordinary_candidate_is_review_only_not_admission() -> None:
    result = assess_candidate_shadow(_candidate())
    assert result.disposition is CandidateReviewDisposition.REVIEW
    assert result.reason_code == "eligible_proposal_requires_review"
    assert not hasattr(result, "value")
    assert not hasattr(result, "can_write")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"accepted_user_turn": False}, "not_accepted_direct_owner_turn"),
        (
            {"source_class": MemorySourceClass.EXTERNAL_EMAIL},
            "not_accepted_direct_owner_turn",
        ),
        (
            {"proposal": _proposal(sensitivity=MemoryExtractionSensitivity.SECRET)},
            "not_normal_sensitivity",
        ),
        (
            {"proposal": _proposal(sensitivity=MemoryExtractionSensitivity.SENSITIVE)},
            "not_normal_sensitivity",
        ),
        (
            {"proposal": _proposal(durable_candidate=False)},
            "provider_marked_non_durable",
        ),
        (
            {"proposal": _proposal(intent=MemoryExtractionIntent.TRANSIENT)},
            "intent_not_quarantine_eligible",
        ),
    ],
)
def test_candidate_shadow_fails_closed(kwargs: dict, reason: str) -> None:
    result = assess_candidate_shadow(_candidate(**kwargs))
    assert result.disposition is CandidateReviewDisposition.SKIP
    assert result.reason_code == reason


def test_candidate_shadow_deduplicates_only_exact_normalized_value() -> None:
    result = assess_candidate_shadow(
        _candidate(current_exact_value="  CONCISE practical EXAMPLES  ")
    )
    assert result.disposition is CandidateReviewDisposition.DUPLICATE


def test_candidate_shadow_requiring_existing_fact_change_never_auto_writes() -> None:
    conflicting = assess_candidate_shadow(
        _candidate(current_exact_value="detailed explanations")
    )
    assert conflicting.disposition is CandidateReviewDisposition.CONFLICT_REVIEW
    correction = assess_candidate_shadow(
        _candidate(
            proposal=_proposal(
                intent=MemoryExtractionIntent.CORRECTION,
                candidate_type=MemoryCandidateType.FACT_CORRECTION,
            )
        )
    )
    assert correction.disposition is CandidateReviewDisposition.CONFLICT_REVIEW


def test_context_shadow_is_only_measurement_never_injection() -> None:
    result = assess_context_shadow(_context())
    assert result.disposition is ContextShadowDisposition.MEASURE_ONLY
    assert result.reason_code == "eligible_for_shadow_evaluation_only"
    assert not hasattr(result, "memory_value")
    assert not hasattr(result, "context_packet")
    assert not hasattr(result, "release")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"authority": AuthorityClass.UNTRUSTED}, "unapproved_source_or_authority"),
        (
            {"source": MemorySourceClass.ASSISTANT_OUTPUT},
            "unapproved_source_or_authority",
        ),
        ({"sensitivity": Sensitivity.LOCAL_ONLY}, "sensitivity_not_admitted"),
        ({"sensitivity": Sensitivity.PRIVATE}, "sensitivity_not_admitted"),
        ({"state": AssertionState.SUPERSEDED}, "not_current_active_assertion"),
        ({"canonical_source_ref": None}, "missing_canonical_provenance"),
        ({"conflicts_with_current_turn": True}, "current_turn_has_priority"),
        ({"task_grounded_in_current_turn": False}, "task_not_grounded"),
        ({"current_task_scope": "travel_planning"}, "task_scope_not_exactly_matched"),
        ({"current_task_scope": ""}, "task_scope_not_exactly_matched"),
        ({"utility_signal": ContextUtilitySignal.UNKNOWN}, "utility_not_demonstrated"),
        (
            {"utility_signal": ContextUtilitySignal.STEERING_RISK},
            "utility_not_demonstrated",
        ),
        (
            {"utility_signal": ContextUtilitySignal.UNNECESSARY},
            "utility_not_demonstrated",
        ),
    ],
)
def test_context_shadow_rejects_unproven_influence(changes: dict, reason: str) -> None:
    result = assess_context_shadow(replace(_context(), **changes))
    assert result.disposition is ContextShadowDisposition.SKIP
    assert result.reason_code == reason


def test_context_scope_comparison_is_normalized_but_not_semantic_guessing() -> None:
    eligible = assess_context_shadow(
        replace(_context(), current_task_scope=" Interview_Answer_Style ")
    )
    assert eligible.disposition is ContextShadowDisposition.MEASURE_ONLY
    ambiguous = assess_context_shadow(
        replace(_context(), current_task_scope="interview")
    )
    assert ambiguous.disposition is ContextShadowDisposition.SKIP
