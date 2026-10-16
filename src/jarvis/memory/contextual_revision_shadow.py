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
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .assertions import canonical_value_json
from .candidates import (
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from .contextual_control_shadow import (
    ContextualBoundaryDisposition,
    assess_contextual_memory_boundary,
)
from .explicit import (
    MemorySecretRejectedError,
    reject_prohibited_secret,
)
from .retrieval import RetrievalCandidate
from .revision_proposal_shadow import review_extracted_revision_shadow
from .revision_shadow import RevisionDisposition
from .revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from .service import canonical_memory_predicate
from .types import AssertionState, MemorySourceClass, Sensitivity, ValueType

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


_EXPLICIT_RETRACTION_CUE = re.compile(
    r"\b(?:i\s+(?:retract|withdraw)\b|"
    r"(?:i\s+)?take\s+(?:that|it|my\s+(?:statement|claim))\s+back\b|"
    r"w(?:a|i)pas\s+(?:leta|leti|lete|lo|lene)\b|"
    r"(?:retract|withdraw)\s+(?:my|the|that)\s+(?:claim|statement)\b)"
    r"|(?:वापस\s+ले(?:ता|ती|ते|ना|ता\s+हूँ|ती\s+हूँ)?)",
    flags=re.IGNORECASE,
)


def _has_explicit_retraction_cue(current_turn: str) -> bool:
    """Only high-precision direct withdrawal language, not generic 'wrong'.

    This is an intentionally *incomplete* research gate: uncertainty must
    escalate to clarification rather than hallucinating a retraction.
    """

    return bool(_EXPLICIT_RETRACTION_CUE.search(current_turn))


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
        if (
            assess_contextual_memory_boundary(turn.text)
            is ContextualBoundaryDisposition.EXPLICIT_CONTROL
        ):
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

    # Research data-egress interlock: only disposable synthetic conversations
    # can reach the optional contextual extractor in this draft.
    if not conversation.session_id.startswith("synthetic"):
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "synthetic_session_required"
        )

    # Strict accepted-turn guard before any memory reader or model invocation.
    if turn.role is not ConversationRole.USER or not any(
        accepted is turn for accepted in conversation.turns
    ):
        return ContextualRevisionReview(RevisionDisposition.SKIP, "untrusted_turn")
    if not conversation.turns or conversation.turns[-1] is not turn:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "not_latest_turn")
    if (
        assess_contextual_memory_boundary(turn.text)
        is ContextualBoundaryDisposition.EXPLICIT_CONTROL
    ):
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
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "model_calls_disabled"
        )

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
            # Compare the value AND normalized text against the canonical row
            # within the same read-only connection invocation. A forged/stale
            # retrieval object must never supply instructions to the extractor.
            content_bound = await reader.verify_exact_content(
                subject_scope="personal",
                subject="owner",
                predicate=key,
                assertion_id=assertion.assertion_id,
                value_json=canonical_value_json(ValueType.TEXT, assertion.value),
                normalized_text=assertion.normalized_text,
            )
            if not content_bound:
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
        proposal = await extractor.extract_contextual(text=turn.text, context=context)
    except Exception:  # noqa: BLE001 - third-party SDK failures fail closed
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
                RevisionDisposition.NEEDS_CLARIFICATION,
                "target_not_in_verified_context",
            )

        # A model's single selected predicate cannot establish which of
        # multiple retrieved memories the owner intended to correct. The
        # prior candidate list is evidence, not semantic target authority.
        # An independently grounded target-selection proof is a separate gate.
        if len(seen_keys) > 1:
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION,
                "multiple_verified_targets_need_clarification",
            )

        # Retraction requires direct withdrawal evidence from the CURRENT
        # accepted turn. A statement that older information was wrong, or
        # that a replacement is undecided, is NOT automatically a retraction.
        # Conservative refusal is preferable to deleting a valid memory.
        if (
            proposal.intent is MemoryExtractionIntent.RETRACTION
            and not _has_explicit_retraction_cue(turn.text)
        ):
            return ContextualRevisionReview(
                RevisionDisposition.NEEDS_CLARIFICATION,
                "retraction_not_supported_by_current_turn",
            )

    outcome = await review_extracted_revision_shadow(
        proposal=proposal,
        accepted_user_turn=True,
        source_class=MemorySourceClass.OWNER_DIRECT,
        reader=reader,
    )
    return ContextualRevisionReview(outcome.disposition, outcome.reason_code)
