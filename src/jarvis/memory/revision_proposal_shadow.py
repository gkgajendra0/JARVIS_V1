"""Research-only bridge: typed extracted proposals -> canonical revision reviews.

Does not run a model, access an owner memory database, write assertions,
authorize admission, or release memory values to ContextAssembler.
Any canonical reader MUST be explicitly injected; tests use a disposable
synthetic SQLite database or a fake resolver. A model-selected predicate is
NOT proof that the utterance actually referred to that stored fact.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import (
    MemoryCandidateDisposition,
    MemoryCandidatePolicy,
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from .revision_shadow import (
    RevisionDisposition,
    RevisionIntent,
    RevisionShadowInput,
    assess_revision_shadow,
)
from .revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from .service import canonical_memory_predicate
from .types import MemorySourceClass

_INTENTS: dict[
    tuple[MemoryExtractionIntent, MemoryCandidateType], RevisionIntent
] = {
    (MemoryExtractionIntent.HISTORICAL_CHANGE, MemoryCandidateType.FACT_CHANGE):
        RevisionIntent.FACT_CHANGE,
    (MemoryExtractionIntent.CORRECTION, MemoryCandidateType.FACT_CORRECTION):
        RevisionIntent.FACT_CORRECTION,
    (MemoryExtractionIntent.RETRACTION, MemoryCandidateType.FACT_RETRACTION):
        RevisionIntent.FACT_RETRACTION,
    (MemoryExtractionIntent.CANDIDATE, MemoryCandidateType.FACT):
        RevisionIntent.NEW_CANDIDATE,
    (MemoryExtractionIntent.CANDIDATE, MemoryCandidateType.PREFERENCE):
        RevisionIntent.NEW_CANDIDATE,
    (MemoryExtractionIntent.CANDIDATE, MemoryCandidateType.RULE):
        RevisionIntent.NEW_CANDIDATE,
}
_UNSAFE_SOURCE_REASONS = frozenset(
    {
        "canonical_sensitivity_restricted",
        "canonical_owner_source_not_verified",
        "canonical_source_missing",
        "canonical_version_not_latest",
        "canonical_lineage_unverified",
        "canonical_lineage_source_unverified",
    }
)


@dataclass(frozen=True, slots=True)
class RevisionProposalReview:
    """Only decision and reason; no assertion ID, value or source evidence."""

    disposition: RevisionDisposition
    reason_code: str


async def review_extracted_revision_shadow(
    *,
    proposal: MemoryExtractionProposal,
    accepted_user_turn: bool,
    source_class: MemorySourceClass,
    reader: CanonicalRevisionSnapshotReader,
) -> RevisionProposalReview:
    """Evaluate a provider-created proposal against canonical metadata.

    This is still an *untrusted* proposal; exact predicate equality does not
    prove semantic correctness or create memory-update authority.
    """

    if not isinstance(proposal, MemoryExtractionProposal):
        raise TypeError("proposal must be a MemoryExtractionProposal")
    if not isinstance(reader, CanonicalRevisionSnapshotReader):
        raise TypeError("reader must be a CanonicalRevisionSnapshotReader")

    if not accepted_user_turn or source_class is not MemorySourceClass.OWNER_DIRECT:
        return RevisionProposalReview(RevisionDisposition.SKIP, "untrusted_turn")

    if proposal.sensitivity is not MemoryExtractionSensitivity.NORMAL:
        return RevisionProposalReview(RevisionDisposition.SKIP, "sensitive_proposal")

    policy = MemoryCandidatePolicy().evaluate(proposal)
    if policy.disposition is MemoryCandidateDisposition.DROP:
        return RevisionProposalReview(RevisionDisposition.SKIP, policy.reason_code)

    intent = _INTENTS.get((proposal.intent, proposal.candidate_type))
    if intent is None:
        return RevisionProposalReview(
            RevisionDisposition.SKIP, "unrecognized_revision_intent_pair"
        )
    # The model's subject/predicate are hints only. Never query another
    # person's records even if the provider requests a different subject.
    if proposal.subject != "owner" or not proposal.predicate:
        return RevisionProposalReview(
            RevisionDisposition.NEEDS_CLARIFICATION, "unresolved_owner_target"
        )

    try:
        key = canonical_memory_predicate(proposal.predicate)
    except (ValueError, TypeError):
        return RevisionProposalReview(
            RevisionDisposition.NEEDS_CLARIFICATION, "invalid_memory_key"
        )

    resolution = await reader.resolve_exact(
        subject_scope="personal", subject="owner", predicate=key
    )
    if resolution.reason_code in _UNSAFE_SOURCE_REASONS:
        return RevisionProposalReview(
            RevisionDisposition.SKIP, resolution.reason_code
        )
    decision = assess_revision_shadow(
        RevisionShadowInput(
            accepted_user_turn=accepted_user_turn,
            source_class=source_class,
            sensitivity=proposal.sensitivity,
            intent=intent,
            witness=resolution.witness,
        )
    )
    return RevisionProposalReview(decision.disposition, decision.reason_code)
