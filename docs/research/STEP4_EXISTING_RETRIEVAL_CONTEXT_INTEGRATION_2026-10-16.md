# Phase 4.4 — Existing retrieval engine integration (2026-10-16)

**Status: draft research / disconnected from production / zero live model calls.**

Already built and measured in prior JARVIS work:
- SQLCipher/DPAPI canonical memory with explicit owner persistence.
- Local Qwen3-Embedding 0.6B + Qwen3-Reranker 0.6B and FTS5 hybrid retrieval.
- Gemini/OpenAI typed `MemoryExtractionProposal` provider adapters.
- PRs #264–268: revision shadow review, canonical lineage/provenance,
  correction proposal classification, context binding and exact value match.

This branch adds one independent **research-only** function
`review_with_existing_retrieval_shadow` that connects the earlier
components without running or replacing their local model weights:

1. Require most recent *accepted* owner turn, non-secret and not a separately
   recognized explicit Phase-4.3 memory command.
2. Stop unless `allow_model_calls=True` was deliberately passed.
3. Use injected existing `QueryEmbeddingEncoder.encode_query` off the event
   loop, then existing `SemanticRetrievalService.retrieve_first_stage`
   with exact `personal/owner` constraints and source policy
   `OWNER_EXPLICIT | OWNER_DIRECT`, `STANDARD` sensitivity.
4. Limit to at most three candidate results (this is not an accuracy claim).
5. Delegate to PR #268's canonical ID+value/normalized text source binding,
   bounded previous owner turns, current-turn-grounded structured extractor,
   and review-only decision result.

Tests use synthetic 256d one-hot embeddings, in-memory-like temporary
SQLite and the actual existing `SemanticEmbeddingStore` and
`SemanticRetrievalService` without loading either Qwen model. Tests
cover owner-subject restriction, selected canonical value, default-OFF
encoder guard and malformed embedding failure.

**Important limitation:** This is an integration seam and tests metadata
eligibility, not true candidate recall or precision in English/Hindi/Hinglish.
No prompt-injection or ASR robustness claims follow from synthetic fixtures.
It is not imported from `MemoryCandidateCoordinator`, `MemoryService`
or LiveKit, and is not authorized to change permanent memories or release
anything into `ContextAssembler`.

**Next:** Correct the Phase 4.3 implicit-vs-explicit classification collision
without weakening explicit authorization; measure independent retrieval
and contextual target-binding quality on new, private blind cases.
Any real Gemini run requires approved egress/data scope and a bounded
free-tier call budget; the existing owner-memory payload is excluded.
