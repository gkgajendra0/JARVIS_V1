# Step 4 — Architecture Approval Record

## Status

**APPROVED BY OWNER — 2026-09-05**

The owner explicitly approved `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md` and authorized Step-4 production implementation to begin.

Approval instruction:

> Approved — start Step 4 implementation

This record closes the Step-4 human architecture approval gate. It does **not** mark Step 4 implemented, accepted, or merged.

## Approved architectural commitments

Implementation proceeds with the commitments defined in the proposal, including:

1. `ConversationSession` remains the owner of canonical accepted conversation truth.
2. `MemoryService` becomes the sole durable memory mutation/truth owner.
3. `ContextAssembler` becomes the sole Step-4 model-context release owner.
4. SQLCipher 4.17 / SQLite + FTS5 is the selected canonical local memory store.
5. A random database key is protected with Windows DPAPI user scope and purpose binding.
6. Temporal/provenance lifecycle is JARVIS-owned; historical change, correction, retraction, and forget remain distinct.
7. Models may propose candidates but never directly mutate canonical memory.
8. Explicit remember/correct/forget is implemented before implicit durable learning.
9. Implicit durable auto-admission starts disabled and remains calibration-gated.
10. Selected semantic retrieval is Qwen3-Embedding-0.6B 256d + FTS5 + equal RRF + top-3 Qwen3-Reranker-0.6B BF16, with broad automatic injection calibration-gated.
11. No vector database is introduced without measured scale evidence.
12. CycloneDX + a JARVIS Capability Registry provides the self-knowledge foundation.
13. Autonomous repair, code modification, deployment, or authority expansion remains out of Step-4 scope.

## Authorized implementation start

Dedicated implementation branch:

`implementation/step-4-memory-context`

First authorized implementation phase:

**Phase 4.0A — provenance + neutral security boundary**

Scope:

- stable JARVIS-owned `session_id`;
- stable JARVIS-owned `turn_id`;
- timezone-aware UTC `accepted_at`;
- provider item IDs retained only as optional external/diagnostic provenance;
- move/generalize the already-proven Windows DPAPI key-protection primitive behind neutral `jarvis.security` while preserving accepted identity behavior;
- keep all existing Step-1/2/3 quality gates green.

Explicitly not authorized as part of Phase 4.0A:

- canonical memory database implementation;
- automatic LLM memory writes;
- implicit durable admission;
- semantic memory injection;
- autonomous self-repair.

## Lifecycle consequence

The Step-4 lifecycle is now:

`REQUIREMENTS -> RESEARCH -> TECHNOLOGY DECISION -> ARCHITECTURE -> HUMAN APPROVAL [COMPLETE] -> IMPLEMENTATION [ACTIVE] -> AUTOMATED VALIDATION -> REAL HUMAN USE -> CORRECTION -> HUMAN ACCEPTANCE -> DOCUMENTATION RECONCILIATION -> PROTECTED-MAIN MERGE -> DONE`

`docs/CURRENT_ARCHITECTURE.md` remains unchanged until the relevant implementation has passed acceptance; approval of a proposal is not the same as accepted production architecture.
