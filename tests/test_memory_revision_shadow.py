"""Offline revision-decision contracts; no cloud, canonical store or writes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.memory.candidates import MemoryExtractionSensitivity
from jarvis.memory.revision_shadow import (
    CanonicalRevisionWitness,
    RevisionDisposition,
    RevisionIntent,
    RevisionShadowInput,
    assess_revision_shadow,
)
from jarvis.memory.types import MemorySourceClass


def _witness(*, equivalent: bool | None = None) -> CanonicalRevisionWitness:
    return CanonicalRevisionWitness(
        assertion_id="opaque-assertion-1",
        assertion_version=4,
        canonical_source_ref="canonical:accepted-owner-turn",
        active=True,
        owner_authority_verified=True,
        same_subject_predicate_verified=True,
        meaning_equivalent_verified=equivalent,
    )


def _evidence(
    intent: RevisionIntent,
    witness: CanonicalRevisionWitness | None = None,
) -> RevisionShadowInput:
    return RevisionShadowInput(
        accepted_user_turn=True,
        source_class=MemorySourceClass.OWNER_DIRECT,
        sensitivity=MemoryExtractionSensitivity.NORMAL,
        intent=intent,
        witness=witness,
    )


def test_new_fact_proposal_can_be_reviewed_without_existing_memory() -> None:
    decision = assess_revision_shadow(_evidence(RevisionIntent.NEW_CANDIDATE))
    assert decision.disposition is RevisionDisposition.REVIEW
    assert not hasattr(decision, "memory_value")
    assert not hasattr(decision, "authorized_write")


@pytest.mark.parametrize(
    "intent",
    [
        RevisionIntent.FACT_CHANGE,
        RevisionIntent.FACT_CORRECTION,
        RevisionIntent.FACT_RETRACTION,
        RevisionIntent.DUPLICATE_SUSPECTED,
    ],
)
def test_unresolved_references_request_clarification_not_unsafe_updates(
    intent: RevisionIntent,
) -> None:
    result = assess_revision_shadow(_evidence(intent))
    assert result.disposition is RevisionDisposition.NEEDS_CLARIFICATION


@pytest.mark.parametrize(
    "intent",
    [
        RevisionIntent.FACT_CHANGE,
        RevisionIntent.FACT_CORRECTION,
        RevisionIntent.FACT_RETRACTION,
    ],
)
def test_verified_source_and_version_produce_review_only(
    intent: RevisionIntent,
) -> None:
    decision = assess_revision_shadow(_evidence(intent, _witness()))
    assert decision.disposition is RevisionDisposition.CONFLICT_REVIEW


def test_semantic_duplicate_requires_independently_verified_equivalence() -> None:
    assert (
        assess_revision_shadow(
            _evidence(RevisionIntent.DUPLICATE_SUSPECTED, _witness(equivalent=True))
        ).disposition
        is RevisionDisposition.DUPLICATE
    )
    assert (
        assess_revision_shadow(
            _evidence(RevisionIntent.DUPLICATE_SUSPECTED, _witness(equivalent=None))
        ).disposition
        is RevisionDisposition.NEEDS_CLARIFICATION
    )
    assert (
        assess_revision_shadow(
            _evidence(RevisionIntent.NEW_CANDIDATE, _witness(equivalent=False))
        ).disposition
        is RevisionDisposition.CONFLICT_REVIEW
    )


@pytest.mark.parametrize(
    "bad_witness",
    [
        replace(_witness(), assertion_id=""),
        replace(_witness(), assertion_version=0),
        replace(_witness(), canonical_source_ref="model:hallucinated-reference"),
        replace(_witness(), active=False),
        replace(_witness(), owner_authority_verified=False),
    ],
)
def test_missing_or_unverified_canonical_proof_fails_closed(
    bad_witness: CanonicalRevisionWitness,
) -> None:
    result = assess_revision_shadow(
        _evidence(RevisionIntent.FACT_CORRECTION, bad_witness)
    )
    assert result.disposition is RevisionDisposition.SKIP


def test_unresolved_subject_match_requests_clarification() -> None:
    result = assess_revision_shadow(
        _evidence(
            RevisionIntent.FACT_CORRECTION,
            replace(_witness(), same_subject_predicate_verified=False),
        )
    )
    assert result.disposition is RevisionDisposition.NEEDS_CLARIFICATION


@pytest.mark.parametrize(
    "disallowed",
    [
        _evidence(RevisionIntent.FACT_CORRECTION, _witness()),
        replace(
            _evidence(RevisionIntent.FACT_CORRECTION, _witness()),
            source_class=MemorySourceClass.TOOL_UNTRUSTED,
        ),
    ],
)
def test_nonowner_or_unaccepted_turns_cannot_authorize_revisions(
    disallowed: RevisionShadowInput,
) -> None:
    # The first fixture is accepted; exercise the unaccepted-turn path.
    unaccepted = replace(disallowed, accepted_user_turn=False)
    assert (
        assess_revision_shadow(unaccepted).disposition
        is RevisionDisposition.SKIP
    )
    if disallowed.source_class is not MemorySourceClass.OWNER_DIRECT:
        assert (
            assess_revision_shadow(disallowed).disposition
            is RevisionDisposition.SKIP
        )


@pytest.mark.parametrize(
    "sensitivity",
    [MemoryExtractionSensitivity.SENSITIVE, MemoryExtractionSensitivity.SECRET],
)
def test_sensitive_corrections_are_never_reviewed_here(
    sensitivity: MemoryExtractionSensitivity,
) -> None:
    result = assess_revision_shadow(
        replace(
            _evidence(RevisionIntent.FACT_CORRECTION, _witness()),
            sensitivity=sensitivity,
        )
    )
    assert result.disposition is RevisionDisposition.SKIP


def test_none_intent_skips_even_with_verified_witness() -> None:
    result = assess_revision_shadow(_evidence(RevisionIntent.NONE, _witness()))
    assert result.disposition is RevisionDisposition.SKIP
