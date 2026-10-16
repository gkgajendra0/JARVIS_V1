"""Offline research connection to the EXISTING local Qwen/FTS5 retrieval API.

No new embedder, reranker, memory store, model router or provider is installed.
The injected QueryEmbeddingEncoder / SemanticRetrievalService are existing
JARVIS contracts and can be synthetic offline adapters in tests.

Never called from production voice; model calls are disabled by default.
"""

from __future__ import annotations

import asyncio

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .contextual_control_shadow import (
    ContextualBoundaryDisposition,
    assess_contextual_memory_boundary,
)
from .contextual_revision_shadow import (
    ContextualMemoryExtractor,
    ContextualRevisionReview,
    review_contextual_revision_shadow,
)
from .explicit import (
    MemorySecretRejectedError,
    reject_prohibited_secret,
)
from .retrieval import (
    RetrievalConstraints,
    RetrievalEligibility,
    SemanticRetrievalService,
)
from .retrieval_models import QueryEmbeddingEncoder
from .revision_shadow import RevisionDisposition
from .revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from .types import AuthorityClass, Sensitivity

_MAX_INPUT_LENGTH = 1200
_MAX_RESULTS = 3

_OWNER_STANDARD_ELIGIBILITY = RetrievalEligibility(
    authorities=frozenset({AuthorityClass.OWNER_DIRECT, AuthorityClass.OWNER_EXPLICIT}),
    sensitivities=frozenset({Sensitivity.STANDARD}),
)
_OWNER_SCOPE = RetrievalConstraints(subject_scope="personal", subject="owner")


async def review_with_existing_retrieval_shadow(
    *,
    conversation: ConversationSession,
    turn: ConversationTurn,
    encoder: QueryEmbeddingEncoder,
    retrieval: SemanticRetrievalService,
    reader: CanonicalRevisionSnapshotReader,
    extractor: ContextualMemoryExtractor,
    allow_model_calls: bool = False,
) -> ContextualRevisionReview:
    """Reuse the exact production-capable retrieval contracts in shadow mode.

    Selection relevance remains unproven: this integration merely performs
    eligible local retrieval with fixed owner/sensitivity filters and delegates
    content/version checks and correction review to prior shadow modules.
    """

    if not isinstance(conversation, ConversationSession):
        raise TypeError("conversation must be ConversationSession")
    if not isinstance(turn, ConversationTurn):
        raise TypeError("turn must be ConversationTurn")
    if not callable(getattr(encoder, "encode_query", None)):
        raise TypeError("encoder must expose encode_query")
    if not isinstance(retrieval, SemanticRetrievalService):
        raise TypeError("retrieval must be SemanticRetrievalService")
    if not isinstance(reader, CanonicalRevisionSnapshotReader):
        raise TypeError("reader must be CanonicalRevisionSnapshotReader")
    if not callable(getattr(extractor, "extract_contextual", None)):
        raise TypeError("extractor must support extract_contextual")

    # Research data-egress interlock: only disposable synthetic conversations
    # can reach the optional contextual extractor in this draft.
    if not conversation.session_id.startswith("synthetic"):
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "synthetic_session_required"
        )

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
    if len(turn.text) > _MAX_INPUT_LENGTH:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "turn_too_large")
    try:
        reject_prohibited_secret(predicate="candidate_extraction", value=turn.text)
    except MemorySecretRejectedError:
        return ContextualRevisionReview(RevisionDisposition.SKIP, "secret_guard")

    if not allow_model_calls:
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "model_calls_disabled"
        )

    try:
        # Reuse existing local query embeddings, off the event loop, not an
        # extra provider/model call. No GPU models run in fixture-based CI.
        vector = await asyncio.to_thread(encoder.encode_query, turn.text)
        candidates = await retrieval.retrieve_first_stage(
            turn.text,
            vector,
            eligibility=_OWNER_STANDARD_ELIGIBILITY,
            constraints=_OWNER_SCOPE,
            limit=_MAX_RESULTS,
        )
    except Exception:  # noqa: BLE001 - optional local retrieval failures fail closed
        return ContextualRevisionReview(
            RevisionDisposition.SKIP, "bounded_retrieval_failed"
        )

    return await review_contextual_revision_shadow(
        conversation=conversation,
        turn=turn,
        retrieved=candidates,
        reader=reader,
        extractor=extractor,
        allow_model_calls=True,
    )
