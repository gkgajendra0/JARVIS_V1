"""Research-only context -> structured extraction -> canonical revision review.

This is an additive opt-in shadow integration, NOT a production runtime path.
Context is bounded, checked against canonical metadata and passed only to an
explicitly injected extractor. There is no database opener, deployment flag,
automatic memory write, context injection, or automatic model invocation.

The caller supplies *retrieved* candidates from an already eligible,
local/approved retrieval pipeline. Their presence does not establish correct
semantic relevance, and the model's proposed target is never authority.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from .explicit import (
    MemorySecretRejectedError,
    is_explicit_memory_control_text,
    reject_prohibited_secret,
)
from .retrieval import RetrievalCandidate
from .revision_proposal_shadow import review_extracted_revision_shadow
from .revision_shadow import RevisionDisposition
from .revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from .service import canonical_memory_predicate
from .types import AssertionState, MemorySourceClass, Sensitivity

_MAX_CONTEXT_CANDIDATES = 3
_MAX_RECENT_OWNER_TURNS = 3
_MAX_USER_TEXT = 1200
_MAX_PRIOR_TEXT = 500
_MAX_MEMORY_TEXT = 500
_REVISION_INTENTS = frozenset(
    {
        MemoryExtractionIntent.HISTORICAL_CHANGE,
        MemoryExtractionIntent.CORRECTION,
        MemoryExtractionIntent.RETRACTION,
    }
)


class ContextualMemoryExtractor(Protocol):
    async def extract_contextual(
        self, *, text: str, context: str
    ) -> MemoryExtractionProposal: ...


@dataclass(frozen=True, slots=True)
class ContextualRevisionReview:
    disposition: RevisionDisposition
    reason_code: str


def _safe_prior_turns(
    conversation: ConversationSession, current: ConversationTurn
) -> tuple[str, ...]:
    seen_current = False
    prior: list[str] = []
    for turn in reversed(conversation.turns):
        if turn.turn_id == current.turn_id:
            seen_current = True
            continue
        if not seen_current or turn.role is not ConversationRole.USER:
            continue
        if is_explicit_memory_control_text(turn.text):
            continue
        try:
            reject_prohibited_secret(predicate="prior_user_turn", value=turn.text)
        except MemorySecretRejectedError:
            continue
        if len(turn.text) <= _MAX_PRIOR_TEXT:
            prior.append(turn.text)
        if len(prior) >= _MAX_RECENT_OWNER_TURNS:
            break
    prior.reverse()
    return tuple(prior)


async def review_contextual_revision_shadow(
    *,
    conversation: ConversationSession,
    turn: ConversationTurn,
    retrieved: Sequence[RetrievalCandidate],
    reader: CanonicalRevisionSnapshotReader,
    extractor: ContextualMemoryExtractor,
    allow_model_calls: bool = False,
) -> ContextualRevisionReview:
    """Propose a REVIEW only; never create or change long-term memory.

    `allow_model_calls` is deliberately false by default. This research helper
    must not receive owner-sensitive values, unredacted production retrievals,
    or an external extractor without an additional privacy/consent gate.
    """

    if not isinstance(conversation, ConversationSession):
        raise TypeError("conversation must be ConversationSession")
    if not isinstance(turn, ConversationTurn):
        raise TypeError("turn must be ConversationTurn")
    if not isinstance(reader, CanonicalRevisionSnapshotReader):
        raise TypeError("reader must be CanonicalRevisionSnapshotReader")
    if not callable(getattr(extractor, "extract_contextual", None)):
        raise TypeError("extractor must support extract_contextual")
    if isinstance(retrieved, (str, bytes)) or not isinstance(retrieved, Sequence):
        raise TypeError("retrieved must be a sequence of RetrievalCandidate")

    # Strict accepted-turn guard before any memory reader or model invocation.
    if turn.role is not ConversationRole.USER or turn not in conversation.turns:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "untrusted_turn")
    if not conversation.turns or conversation.turns[-1].turn_id != turn.turn_id:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "not_latest_turn")
    if is_explicit_memory_control_text(turn.text):
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "explicit_memory_control_boundary"
        )
    if len(turn.text) > _MAX_USER_TEXT:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "turn_too_large")
    try:
        reject_prohibited_secret(predicate="candidate_extraction", value=turn.text)
    except MemorySecretRejectedError:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "secret_guard")

    if not allow_model_calls:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "model_calls_disabled")

    seen_keys: set[str] = set()
    if not retrieved:
        # No related canonical memory evidence: a contextual review could
        # still be meaningful, but a proposed correction stays unresolved.
        valid_candidates: list[dict[str, str]] = []
    else:
        if len(retrieved) > _MAX_CONTEXT_CANDIDATES:
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION, "candidate_budget_exceeded"
            )
        valid_candidates = []
        for candidate in retrieved:
            if not isinstance(candidate, RetrievalCandidate):
                return ContextualRevisionReview(
                    RevisionDisposition.SKIP, "invalid_retrieval_candidate"
                )
            assertion = candidate.assertion
            if (
                assertion.subject_scope != "personal"
                or assertion.subject != "owner"
                or assertion.sensitivity is not Sensitivity.STANDARD
                or assertion.state is not AssertionState.ACTIVE
                or assertion.system_to is not None
                or assertion.valid_to is not None
                or not isinstance(assertion.value, str)
                or len(assertion.value) > _MAX_MEMORY_TEXT
            ):
                return ContextualRevisionReview(
                    RevisionDisposition.SKIP, "unsafe_retrieval_context"
                )
            try:
                key = canonical_memory_predicate(assertion.predicate)
                reject_prohibited_secret(predicate=key, value=assertion.value)
            except (ValueError, MemorySecretRejectedError):
                return ContextualRevisionReview(
                    RevisionDisposition.SKIP, "unsafe_retrieval_context"
                )
            if key in seen_keys:
                return ContextualRevisionReview(
                    RevisionDisposition.NEEDS_CLARIFICATION, "ambiguous_retrieval_keys"
                )
            seen_keys.add(key)
            resolved = await reader.resolve_exact(
                subject_scope="personal", subject="owner", predicate=key
            )
            if (
                resolved.witness is None
                or resolved.witness.assertion_id != assertion.assertion_id
            ):
                return ContextualRevisionReview(
                    RevisionDisposition.SKIP, "unverified_retrieval_candidate"
                )
            valid_candidates.append(
                {
                    "predicate": key,
                    "current_value": assertion.value,
                }
            )

    context = json.dumps(
        {
            "recent_accepted_owner_turns": _safe_prior_turns(conversation, turn),
            "verified_current_memory_candidates": valid_candidates,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    try:
        proposal = await extractor.extract_contextual(
            text=turn.text, context=context
        )
    except Exception:
        # Research isolation: provider errors never become admission/release.
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "contextual_extractor_failed"
        )
    if not isinstance(proposal, MemoryExtractionProposal):
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "invalid_contextual_proposal"
        )
    if proposal.sensitivity is not MemoryExtractionSensitivity.NORMAL:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "sensitive_proposal")

    if proposal.intent in _REVISION_INTENTS:
        if not proposal.predicate:
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION, "model_target_missing"
            )
        try:
            proposed_key = canonical_memory_predicate(proposal.predicate)
        except (ValueError, TypeError):
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION, "model_target_invalid"
            )
        if proposed_key not in seen_keys:
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION, "target_not_in_verified_context"
            )

    outcome = await review_extracted_revision_shadow(
        proposal=proposal,
        accepted_user_turn=True,
        source_class=MemorySourceClass.OWNER_DIRECT,
        reader=reader,
    )
    return ContextualRevisionReview(outcome.disposition, outcome.reason_code)
