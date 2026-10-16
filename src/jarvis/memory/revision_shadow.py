"""Research-only, source-grounded review for memory revisions.

This module never reads a store, calls a model, mutates an assertion, or
returns memory contents. The *caller* must independently verify canonical
identity, version, provenance and semantic match. Until a trusted resolver
exists those booleans are oracle-like research evidence, NOT permission
for production admission, deletion, or context injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .candidates import MemoryExtractionSensitivity
from .types import MemorySourceClass


class RevisionIntent(StrEnum):
    NEW_CANDIDATE = "new_candidate"
    DUPLICATE_SUSPECTED = "duplicate_suspected"
    FACT_CHANGE = "fact_change"
    FACT_CORRECTION = "fact_correction"
    FACT_RETRACTION = "fact_retraction"
    NONE = "none"


class RevisionDisposition(StrEnum):
    SKIP = "skip"
    REVIEW = "review"
    DUPLICATE = "duplicate"
    CONFLICT_REVIEW = "conflict_review"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass(frozen=True, slots=True)
class CanonicalRevisionWitness:
    """Trusted resolver's *opaque*, versioned canonical reference evidence."""

    assertion_id: str
    assertion_version: int
    canonical_source_ref: str
    active: bool
    latest_version_verified: bool
    owner_authority_verified: bool
    same_subject_predicate_verified: bool
    meaning_equivalent_verified: bool | None = None


@dataclass(frozen=True, slots=True)
class RevisionShadowInput:
    """Accepted owner-turn classification plus independently resolved evidence."""

    accepted_user_turn: bool
    source_class: MemorySourceClass
    sensitivity: MemoryExtractionSensitivity
    intent: RevisionIntent
    witness: CanonicalRevisionWitness | None = None


@dataclass(frozen=True, slots=True)
class RevisionShadowDecision:
    disposition: RevisionDisposition
    reason_code: str


def assess_revision_shadow(evidence: RevisionShadowInput) -> RevisionShadowDecision:
    """Fail closed unless sufficient canonical evidence is available.

    All outputs are research-only classifications. Even CONFLICT_REVIEW does
    NOT authorize a memory update or a permanent quarantine admission.
    """

    if not isinstance(evidence, RevisionShadowInput):
        raise TypeError("evidence must be RevisionShadowInput")
    if not evidence.accepted_user_turn or evidence.source_class is not (
        MemorySourceClass.OWNER_DIRECT
    ):
        return RevisionShadowDecision(RevisionDisposition.SKIP, "untrusted_turn")
    if evidence.sensitivity is not MemoryExtractionSensitivity.NORMAL:
        return RevisionShadowDecision(RevisionDisposition.SKIP, "sensitive_input")
    if evidence.intent is RevisionIntent.NONE:
        return RevisionShadowDecision(RevisionDisposition.SKIP, "no_revision_intent")

    witness = evidence.witness
    if witness is None:
        if evidence.intent is RevisionIntent.NEW_CANDIDATE:
            return RevisionShadowDecision(RevisionDisposition.REVIEW, "new_proposal")
        return RevisionShadowDecision(
            RevisionDisposition.NEEDS_CLARIFICATION, "unresolved_existing_memory"
        )

    if (
        not isinstance(witness.assertion_id, str)
        or not witness.assertion_id.strip()
        or type(witness.assertion_version) is not int
        or witness.assertion_version < 1
        or not isinstance(witness.canonical_source_ref, str)
        or not witness.canonical_source_ref.startswith("canonical:")
        or not witness.active
        or not witness.latest_version_verified
        or not witness.owner_authority_verified
    ):
        return RevisionShadowDecision(
            RevisionDisposition.SKIP, "unverified_canonical_reference"
        )
    if not witness.same_subject_predicate_verified:
        return RevisionShadowDecision(
            RevisionDisposition.NEEDS_CLARIFICATION, "ambiguous_memory_target"
        )

    if evidence.intent in {
        RevisionIntent.FACT_CHANGE,
        RevisionIntent.FACT_CORRECTION,
        RevisionIntent.FACT_RETRACTION,
    }:
        return RevisionShadowDecision(
            RevisionDisposition.CONFLICT_REVIEW, "verified_lifecycle_review"
        )

    if witness.meaning_equivalent_verified is True:
        return RevisionShadowDecision(
            RevisionDisposition.DUPLICATE, "trusted_semantic_equivalence"
        )
    if witness.meaning_equivalent_verified is False:
        return RevisionShadowDecision(
            RevisionDisposition.CONFLICT_REVIEW, "verified_distinct_value"
        )
    return RevisionShadowDecision(
        RevisionDisposition.NEEDS_CLARIFICATION,
        "semantic_relationship_not_verified",
    )
