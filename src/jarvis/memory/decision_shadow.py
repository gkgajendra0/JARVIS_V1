"""Research-only, non-authoritative decision probes for Step 4 memory.

Neither probe calls a provider, opens a database, returns memory contents,
mutates canonical memory, or connects to ContextAssembler. An eligible result
means ONLY that a candidate may be measured in a shadow experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .candidates import (
    MemoryCandidateDisposition,
    MemoryCandidatePolicy,
    MemoryCandidateType,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from .types import AssertionState, AuthorityClass, MemorySourceClass, Sensitivity


class CandidateReviewDisposition(StrEnum):
    SKIP = "skip"
    REVIEW = "review"
    CONFLICT_REVIEW = "conflict_review"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class CandidateShadowInput:
    """Caller-supplied, non-authoritative research evidence only."""

    proposal: MemoryExtractionProposal
    source_class: MemorySourceClass
    accepted_user_turn: bool
    current_exact_value: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateShadowDecision:
    disposition: CandidateReviewDisposition
    reason_code: str


def assess_candidate_shadow(
    evidence: CandidateShadowInput,
) -> CandidateShadowDecision:
    """Assess an *existing proposal*; never grant durable write permission."""

    if not isinstance(evidence, CandidateShadowInput):
        raise TypeError("evidence must be CandidateShadowInput")
    if not evidence.accepted_user_turn or evidence.source_class is not (
        MemorySourceClass.OWNER_DIRECT
    ):
        return CandidateShadowDecision(
            CandidateReviewDisposition.SKIP, "not_accepted_direct_owner_turn"
        )
    proposal = evidence.proposal
    if proposal.sensitivity is not MemoryExtractionSensitivity.NORMAL:
        return CandidateShadowDecision(
            CandidateReviewDisposition.SKIP, "not_normal_sensitivity"
        )

    policy = MemoryCandidatePolicy().evaluate(proposal)
    if policy.disposition is MemoryCandidateDisposition.DROP:
        return CandidateShadowDecision(
            CandidateReviewDisposition.SKIP, policy.reason_code
        )

    if proposal.candidate_type in {
        MemoryCandidateType.FACT_CHANGE,
        MemoryCandidateType.FACT_CORRECTION,
        MemoryCandidateType.FACT_RETRACTION,
    }:
        return CandidateShadowDecision(
            CandidateReviewDisposition.CONFLICT_REVIEW,
            "lifecycle_change_requires_review",
        )

    if evidence.current_exact_value is not None:
        if evidence.current_exact_value.strip().casefold() == (
            (proposal.value or "").strip().casefold()
        ):
            return CandidateShadowDecision(
                CandidateReviewDisposition.DUPLICATE, "exact_normalized_duplicate"
            )
        return CandidateShadowDecision(
            CandidateReviewDisposition.CONFLICT_REVIEW,
            "different_current_value_requires_review",
        )

    return CandidateShadowDecision(
        CandidateReviewDisposition.REVIEW, "eligible_proposal_requires_review"
    )


class ContextUtilitySignal(StrEnum):
    """A hypothetical adviser label, never an authorization or confidence proof."""

    UNKNOWN = "unknown"
    ESSENTIAL = "essential"
    HELPFUL = "helpful"
    UNNECESSARY = "unnecessary"
    STEERING_RISK = "steering_risk"


class ContextShadowDisposition(StrEnum):
    SKIP = "skip"
    MEASURE_ONLY = "measure_only"


@dataclass(frozen=True, slots=True)
class ContextShadowEvidence:
    """Only canonical metadata and a scope label; no memory value or prompt."""

    authority: AuthorityClass
    source: MemorySourceClass
    sensitivity: Sensitivity
    state: AssertionState
    canonical_source_ref: str | None
    memory_scope: str | None
    current_task_scope: str | None
    task_grounded_in_current_turn: bool
    conflicts_with_current_turn: bool
    utility_signal: ContextUtilitySignal


@dataclass(frozen=True, slots=True)
class ContextShadowDecision:
    disposition: ContextShadowDisposition
    reason_code: str


def assess_context_shadow(
    evidence: ContextShadowEvidence,
) -> ContextShadowDecision:
    """Select a *measurement candidate* only; never release context to an LLM.

    Real production admission must additionally verify freshness and identity
    from canonical data rather than trusting these caller-supplied metadata.
    """

    if not isinstance(evidence, ContextShadowEvidence):
        raise TypeError("evidence must be ContextShadowEvidence")
    deny = ContextShadowDisposition.SKIP
    if evidence.authority not in {
        AuthorityClass.OWNER_DIRECT,
        AuthorityClass.OWNER_EXPLICIT,
    } or evidence.source not in {
        MemorySourceClass.OWNER_DIRECT,
        MemorySourceClass.OWNER_EXPLICIT,
    }:
        return ContextShadowDecision(deny, "unapproved_source_or_authority")
    if evidence.sensitivity is not Sensitivity.STANDARD:
        return ContextShadowDecision(deny, "sensitivity_not_admitted")
    if evidence.state is not AssertionState.ACTIVE:
        return ContextShadowDecision(deny, "not_current_active_assertion")
    if not isinstance(evidence.canonical_source_ref, str) or not (
        evidence.canonical_source_ref.strip()
    ):
        return ContextShadowDecision(deny, "missing_canonical_provenance")
    if evidence.conflicts_with_current_turn:
        return ContextShadowDecision(deny, "current_turn_has_priority")
    if not evidence.task_grounded_in_current_turn:
        return ContextShadowDecision(deny, "task_not_grounded")
    if (
        not isinstance(evidence.memory_scope, str)
        or not isinstance(evidence.current_task_scope, str)
        or not evidence.memory_scope.strip()
        or not evidence.current_task_scope.strip()
        or evidence.memory_scope.strip().casefold()
        != evidence.current_task_scope.strip().casefold()
    ):
        return ContextShadowDecision(deny, "task_scope_not_exactly_matched")
    if evidence.utility_signal not in {
        ContextUtilitySignal.ESSENTIAL,
        ContextUtilitySignal.HELPFUL,
    }:
        return ContextShadowDecision(deny, "utility_not_demonstrated")
    return ContextShadowDecision(
        ContextShadowDisposition.MEASURE_ONLY, "eligible_for_shadow_evaluation_only"
    )
